"""
האווירה של כל שיר: אנרגיה, קצביות, שמחה ועוד.
ספוטיפיי כבר לא חושף את הנתונים האלה לאפליקציות חדשות, ולכן הם מגיעים מ-ReccoBeats,
שירות חינמי שמחזיר אותם לפי ה-id של השיר בספוטיפיי.
כל בחירה (מצב רוח ואירוע) מתורגמת לטווחים, ושיר שלא עומד בהם לא נכנס לפלייליסט.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import requests

FEATURES_URL = "https://api.reccobeats.com/v1/audio-features"
# כמה שירים בכל בקשה ל-ReccoBeats
BATCH = 40
TIMEOUT_SECONDS = 10
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "features.json")
NAMES = ("energy", "danceability", "valence", "acousticness", "instrumentalness", "speechiness", "tempo")

# טווחים לכל בחירה: {תכונה: (מינימום, מקסימום)}. None אומר בלי גבול.
# energy: עוצמה וקצב, danceability: כמה השיר רקיד, valence: כמה הוא שמח (0 עצוב, 1 שמח)
MOOD_PROFILES = {
    "שמח": {"valence": (0.55, None), "energy": (0.45, None)},
    "עצוב": {"valence": (None, 0.4), "energy": (None, 0.6)},
    "אנרגטי": {"energy": (0.7, None), "danceability": (0.5, None)},
    "רגוע": {"energy": (None, 0.5), "speechiness": (None, 0.2)},
    "רומנטי": {"energy": (None, 0.65), "speechiness": (None, 0.15)},
    "נוסטלגי": {},
    "מוטיבציה": {"energy": (0.65, None)},
    "שבור לב": {"valence": (None, 0.4)},
    "בא לרקוד": {"energy": (0.65, None), "danceability": (0.65, None)},
    "חולמני": {"energy": (None, 0.55), "speechiness": (None, 0.15)},
}
EVENT_PROFILES = {
    "ריצה": {"energy": (0.7, None), "danceability": (0.55, None)},
    "חדר כושר": {"energy": (0.68, None), "danceability": (0.55, None)},
    "רכיבה על אופניים": {"energy": (0.65, None), "danceability": (0.5, None)},
    "יוגה ומדיטציה": {"energy": (None, 0.35), "speechiness": (None, 0.1)},
    "הליכה": {"energy": (0.4, 0.85)},
    "בוקר טוב": {"energy": (0.3, 0.75), "valence": (0.45, None)},
    "נסיעה באוטו": {"energy": (0.5, None)},
    "בדרך לעבודה": {"energy": (0.45, None)},
    "עבודה וריכוז": {"energy": (None, 0.55), "speechiness": (None, 0.1)},
    "לימודים": {"energy": (None, 0.5), "speechiness": (None, 0.1)},
    "בישול": {"energy": (0.35, 0.8), "valence": (0.4, None)},
    "ניקיון הבית": {"energy": (0.6, None), "danceability": (0.6, None)},
    "מקלחת": {"energy": (0.5, None), "valence": (0.5, None)},
    "לפני השינה": {"energy": (None, 0.35), "speechiness": (None, 0.1)},
    "מסיבה": {"energy": (0.7, None), "danceability": (0.65, None)},
    "יום הולדת": {"energy": (0.6, None), "danceability": (0.6, None), "valence": (0.55, None)},
    "חתונה": {"energy": (0.6, None), "danceability": (0.6, None), "valence": (0.5, None)},
    "על האש": {"energy": (0.55, None), "danceability": (0.6, None), "valence": (0.5, None)},
    "ארוחת ערב עם חברים": {"energy": (0.3, 0.7)},
    "ערב רומנטי": {"energy": (None, 0.6), "speechiness": (None, 0.15)},
    "קריוקי": {"energy": (0.45, None), "valence": (0.4, None)},
    "ערב משחקים": {"energy": (0.45, 0.85)},
    "שבת בבית": {"energy": (None, 0.65)},
    "חגים": {"valence": (0.45, None)},
    "ערב שירה בציבור": {"energy": (None, 0.7), "speechiness": (None, 0.15)},
    "ים": {"energy": (0.5, None), "valence": (0.55, None)},
    "טיול בטבע": {"energy": (0.35, 0.75)},
    "קמפינג ומדורה": {"energy": (None, 0.65), "acousticness": (0.25, None)},
    "חופשה בחו\"ל": {"danceability": (0.6, None), "valence": (0.55, None)},
    "בריכה": {"energy": (0.6, None), "danceability": (0.65, None)},
    "פרידה": {"valence": (None, 0.4)},
    "געגועים": {"valence": (None, 0.5), "energy": (None, 0.6)},
    "נוסטלגיה": {},
    "מוטיבציה": {"energy": (0.65, None)},
}

_cache = None
_lock = threading.Lock()


def profile_for(mood, event, ranges=None):
    """
    מחבר את הטווחים של מצב הרוח והאירוע. אם הם סותרים (למשל עצוב בחדר כושר),
    האירוע קובע את האנרגיה ומצב הרוח קובע את השמחה.
    """
    profile = dict(MOOD_PROFILES.get(mood, {}))
    for name, (low, high) in EVENT_PROFILES.get(event, {}).items():
        if name not in profile:
            profile[name] = (low, high)
            continue
        old_low, old_high = profile[name]
        new_low = max(x for x in (low, old_low, -1) if x is not None)
        new_high = min(x for x in (high, old_high, 999) if x is not None)
        if new_low > new_high:
            # סתירה: האירוע מנצח, חוץ מ-valence שנשאר של מצב הרוח
            if name != "valence":
                profile[name] = (low, high)
        else:
            profile[name] = (None if new_low == -1 else new_low, None if new_high == 999 else new_high)
    # טווחים שהמשתמש קבע ידנית גוברים על ברירת המחדל
    profile.update(ranges or {})
    return profile


def distance(features, profile):
    """כמה השיר רחוק מהטווחים. 0 אומר שהוא בפנים."""
    total = 0.0
    for name, (low, high) in profile.items():
        value = features.get(name)
        if value is None:
            continue
        if low is not None and value < low:
            total += low - value
        if high is not None and value > high:
            total += value - high
    return total


def strength(features, profile):
    """בתוך הטווח: עד כמה השיר מובהק. בחדר כושר, שיר עם יותר אנרגיה מקבל יותר."""
    total = 0.0
    for name, (low, high) in profile.items():
        value = features.get(name)
        if value is None:
            continue
        if low is not None and high is None:
            total += value - low
        elif high is not None and low is None:
            total += high - value
    return total


def _load():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save():
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f)


def _fetch(ids):
    try:
        response = requests.get(FEATURES_URL, params={"ids": ",".join(ids)}, timeout=TIMEOUT_SECONDS)
        content = response.json().get("content", [])
    except (requests.RequestException, ValueError, AttributeError):
        return None
    found = {}
    for item in content:
        spotify_id = (item.get("href") or "").rsplit("/", 1)[-1]
        if spotify_id:
            found[spotify_id] = {name: item.get(name) for name in NAMES}
    return found


def get_features(track_ids):
    """
    {id: {energy, danceability, ...}} לשירים שנמצאו. שיר ש-ReccoBeats לא מכיר נשמר כ-None,
    כדי לא לשאול עליו שוב. הכל נשמר בקובץ, כי הנתונים של שיר לא משתנים.
    """
    cache = _load()
    missing = [i for i in dict.fromkeys(track_ids) if i and i not in cache]
    if missing:
        batches = [missing[i:i + BATCH] for i in range(0, len(missing), BATCH)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_fetch, batches))
        with _lock:
            for batch, found in zip(batches, results):
                if found is None:
                    # השירות לא ענה: לא שומרים, וננסה שוב בפעם הבאה
                    continue
                for track_id in batch:
                    cache[track_id] = found.get(track_id)
            _save()
    return {i: cache[i] for i in track_ids if cache.get(i)}


def describe(features):
    """תיאור קצר לתצוגה: קצב ואנרגיה."""
    if not features:
        return ""
    parts = []
    if features.get("tempo"):
        parts.append(f"{round(features['tempo'])} BPM")
    if features.get("energy") is not None:
        parts.append(f"אנרגיה {round(features['energy'] * 100)}%")
    if features.get("valence") is not None:
        parts.append(f"שמחה {round(features['valence'] * 100)}%")
    return " · ".join(parts)
