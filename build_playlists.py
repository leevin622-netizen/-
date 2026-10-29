"""
בונה את הקטלוג של "פלייליסטים קיימים": מחפש פלייליסטים בספוטיפיי בארצות הברית ובישראל,
לפי קטגוריות (ובעברית לשוק הישראלי), מביא לכל אחד את מספר העוקבים, ושומר את 500 הישראלים
ו-500 האמריקאים הגדולים.
האפליקציה מריצה את זה בעצמה ברקע כשהקטלוג ריק או ישן משבוע. אפשר גם ידנית, מתוך תיקיית הפרויקט:
    .\\venv\\Scripts\\python build_playlists.py
אפשר לעצור באמצע ולהתחיל שוב: מה שכבר נאסף לא נאסף מחדש.
הבנייה איטית בכוונה (בקשה אחת בכל פעם, עם הפסקה), כי ספוטיפיי חוסם לכמה שעות מי שמציף אותו.
"""
import os
import re
import threading
import time

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

import catalog

RETRIES = 2
# המתנה ארוכה מזו לא שווה לחכות לה. עוצרים, ואפשר להמשיך אחר כך
MAX_WAIT_SECONDS = 600
# הפסקה אחרי כל בקשה: כ-2 בקשות בשנייה לכל היותר
PAUSE_SECONDS = 0.4
# אחרי עצירה (למשל בגלל חסימה) האפליקציה לא מנסה שוב לפני שעה
RETRY_AFTER_SECONDS = 3600

_lock = threading.Lock()
_state = {"running": False, "next_try": 0.0}


class RateLimited(RuntimeError):
    pass


def with_retry(call):
    """ספוטיפיי מגביל בקשות. מחכים קצת ומנסים שוב. אם ההמתנה ארוכה, עוצרים מיד."""
    for attempt in range(1, RETRIES + 1):
        try:
            result = call()
            time.sleep(PAUSE_SECONDS)
            return result
        except SpotifyException as error:
            if error.http_status != 429:
                raise
            # ספוטיפיי כותב כמה לחכות בכותרת Retry-After (או בהודעה)
            header = (getattr(error, "headers", None) or {}).get("Retry-After", "")
            match = re.search(r"after: (\d+)", str(error))
            wait = int(header) if str(header).isdigit() else int(match.group(1)) if match else 30 * attempt
            if wait > MAX_WAIT_SECONDS:
                raise RateLimited(
                    f"ספוטיפיי הגביל את הבקשות ל-{wait // 60} דקות. הבנייה נעצרה. "
                    "היא תמשיך ממקום העצירה בפעם הבאה"
                ) from error
            print(f"   ספוטיפיי ביקש להמתין, ממתינים {wait} שניות", flush=True)
            time.sleep(wait)
    raise RateLimited("ספוטיפיי ממשיך להגביל. הבנייה תמשיך מאותו מקום בפעם הבאה")


def medium_image(images):
    if not images:
        return ""
    return images[min(1, len(images) - 1)]["url"]


def search_pages(sp, term, market):
    """פלייליסטים לפי מונח ושוק. ספוטיפיי מחזיר גם ערכים ריקים בתוך הרשימה, מדלגים עליהם."""
    found = []
    for page in range(catalog.PAGES):
        result = with_retry(lambda: sp.search(
            q=term, type="playlist", market=market, limit=catalog.PAGE_SIZE, offset=page * catalog.PAGE_SIZE,
        ))["playlists"]
        items = result.get("items") or []
        if not items:
            break
        for item in items:
            if item and item.get("id") and catalog.allowed_name(item.get("name") or ""):
                found.append({
                    "id": item["id"], "name": item["name"].strip(),
                    "owner": (item.get("owner") or {}).get("display_name") or "",
                    "description": item.get("description") or "",
                    "image": medium_image(item.get("images")),
                })
    return found


def fetch_followers(sp, playlist_id):
    try:
        data = with_retry(lambda: sp.playlist(playlist_id, fields="followers"))
    except SpotifyException as error:
        if error.http_status in (400, 403, 404):
            # פלייליסט שנמחק או פרטי: לא שייך לקטלוג
            catalog.forget(playlist_id)
            return
        raise
    catalog.set_followers(playlist_id, (data.get("followers") or {}).get("total") or 0)


def make_client():
    load_dotenv()
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            os.getenv("SPOTIFY_CLIENT_ID"), os.getenv("SPOTIFY_CLIENT_SECRET"),
            cache_handler=MemoryCacheHandler(),
        ),
        retries=0, requests_timeout=15,
    )


def run(sp, log=print):
    """בונה או ממשיך לבנות. מחזיר True כשהקטלוג שלם, False אם נעצר באמצע."""
    catalog.reclassify()
    jobs = catalog.search_jobs()
    log(f"שלב 1: {len(jobs)} חיפושים")
    try:
        for number, (market, key, term) in enumerate(jobs, 1):
            done_key = f"{market}|{key}|{term}"
            if catalog.is_done(done_key):
                continue
            items = search_pages(sp, term, market)
            catalog.add_candidates(items, market, key)
            catalog.mark_done(done_key)
            log(f"[{number}/{len(jobs)}] {market} {key} {term!r}: {len(items)} פלייליסטים")
            # הקטלוג מתעדכן בהדרגה, כדי שמי שנכנס באמצע כבר יראה משהו
            if number % 20 == 0:
                catalog.select_top()

        pending = catalog.without_followers()
        log(f"שלב 2: מספר עוקבים ל-{len(pending)} פלייליסטים")
        for number, playlist_id in enumerate(pending, 1):
            fetch_followers(sp, playlist_id)
            if number % 100 == 0:
                log(f"  {number}/{len(pending)}")
                catalog.select_top()
    except RateLimited as error:
        log(f"\n{error}")
        catalog.select_top()
        return False
    catalog.select_top()
    catalog.mark_done(catalog.COMPLETE_KEY)
    log(f"סיימנו. {len(catalog.load())} פלייליסטים בקטלוג")
    return True


def is_running():
    return _state["running"]


def refresh_in_background():
    """מתחיל עדכון ברקע אם הקטלוג ריק או ישן, ואין עדכון שכבר רץ. בטוח לקרוא שוב ושוב."""
    if time.time() < _state["next_try"] or not catalog.needs_refresh():
        return
    with _lock:
        if _state["running"]:
            return
        _state["running"] = True

    def work():
        try:
            finished = run(make_client(), log=lambda text: print(f"[קטלוג] {text}", flush=True))
            if not finished:
                _state["next_try"] = time.time() + RETRY_AFTER_SECONDS
        except Exception as error:  # עדכון ברקע לא אמור להפיל את האפליקציה
            print(f"[קטלוג] העדכון נכשל: {error}", flush=True)
            _state["next_try"] = time.time() + RETRY_AFTER_SECONDS
        finally:
            _state["running"] = False

    threading.Thread(target=work, daemon=True, name="catalog-refresh").start()


if __name__ == "__main__":
    run(make_client())
