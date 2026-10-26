"""
קטעי תצוגה מקדימה של 30 שניות, מ-Deezer. ספוטיפיי כבר לא נותן קטעים כאלה לאפליקציות חדשות,
ו-Deezer לא דורש מפתח ולא משתמש במכסת ספוטיפיי. מחפשים לפי אמן ושם שיר, ומקבלים קטע רק אם השם תואם.
"""
import threading

import requests

DEEZER_SEARCH = "https://api.deezer.com/search"
TIMEOUT_SECONDS = 4
# כמה קטעים לזכור, כדי שלחיצה שנייה על אותו שיר לא תפנה שוב ל-Deezer
MAX_REMEMBERED = 2000
_cache = {}
_lock = threading.Lock()


def _normal(text):
    return " ".join((text or "").lower().split())


def preview_url(artist, title):
    """כתובת קטע של 30 שניות לשיר, או מחרוזת ריקה אם לא נמצא התאמה ברורה."""
    artist, title = (artist or "")[:200], (title or "")[:200]
    key = (_normal(artist), _normal(title))
    if not key[0] or not key[1]:
        return ""
    with _lock:
        if key in _cache:
            return _cache[key]
    url = ""
    try:
        data = requests.get(
            DEEZER_SEARCH,
            params={"q": f'artist:"{artist}" track:"{title}"', "limit": 5},
            timeout=TIMEOUT_SECONDS,
        ).json()
        for item in data.get("data", []):
            # רק התאמה מלאה לשם השיר והאמן, כדי לא להציג שיר אחר בטעות
            same_title = _normal(item.get("title")) == key[1]
            same_artist = _normal((item.get("artist") or {}).get("name")) == key[0]
            if same_title and same_artist and item.get("preview"):
                url = item["preview"]
                break
    except (requests.RequestException, ValueError):
        # לא מזכירים תשובה שנכשלה, כדי שניסיון אחר כן יצליח
        return ""
    with _lock:
        if len(_cache) >= MAX_REMEMBERED:
            _cache.clear()
        _cache[key] = url
    return url
