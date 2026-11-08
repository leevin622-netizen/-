"""
עדכון ברקע של כל מה שהאפליקציה שומרת מספוטיפיי:
1. אינדקס השירים (index_store), שממנו נבנים הפלייליסטים. כל מונח מתעדכן פעם בשבוע.
2. הקטלוג של "פלייליסטים קיימים": מחפש פלייליסטים בספוטיפיי בארצות הברית ובישראל,
לפי קטגוריות (ובעברית לשוק הישראלי), מביא לכל אחד את מספר העוקבים, ושומר את 500 הישראלים
ו-500 האמריקאים הגדולים.
האפליקציה מריצה את זה בעצמה ברקע, ובודקת שוב כל כמה שעות. אפשר גם ידנית, מתוך תיקיית הפרויקט:
    .\\venv\\Scripts\\python build_playlists.py
אפשר לעצור באמצע ולהתחיל שוב: מה שכבר נאסף לא נאסף מחדש.
הבנייה איטית בכוונה (בקשה אחת בכל פעם, עם הפסקה), כי ספוטיפיי חוסם לכמה שעות מי שמציף אותו.
"""
import json
import logging
import os
import re
import threading
import time

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

import build_index
import catalog
import engine
import index_store
from vibes import get_features

RETRIES = 2
# המתנה ארוכה מזו לא שווה לחכות לה. עוצרים, ואפשר להמשיך אחר כך
MAX_WAIT_SECONDS = 600
# הפסקה אחרי כל בקשה: בקשה אחת בשנייה לכל היותר
PAUSE_SECONDS = 1.0
# לא יותר מזה בקשות בהרצה אחת (כלומר בשעה). המכסה של ספוטיפיי משותפת לכל האפליקציה,
# ולכן העדכון ברקע לוקח ממנה מעט, והשאר נשאר למשתמשים באתר. 400 בשעה כבר הביאו לחסימה של יום,
# וגם 100 בשעה, שלוש שעות ברצף כשנוספו מונחים חדשים (8 בנובמבר), הביאו לחסימה של 24 שעות
REQUESTS_PER_RUN = 40
# כשמישהו השתמש באתר בדקות האחרונות, העדכון ברקע לא שולח בקשות, וממתין שהאתר יתפנה
USER_QUIET_SECONDS = 10 * 60
# אחרי עצירה (חלוקה לשעות, או חסימה) ממשיכים כעבור שעה, או כשהחסימה נגמרת
RETRY_AFTER_SECONDS = 3600
# אחרי שהכול מעודכן, בודקים שוב כעבור כמה שעות אם משהו התיישן
CHECK_AGAIN_SECONDS = 6 * 60 * 60

BLOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "spotify_block.json")

_lock = threading.Lock()
_state = {"running": False, "user_at": 0.0}


class RateLimited(RuntimeError):
    pass


def note_user_activity():
    """האתר מדווח שמשתמש פעיל עכשיו (בכל בקשה), כדי שהעדכון ברקע יפנה לו את המכסה של ספוטיפיי."""
    _state["user_at"] = time.time()


def users_active():
    return time.time() - _state["user_at"] < USER_QUIET_SECONDS


_sent = {"count": 0}


class _RetryAfterSpy(logging.Handler):
    """spotipy כותב את זמן החסימה רק ביומן. תופסים אותו משם כדי לדעת מתי לנסות שוב."""
    seconds = None

    def emit(self, record):
        match = re.search(r"after: (\d+) s", record.getMessage())
        if match:
            _RetryAfterSpy.seconds = int(match.group(1))


logging.getLogger("spotipy.util").addHandler(_RetryAfterSpy())


def blocked_until():
    """מתי החסימה של ספוטיפיי מסתיימת (0 אם אין חסימה ידועה). נשמר בדיסק, ושורד הפעלה מחדש."""
    try:
        with open(BLOCK_FILE, encoding="utf-8") as f:
            return float(json.load(f)["until"])
    except (OSError, ValueError, KeyError):
        return 0.0


def remember_block(seconds):
    """זוכר עד מתי ספוטיפיי חוסם. חסימה קצרה יותר לא מקצרת חסימה ידועה וארוכה יותר."""
    until = max(blocked_until(), time.time() + seconds + 60)
    os.makedirs(os.path.dirname(BLOCK_FILE), exist_ok=True)
    with open(BLOCK_FILE, "w", encoding="utf-8") as f:
        json.dump({"until": until}, f)


