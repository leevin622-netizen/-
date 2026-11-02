import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import requests

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
# אם Last.fm לא עונה תוך כמה שניות, מוותרים על התגיות של האמן הזה
TIMEOUT_SECONDS = 4
# תגיות של אמנים שכבר נמצאו, כדי לא לבקש אותן שוב. נשמרות גם בקובץ, כי הן כמעט לא משתנות,
# וכך אחרי הפעלה מחדש של השרת טעינת הסגנון של המשתמש לא מחכה שוב ל-Last.fm
TAGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "lastfm_tags.json")
# Last.fm מחזיר את הקוד הזה כשאין אמן כזה. גם זו תשובה ששווה לזכור
NOT_FOUND = 6
_tags_cache = None
_tags_lock = threading.Lock()


def _tags():
    global _tags_cache
    with _tags_lock:
        if _tags_cache is None:
            try:
                with open(TAGS_FILE, encoding="utf-8") as f:
                    _tags_cache = json.load(f)
            except (OSError, ValueError):
                _tags_cache = {}
        return _tags_cache


def _save_tags():
    with _tags_lock:
        # עותק, כי בקשה אחרת יכולה להוסיף תגיות בזמן הכתיבה
        snapshot = dict(_tags_cache)
        try:
            os.makedirs(os.path.dirname(TAGS_FILE), exist_ok=True)
            with open(TAGS_FILE, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False)
        except OSError:
            pass


def get_artist_tags(artist_name, limit=5):
    """מחזיר רשימת תגיות (ז'אנרים) לאמן מ-Last.fm, או רשימה ריקה אם לא נמצא."""
    cache = _tags()
    if artist_name in cache:
        return cache[artist_name]
    api_key = os.getenv("LASTFM_API_KEY")
    if not api_key:
        return []

    params = {
        "method": "artist.gettoptags",
        "artist": artist_name,
        "api_key": api_key,
        "format": "json",
        "autocorrect": 1,
    }
    try:
        response = requests.get(LASTFM_URL, params=params, timeout=TIMEOUT_SECONDS)
        data = response.json()
    except (requests.RequestException, ValueError):
        return []

    if "error" in data:
        # אמן שלא קיים ב-Last.fm נזכר כריק. שגיאה אחרת (למשל הגבלה) לא נזכרת, וננסה שוב
        if data.get("error") == NOT_FOUND:
            cache[artist_name] = []
        return []

    tags = data.get("toptags", {}).get("tag", [])
    cache[artist_name] = [tag["name"] for tag in tags[:limit]]
    return cache[artist_name]


def get_tags_for_artists(artist_names):
    """מביא תגיות לכמה אמנים במקביל, במקום אחד אחרי השני. תגיות חדשות נשמרות לקובץ."""
    before = len(_tags())
    with ThreadPoolExecutor(max_workers=20) as pool:
        found = list(pool.map(get_artist_tags, artist_names))
    if len(_tags()) != before:
        _save_tags()
    return found


# אמנים דומים שכבר נמצאו, לפי שם האמן
_similar_cache = {}


def get_similar_artists(artist_name, limit=10):
    """
    אמנים דומים לאמן, לפי Last.fm: [{"name": ..., "match": 0..1}]. ריק אם לא נמצאו,
    או אם אין מפתח Last.fm.
    """
    if artist_name in _similar_cache:
        return _similar_cache[artist_name]
    api_key = os.getenv("LASTFM_API_KEY")
    if not api_key:
        return []
    params = {
        "method": "artist.getsimilar",
        "artist": artist_name,
        "api_key": api_key,
        "format": "json",
        "autocorrect": 1,
        "limit": limit,
    }
    try:
        data = requests.get(LASTFM_URL, params=params, timeout=TIMEOUT_SECONDS).json()
    except (requests.RequestException, ValueError):
        return []
    if "error" in data:
        return []
    items = data.get("similarartists", {}).get("artist", [])
    _similar_cache[artist_name] = [
        {"name": item["name"], "match": float(item.get("match") or 0)} for item in items if item.get("name")
    ]
    return _similar_cache[artist_name]


def _user_top(method, key, user, api_key, max_pages=5):
    """מביא את רשימת ה-top של משתמש ב-Last.fm, עמוד אחרי עמוד (עד 1000 פריטים בעמוד)."""
    items = []
    for page in range(1, max_pages + 1):
        params = {
            "method": method, "user": user, "api_key": api_key,
            "format": "json", "period": "overall", "limit": 1000, "page": page,
        }
        try:
            data = requests.get(LASTFM_URL, params=params, timeout=10).json()
        except (requests.RequestException, ValueError):
            break
        block = data.get(key + "s", {})
        items += block.get(key, [])
        if page >= int(block.get("@attr", {}).get("totalPages", 1)):
            break
    return items


def get_user_playcounts():
    """
    מספר ההשמעות של כל שיר ואמן, לפי Last.fm.
    ספוטיפיי לא חושף מספר השמעות, ולכן זה עובד רק אם LASTFM_USER מוגדר ב-.env
    וה-Spotify מחובר ל-Last.fm (scrobbling). מחזיר (tracks, artists) או (None, None).
    """
    user = os.getenv("LASTFM_USER")
    api_key = os.getenv("LASTFM_API_KEY")
    if not user or not api_key:
        return None, None
    tracks = {
        (t["artist"]["name"].lower(), t["name"].lower()): int(t["playcount"])
        for t in _user_top("user.gettoptracks", "track", user, api_key)
    }
    artists = {
        a["name"].lower(): int(a["playcount"])
        for a in _user_top("user.gettopartists", "artist", user, api_key)
    }
    return tracks, artists
