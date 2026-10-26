import os
import pickle
import time

import requests
from spotipy.exceptions import SpotifyException

from engine import is_hebrew

# ספוטיפיי מחזיר עד 50 פריטים בכל בקשה
PAGE = 50
TIME_RANGES = {"short_term": "4 שבועות", "medium_term": "6 חודשים", "long_term": "כל הזמנים"}
# כמה זמן לשמור את הספרייה, כדי שמעבר בין עמודים לא יטען הכל מחדש מספוטיפיי.
# הנתונים נשמרים גם בקובץ, כך שהם נשארים אחרי הפעלה מחדש של האפליקציה.
# כפתור "רענון נתונים" בדף הבית טוען הכל מחדש.
CACHE_SECONDS = 6 * 60 * 60
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
_cache = {}


def _cache_file(user_id):
    safe = "".join(c for c in user_id if c.isalnum() or c in "-_")
    return os.path.join(CACHE_DIR, f"{safe}.pickle")


def _load_from_disk(user_id):
    try:
        with open(_cache_file(user_id), "rb") as f:
            for key, entry in pickle.load(f).items():
                _cache.setdefault((user_id, key), entry)
    except (OSError, pickle.PickleError, EOFError):
        pass


def _save_to_disk(user_id):
    os.makedirs(CACHE_DIR, exist_ok=True)
    data = {key: entry for (uid, key), entry in _cache.items() if uid == user_id}
    with open(_cache_file(user_id), "wb") as f:
        pickle.dump(data, f)


# מופעל כשנתונים ישנים מוצגים במקום טעינה שנכשלה. מקבל את השגיאה ואת מועד השמירה של הנתונים.
# האפליקציה מגדירה את זה, כדי שתוכל להציג למשתמש הודעה. בלי הגדרה, כלום לא קורה.
on_stale = None


def cached(user_id, key, loader):
    if (user_id, key) not in _cache:
        _load_from_disk(user_id)
    entry = _cache.get((user_id, key))
    if entry and time.time() - entry[0] < CACHE_SECONDS:
        return entry[1]
    started = time.time()
    try:
        value = loader()
    except (SpotifyException, requests.RequestException) as error:
        # ספוטיפיי מגביל או לא עונה: מציגים את מה שנשמר בפעם האחרונה, אם יש כזה.
        # אבל התחברות שפגה (401/403) צריכה להמשיך להיזרק, כדי שהמשתמש יתחבר מחדש
        if entry is None or (isinstance(error, SpotifyException) and error.http_status in (401, 403)):
            raise
        if on_stale:
            on_stale(error, entry[0])
        return entry[1]
    # מודפס בחלון של האפליקציה, כדי שיהיה קל לראות מה לוקח זמן
    print(f"[פלייליסטור] נטען {key} תוך {time.time() - started:.1f} שניות")
    _cache[(user_id, key)] = (time.time(), value)
    _save_to_disk(user_id)
    return value


def clear_cache(user_id):
    for key in [k for k in _cache if k[0] == user_id]:
        del _cache[key]
    try:
        os.remove(_cache_file(user_id))
    except OSError:
        pass


def forget(user_id, *keys):
    """מוחק מהמטמון רק את מה שהשתנה, למשל אחרי שעקבת אחרי אמן. שאר הנתונים נשארים."""
    _load_from_disk(user_id)
    for key in keys:
        _cache.pop((user_id, key), None)
    _save_to_disk(user_id)


def all_saved_tracks(sp):
    """כל השירים שאהבת, לא רק 20 האחרונים."""
    items, offset = [], 0
    while True:
        page = sp.current_user_saved_tracks(limit=PAGE, offset=offset)
        items += [i for i in page["items"] if i.get("track")]
        if not page.get("next"):
            return items
        offset += PAGE


def followed_artists(sp):
    artists, after = [], None
    while True:
        block = sp.current_user_followed_artists(limit=PAGE, after=after)["artists"]
        artists += block["items"]
        after = (block.get("cursors") or {}).get("after")
        if not block.get("next") or not after:
            return artists


def top_ranks(sp, kind):
    """
    {id: {time_range: מקום}} לשירים או לאמנים שאתה הכי שומע.
    זה הנתון הכי קרוב להשמעות שספוטיפיי נותן: 50 המובילים בכל תקופה.
    """
    fetch = sp.current_user_top_tracks if kind == "tracks" else sp.current_user_top_artists
    ranks, objects = {}, {}
    for time_range in TIME_RANGES:
        for place, item in enumerate(fetch(limit=PAGE, time_range=time_range)["items"], 1):
            ranks.setdefault(item["id"], {})[time_range] = place
            objects[item["id"]] = item
    return ranks, objects


def best_rank(ranks):
    """המקום הכי גבוה בכל התקופות, למשל (3, '4 שבועות'), או None."""
    if not ranks:
        return None
    time_range, place = min(ranks.items(), key=lambda kv: kv[1])
    return place, TIME_RANGES[time_range]


def collect_artists(saved, followed, top_artist_ranks, top_artist_objects):
    """
    כל האמנים שאתה אוהב: מי שאתה עוקב אחריו, מי שאתה הכי שומע,
    וכל מי שיש לו לפחות שיר אחד ברשימת השירים שאהבת.
    """
    artists = {}

    def entry(artist_id, name):
        return artists.setdefault(artist_id, {
            "id": artist_id, "name": name, "liked": 0, "followed": False,
            "rank": None, "genres": [], "image": "", "hebrew_song": False,
        })

    for item in saved:
        track = item["track"]
        for a in track["artists"]:
            if not a.get("id"):
                continue
            e = entry(a["id"], a["name"])
            e["liked"] += 1
            e["hebrew_song"] = e["hebrew_song"] or is_hebrew(track["name"])
    for a in followed:
        entry(a["id"], a["name"])["followed"] = True
    for artist_id, ranks in top_artist_ranks.items():
        entry(artist_id, top_artist_objects[artist_id]["name"])["rank"] = best_rank(ranks)
    for a in list(followed) + list(top_artist_objects.values()):
        e = artists[a["id"]]
        e["genres"] = a.get("genres") or e["genres"]
        images = a.get("images") or []
        e["image"] = images[-1]["url"] if images else e["image"]
    return list(artists.values())
