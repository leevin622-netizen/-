from concurrent.futures import ThreadPoolExecutor
from engine import is_hebrew

# תגיות או ז'אנרים שמסמנים שהאמן ישראלי
ISRAELI_HINTS = ("israeli", "israel", "hebrew", "mizrahi", "ישראל")
# שמות עבריים שכבר נמצאו ({id: שם או None}), כדי לא לשאול את ספוטיפיי שוב על אותו אמן
_hebrew_cache = {}


def is_israeli_artist(name, tags):
    return is_hebrew(name) or any(h in t.lower() for t in tags for h in ISRAELI_HINTS)


def fetch_hebrew_names(sp_he, artist_ids):
    """מחזיר {id: שם בעברית} לאמנים שיש להם שם עברי בספוטיפיי."""
    ids = list(dict.fromkeys(artist_ids))
    missing = [i for i in ids if i not in _hebrew_cache]
    if missing:
        with ThreadPoolExecutor(max_workers=10) as pool:
            for artist_id, artist in zip(missing, pool.map(sp_he.artist, missing)):
                name = artist["name"] if artist else ""
                _hebrew_cache[artist_id] = name if is_hebrew(name) else None
    return {i: _hebrew_cache[i] for i in ids if _hebrew_cache.get(i)}


def localize_tracks(sp_he, tracks):
    """בשירים בעברית, מחליף את שמות האמנים לשם העברי שלהם."""
    ids = [
        artist_id
        for t in tracks if is_hebrew(t["name"])
        for artist_id, name in t["artists"] if not is_hebrew(name)
    ]
    hebrew = fetch_hebrew_names(sp_he, ids)
    for t in tracks:
        t["artists"] = [(artist_id, hebrew.get(artist_id, name)) for artist_id, name in t["artists"]]
        t["artist"] = ", ".join(name for _, name in t["artists"])
    return tracks
