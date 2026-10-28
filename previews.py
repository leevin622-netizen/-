"""
קטעי תצוגה מקדימה של 30 שניות. ספוטיפיי כבר לא נותן קטעים כאלה לאפליקציות חדשות.
מחפשים קודם ב-Deezer, ואם אין שם, ב-iTunes (בחנות הישראלית ואז האמריקאית), שיש בה הרבה יותר שירים בעברית.
שניהם לא דורשים מפתח ולא משתמשים במכסת ספוטיפיי. מקבלים קטע רק אם השם תואם.
"""
import re
import threading

import requests

DEEZER_SEARCH = "https://api.deezer.com/search"
ITUNES_SEARCH = "https://itunes.apple.com/search"
ITUNES_COUNTRIES = ("IL", "US")
TIMEOUT_SECONDS = 4
# כמה קטעים לזכור, כדי שלחיצה שנייה על אותו שיר לא תפנה שוב לשירותים
MAX_REMEMBERED = 2000
_cache = {}
_lock = threading.Lock()

HEBREW = re.compile(r"[֐-׿]")
LATIN = re.compile(r"[a-z]")


def _normal(text):
    return " ".join((text or "").lower().split())


def _loose(text):
    """
    שם להשוואה: בלי סוגריים ("(Remastered)", "[Live]"), בלי תוספת אחרי מקף ("- 2011 Remaster"),
    בלי "feat." ובלי סימני פיסוק. ככה "שיר (Live)" תואם ל"שיר".
    """
    text = (text or "").lower()
    text = re.sub(r"[\(\[].*?[\)\]]", " ", text)
    text = re.split(r"\s[-–]\s", text)[0]
    text = re.split(r"\s(?:feat\.?|ft\.?|featuring)\s", text)[0]
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def _same_title(found, wanted):
    return bool(wanted) and _loose(found) == wanted


def _same_artist(found, wanted):
    found = _loose(found)
    if not found or not wanted:
        return False
    if found == wanted or wanted in found or found in wanted:
        return True
    # אמן שכתוב בספוטיפיי באנגלית ובחנות בעברית (או להפך). השם של השיר כבר תואם, והחיפוש כלל את האמן
    return bool(HEBREW.search(found)) != bool(HEBREW.search(wanted)) and (
        bool(LATIN.search(found)) or bool(LATIN.search(wanted))
    )


def _from_deezer(artist, title, want_artist, want_title):
    data = requests.get(
        DEEZER_SEARCH,
        # חיפוש רגיל: Deezer כבר לא מחזיר תוצאות לתחביר artist:"..." track:"..."
        params={"q": f"{artist} {title}", "limit": 10},
        timeout=TIMEOUT_SECONDS,
    ).json()
    for item in data.get("data", []):
        if (item.get("preview") and _same_title(item.get("title"), want_title)
                and _same_artist((item.get("artist") or {}).get("name"), want_artist)):
            return item["preview"]
    return ""


def _from_itunes(artist, title, want_artist, want_title, country):
    data = requests.get(
        ITUNES_SEARCH,
        params={"term": f"{artist} {title}", "media": "music", "entity": "song", "limit": 10, "country": country},
        timeout=TIMEOUT_SECONDS,
    ).json()
    for item in data.get("results", []):
        if (item.get("previewUrl") and _same_title(item.get("trackName"), want_title)
                and _same_artist(item.get("artistName"), want_artist)):
            return item["previewUrl"]
    return ""


def preview_url(artist, title):
    """כתובת קטע של 30 שניות לשיר, או מחרוזת ריקה אם לא נמצאה התאמה ברורה."""
    artist, title = (artist or "")[:200], (title or "")[:200]
    key = (_normal(artist), _normal(title))
    if not key[0] or not key[1]:
        return ""
    with _lock:
        if key in _cache:
            return _cache[key]
    want_artist, want_title = _loose(artist), _loose(title)
    # בחיפוש עצמו משתמשים בשם בלי התוספות, כדי לא לפספס בגלל "(Remastered)"
    search_title = want_title or title
    sources = [lambda: _from_deezer(artist, search_title, want_artist, want_title)] + [
        (lambda c=c: _from_itunes(artist, search_title, want_artist, want_title, c)) for c in ITUNES_COUNTRIES
    ]
    url, failed = "", False
    for source in sources:
        try:
            url = source()
        except (requests.RequestException, ValueError):
            failed = True
            continue
        if url:
            break
    if not url and failed:
        # לא מזכירים תשובה שנכשלה, כדי שניסיון אחר כן יצליח
        return ""
    with _lock:
        if len(_cache) >= MAX_REMEMBERED:
            _cache.clear()
        _cache[key] = url
    return url