def with_retry(call):
    """ספוטיפיי מגביל בקשות. מחכים קצת ומנסים שוב. אם ההמתנה ארוכה, עוצרים מיד."""
    if _sent["count"] >= REQUESTS_PER_RUN:
        raise RateLimited(f"נשלחו {REQUESTS_PER_RUN} בקשות. ממשיכים בעוד שעה, כדי לא להגיע לחסימה")
    if users_active():
        raise RateLimited("יש משתמשים באתר. העדכון ברקע ממתין, כדי שהמכסה של ספוטיפיי תישאר להם")
    for attempt in range(1, RETRIES + 1):
        _sent["count"] += 1
        _RetryAfterSpy.seconds = None
        try:
            result = call()
            time.sleep(PAUSE_SECONDS)
            return result
        except SpotifyException as error:
            if error.http_status != 429:
                raise
            # ספוטיפיי כותב כמה לחכות בכותרת Retry-After. כש-spotipy מוותר בעצמו, המספר נמצא רק ביומן
            header = (getattr(error, "headers", None) or {}).get("Retry-After", "")
            wait = int(header) if str(header).isdigit() else _RetryAfterSpy.seconds or 30 * attempt
            if wait > MAX_WAIT_SECONDS:
                # זוכרים עד מתי חסום, כדי לא לשלוח אף בקשה לפני כן (בקשות בזמן חסימה רק מאריכות אותה)
                remember_block(wait)
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


class _GentleClient:
    """לקוח ספוטיפיי לחיפושי האינדקס, שכל בקשה שלו עוברת דרך with_retry: הפסקה, ספירה ועצירה בחסימה."""

    def __init__(self, sp):
        self._sp = sp

    def search(self, **kwargs):
        return with_retry(lambda: self._sp.search(**kwargs))


def needs_refresh():
    return catalog.needs_refresh() or bool(index_store.stale_terms(build_index.all_terms()))


def refresh_index(sp, log):
    """מעדכן מונחים באינדקס השירים שהתיישנו. עד שמונח מתעדכן, הבנייה ממשיכה להשתמש בשירים הישנים שלו."""
    stale = index_store.stale_terms(build_index.all_terms())
    if not stale:
        return
    log(f"אינדקס השירים: {len(stale)} מונחים לעדכון")
    gentle = _GentleClient(sp)
    for number, term in enumerate(stale, 1):
        tracks = engine.search_term(gentle, term, "ביחד", build_index.tracks_for(term))
        # מאפייני הקצב (ReccoBeats, לא ספוטיפיי), כדי שהסינון לפי אווירה יהיה מהיר
        get_features([t["id"] for t in tracks if t.get("id")])
        index_store.save_term(term, tracks)
        log(f"[{number}/{len(stale)}] {term}: {len(tracks)} שירים")


def run(sp, log=print):
    """
    מעדכן את אינדקס השירים ואת הקטלוג, או ממשיך מאיפה שעצר.
    מחזיר True כשהכול מעודכן, False אם נעצר באמצע.
    """
    left = blocked_until() - time.time()
    if left > 0:
        log(f"ספוטיפיי חוסם עוד {int(left // 60)} דקות. לא שולחים בקשות עד אז")
        return False
    _sent["count"] = 0
    try:
        # קודם האינדקס: ממנו נבנים הפלייליסטים, וזה הכי חשוב למשתמשים
        refresh_index(sp, log)
    except RateLimited as error:
        log(str(error))
        return False
    if not catalog.needs_refresh():
        return True
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
    """האם הקטלוג מתעדכן עכשיו (לתצוגה בדף "פלייליסטים קיימים")."""
    return _state["running"] and catalog.needs_refresh()


def refresh_in_background():
    """
    מתחיל את העדכון ברקע, אם הוא עוד לא רץ. בטוח לקרוא שוב ושוב.
    העדכון לא נגמר: אחרי עצירה הוא ממתין (שעה, או עד סוף החסימה) וממשיך, ואחרי שהכול מעודכן
    הוא בודק שוב כל כמה שעות. כך אינדקס השירים והקטלוג לא מתיישנים, בלי שמישהו ייכנס לדף.
    PLAYLISTOR_NO_REFRESH (בבדיקות) מכבה את העדכון, כדי שלא יישלחו בקשות לספוטיפיי.
    """
    if os.getenv("PLAYLISTOR_NO_REFRESH"):
        return
    with _lock:
        if _state["running"]:
            return
        _state["running"] = True

    def log(text):
        print(f"[קטלוג] {text}", flush=True)

    def work():
        try:
            while True:
                time.sleep(max(0.0, blocked_until() - time.time()))
                finished = False
                if needs_refresh():
                    try:
                        finished = run(make_client(), log=log)
                    except Exception as error:  # עדכון ברקע לא אמור להפיל את האפליקציה
                        log(f"העדכון נכשל: {error}")
                    if not finished:
                        # כשהעצירה היא בגלל משתמשים באתר, בודקים שוב כשהם כנראה סיימו, ולא בעוד שעה
                        pause = USER_QUIET_SECONDS if users_active() else RETRY_AFTER_SECONDS
                        wait = max(pause, blocked_until() - time.time())
                        log(f"ממשיכים בעוד {int(wait // 60)} דקות")
                        time.sleep(wait)
                        continue
                time.sleep(CHECK_AGAIN_SECONDS)
        finally:
            _state["running"] = False

    threading.Thread(target=work, daemon=True, name="spotify-refresh").start()


if __name__ == "__main__":
    run(make_client())
