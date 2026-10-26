from html import escape

# ערכת עיצוב לכל סגנון: צבע מרכזי, צבע הטקסט עליו, ושלושה צבעים לרקע המשתנה
THEMES = {
    "pop": {"label": "פופ", "emoji": "💖", "accent": "#ff4fa3", "on_accent": "#fff",
            "colors": ("#ff4fa3", "#8b5cf6", "#ffb347")},
    "mizrahi": {"label": "מזרחית", "emoji": "🌙", "accent": "#f5b301", "on_accent": "#000",
                "colors": ("#f5b301", "#d9480f", "#0ca5a5")},
    "rock": {"label": "רוק", "emoji": "🎸", "accent": "#ff3b30", "on_accent": "#fff",
             "colors": ("#7f0000", "#ff3b30", "#262626")},
    "hiphop": {"label": "היפ הופ", "emoji": "🎤", "accent": "#ffb000", "on_accent": "#000",
               "colors": ("#ff6a00", "#ffd200", "#3a3a3a")},
    "electronic": {"label": "אלקטרוני", "emoji": "⚡", "accent": "#00e5ff", "on_accent": "#000",
                   "colors": ("#00e5ff", "#7c3aed", "#ff00c8")},
    "chill": {"label": "רגוע", "emoji": "🌊", "accent": "#5eead4", "on_accent": "#000",
              "colors": ("#0f766e", "#1e3a8a", "#5eead4")},
    "default": {"label": "קלאסי", "emoji": "🎧", "accent": "#1db954", "on_accent": "#000",
                "colors": ("#1db954", "#0b3d2e", "#1e3a8a")},
}

# מילות מפתח בז'אנרים ובתגיות. הסדר חשוב: "israeli mizrahi" צריך להיספר כמזרחית ולא כפופ
KEYWORDS = [
    ("mizrahi", ("mizrahi", "mizrahit", "mediterranean", "middle eastern", "arabic", "greek", "מזרחי")),
    ("hiphop", ("hip hop", "hip-hop", "rap", "trap", "drill", "היפ הופ")),
    ("electronic", ("electronic", "edm", "house", "techno", "trance", "dubstep", "dance", "workout", "psytrance")),
    ("rock", ("rock", "metal", "punk", "grunge", "alternative", "indie", "רוק")),
    ("chill", ("chill", "lo-fi", "lofi", "jazz", "acoustic", "ambient", "soul", "blues", "instrumental",
               "classical", "ballad", "sad", "reggae")),
    ("pop", ("pop", "summer", "wedding", "funk", "disco", "פופ")),
]

# מצב רוח ואירוע מטופס יצירת הפלייליסט
CHOICE_THEMES = {
    "שמח": "pop", "עצוב": "chill", "ממריץ": "rock", "רגוע": "chill",
    "ריצה": "electronic", "חדר כושר": "hiphop", "רכיבה על אופניים": "electronic",
    "יוגה ומדיטציה": "chill", "הליכה": "pop",
    "בוקר טוב": "pop", "נסיעה באוטו": "rock", "בדרך לעבודה": "pop", "עבודה וריכוז": "chill",
    "לימודים": "chill", "בישול": "chill", "ניקיון הבית": "pop", "מקלחת": "pop", "לפני השינה": "chill",
    "מסיבה": "electronic", "יום הולדת": "pop", "חתונה": "pop", "על האש": "mizrahi",
    "ארוחת ערב עם חברים": "chill", "ערב רומנטי": "chill", "קריוקי": "pop", "ערב משחקים": "pop",
    "שבת בבית": "mizrahi", "חגים": "mizrahi", "ערב שירה בציבור": "chill",
    "ים": "pop", "טיול בטבע": "chill", "קמפינג ומדורה": "chill", "חופשה בחו\"ל": "pop", "בריכה": "pop",
    "פרידה": "chill", "געגועים": "chill", "נוסטלגיה": "rock", "מוטיבציה": "hiphop",
}


