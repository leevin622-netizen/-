"""
הטעם המוזיקלי של המשתמש: הז'אנרים מטופס היצירה שהוא הכי שומע, לפי האמנים המובילים שלו.
משמש להתאמה אישית: ז'אנר מסומן מראש, כרטיסי "בשבילך" בדף הבית, והקטגוריה שנפתחת בפלייליסטים קיימים.
"""
from engine import genres_of

# כמה ז'אנרים מובילים מציגים בכרטיסי "בשבילך"
TOP_GENRES = 3

# הז'אנר בטופס היצירה → הקטגוריה המתאימה בפלייליסטים קיימים (ז'אנר בלי קטגוריה לא מופיע כאן)
CATALOG_CATEGORY = {
    "israeli pop": "israeli", "mizrahi": "israeli", "israeli rock": "israeli", "israeli folk": "israeli",
    "hip hop": "hiphop", "pop": "pop", "rock": "rock", "dance": "dance", "r&b": "rnb",
}


def genre_scores(weighted_tags):
    """weighted_tags: (משקל, [תגיות]) לכל אמן. מחזיר {ז'אנר: ניקוד}, מהגבוה לנמוך."""
    scores = {}
    for weight, tags in weighted_tags:
        for term in genres_of(tags):
            scores[term] = scores.get(term, 0) + weight
    return dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True))


def top_genres(scores, count=TOP_GENRES):
    return list(scores)[:count]


def favourite_category(scores):
    """הקטגוריה בפלייליסטים קיימים שמתאימה לז'אנר הכי נשמע, או "" אם אין התאמה."""
    for term in scores:
        if term in CATALOG_CATEGORY:
            return CATALOG_CATEGORY[term]
    return ""


# הפרופיל המוזיקלי בעמוד הסטטיסטיקות: ממוצע האווירה של השירים שאהבתם (נתוני ReccoBeats, ראו vibes.py)
PROFILE_FEATURES = ("energy", "danceability", "valence", "acousticness")
# מתחת לזה הממוצע לא אומר הרבה, ולכן לא מציגים פרופיל
MIN_PROFILE_TRACKS = 10


def mood_profile(features):
    """
    features: נתוני האווירה של השירים (None לשיר בלי נתונים).
    מחזיר {תכונה: ממוצע 0..1, "tempo": קצב ממוצע, "tracks": כמה שירים נכללו}, או None אם אין מספיק שירים.
    """
    rows = [f for f in features if f]
    if len(rows) < MIN_PROFILE_TRACKS:
        return None

    def mean(name):
        values = [f[name] for f in rows if f.get(name) is not None]
        return sum(values) / len(values) if values else None

    profile = {name: mean(name) for name in PROFILE_FEATURES}
    profile["tempo"] = mean("tempo")
    profile["tracks"] = len(rows)
    return profile


def personality(profile):
    """הטיפוס המוזיקלי לפי האנרגיה והשמחה הממוצעות: (אמוג'י, שם, תיאור). הטקסטים בעברית, ומתורגמים בתצוגה."""
    energy = profile.get("energy") if profile.get("energy") is not None else 0.55
    valence = profile.get("valence") if profile.get("valence") is not None else 0.5
    if energy >= 0.62 and valence >= 0.52:
        return "🎉", "נשמת המסיבה", "הרבה אנרגיה והרבה שמחה. אצלכם תמיד רוקדים."
    if energy >= 0.62 and valence < 0.45:
        return "🔥", "אנרגיה סוערת", "מוזיקה חזקה ועוצמתית, עם צד רגיש מתחת."
    if energy < 0.5 and valence < 0.45:
        return "🌙", "נשמה רגישה", "שירים שקטים ומרגשים, שנכנסים עמוק ללב."
    if energy < 0.5 and valence >= 0.52:
        return "😌", "רוגע שמח", "מוזיקה נינוחה ומחייכת, כמו יום שמש."
    return "🎧", "קצת מהכול", "טעם מאוזן: גם שקט וגם קצבי, גם שמח וגם רגיש."


def mainstream(popularities):
    """
    כמה הטעם מיינסטרים: ממוצע הפופולריות (0..100) של השירים שאהבתם, עם שם ותיאור.
    מחזיר (ממוצע, אמוג'י, שם, תיאור), או None אם אין מספיק שירים עם נתון.
    """
    values = [p for p in popularities if isinstance(p, (int, float))]
    if len(values) < MIN_PROFILE_TRACKS:
        return None
    average = round(sum(values) / len(values))
    if average >= 65:
        return average, "📻", "להיטים של כולם", "אתם אוהבים את מה שכולם שרים."
    if average >= 40:
        return average, "🎯", "בדיוק באמצע", "גם להיטים גדולים וגם שירים שפחות מכירים."
    return average, "💎", "ציידי פנינים", "אתם מוצאים שירים שרוב האנשים עוד לא גילו."
