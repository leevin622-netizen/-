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