def theme_for_tag(tag):
    tag = tag.lower()
    for theme, words in KEYWORDS:
        if any(word in tag for word in words):
            return theme
    return None


def themes_for_tags(tags):
    """כל הסגנונות שהתגיות של אמן מתאימות להם."""
    return {theme_for_tag(t) for t in tags} - {None}


def detect_theme(weighted_tags):
    """
    weighted_tags: רשימת (משקל, [תגיות]) לכל אמן. מחזיר את הסגנון עם הניקוד הכי גבוה.
    כל אמן נספר פעם אחת לכל סגנון, גם אם יש לו כמה תגיות מאותו סגנון.
    """
    scores = {}
    for weight, tags in weighted_tags:
        for theme in {theme_for_tag(t) for t in tags} - {None}:
            scores[theme] = scores.get(theme, 0) + weight
    return max(scores, key=scores.get) if scores else "default"


def theme_for_choice(genre, mood, event):
    """הסגנון של מה שבחרת ביצירת פלייליסט: קודם הז'אנר, אחר כך מצב הרוח והאירוע."""
    return (genre and theme_for_tag(genre)) or CHOICE_THEMES.get(mood) or CHOICE_THEMES.get(event)


def theme_css(name):
    t = THEMES.get(name, THEMES["default"])
    c1, c2, c3 = t["colors"]
    return (
        f":root {{ --accent: {t['accent']}; --accent-dark: {t['accent']}cc; --on-accent: {t['on_accent']};"
        f" --c1: {c1}; --c2: {c2}; --c3: {c3}; }}"
    )


def background_html(images):
    """רקע עם שלוש שורות של תמונות שזזות לסירוגין. בלי תמונות נשאר רק הרקע הצבעוני."""
    if not images:
        return '<div class="bg" aria-hidden="true"></div><div class="bg-shade light"></div>'
    rows = []
    for i in range(3):
        # כל שורה מתחילה מתמונה אחרת, וכל שורה מוכפלת כדי שהתנועה תהיה רציפה
        shifted = images[i * 3 % len(images):] + images[:i * 3 % len(images)]
        while len(shifted) < 8:
            shifted += shifted
        imgs = "".join(f'<img src="{escape(url)}" alt="" loading="lazy">' for url in shifted)
        rows.append(f'<div class="bg-row r{i + 1}"><div class="bg-track">{imgs}{imgs}</div></div>')
    return f'<div class="bg" aria-hidden="true">{"".join(rows)}</div><div class="bg-shade"></div>'


BACKGROUND_CSS = """
.bg {
  position: fixed; inset: 0; z-index: -2; overflow: hidden; direction: ltr;
  display: flex; flex-direction: column; justify-content: space-around;
  background: linear-gradient(120deg, var(--c1), var(--c2), var(--c3), var(--c1));
  background-size: 300% 300%; animation: colors 18s ease infinite;
}
.bg-row { overflow: hidden; }
.bg-track { display: flex; gap: 16px; width: max-content; animation: slide 70s linear infinite; }
.bg-row.r2 .bg-track { animation-direction: reverse; animation-duration: 90s; }
.bg-row.r3 .bg-track { animation-duration: 110s; }
.bg-track img {
  height: 28vh; aspect-ratio: 1; object-fit: cover; border-radius: 18px;
  opacity: .55; box-shadow: 0 8px 30px rgba(0,0,0,.4);
}
.bg-shade {
  position: fixed; inset: 0; z-index: -1;
  background: radial-gradient(ellipse at center, rgba(0,0,0,.35), rgba(0,0,0,.8));
}
.bg-shade.light { background: radial-gradient(ellipse at center, rgba(0,0,0,.1), rgba(0,0,0,.55)); }
@keyframes colors { 0%, 100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@keyframes slide { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@media (prefers-reduced-motion: reduce) { .bg, .bg-track { animation: none; } }
"""
