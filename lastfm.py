import os
from concurrent.futures import ThreadPoolExecutor
import requests

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
# אם Last.fm לא עונה תוך כמה שניות, מוותרים על התגיות של האמן הזה
TIMEOUT_SECONDS = 4
# תגיות של אמנים שכבר נמצאו, כדי לא לבקש אותן שוב בכל טעינה של העמוד
_tags_cache = {}


def get_artist_tags(artist_name, limit=5):
    """מחזיר רשימת תגיות (ז'אנרים) לאמן מ-Last.fm, או רשימה ריקה אם לא נמצא."""
    if artist_name in _tags_cache:
        return _tags_cache[artist_name]
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
        return []

    tags = data.get("toptags", {}).get("tag", [])
    _tags_cache[artist_name] = [tag["name"] for tag in tags[:limit]]
    return _tags_cache[artist_name]


def get_tags_for_artists(artist_names):
    """מביא תגיות לכמה אמנים במקביל, במקום אחד אחרי השני."""
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(get_artist_tags, artist_names))

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
