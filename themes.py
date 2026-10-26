from html import escape
import random

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


# תנועה לכל סגנון. tempo: שניות לתנודה אחת (קצב), rise: שניות שבועה עולה מלמטה למעלה,
# sway: כמה היא זזה הצידה, pulse: האם היא גם מתנפחת בקצב, colors: שניות למעבר צבעים ברקע
MOTION = {
    "pop": {"count": 16, "tempo": 1.6, "rise": 16, "sway": 26, "pulse": False, "colors": 18},
    "mizrahi": {"count": 14, "tempo": 1.9, "rise": 20, "sway": 56, "pulse": False, "colors": 26},
    "rock": {"count": 12, "tempo": 0.9, "rise": 10, "sway": 14, "pulse": True, "colors": 10},
    "hiphop": {"count": 14, "tempo": 1.1, "rise": 13, "sway": 30, "pulse": True, "colors": 12},
    "electronic": {"count": 26, "tempo": 0.6, "rise": 8, "sway": 8, "pulse": True, "colors": 8},
    "chill": {"count": 10, "tempo": 3.6, "rise": 26, "sway": 44, "pulse": False, "colors": 30},
    "default": {"count": 12, "tempo": 2.4, "rise": 16, "sway": 24, "pulse": False, "colors": 18},
}


def bubbles_html(theme):
    """בועות בצבעי הסגנון. כל אחת מתחילה במקום אחר ונעה בקצב של הסגנון, כמו מוזיקה שעולה ויורדת."""
    motion = MOTION.get(theme, MOTION["default"])
    colors = THEMES.get(theme, THEMES["default"])["colors"]
    rnd = random.Random()
    items = []
    for _ in range(motion["count"]):
        rise = motion["rise"] * rnd.uniform(0.7, 1.3)
        style = (
            f"--x:{rnd.randint(-2, 98)}%;--s:{rnd.randint(40, 140)}px;"
            f"--rise:{rise:.1f}s;--d:-{rnd.uniform(0, rise):.1f}s;"
            f"--sway:{motion['sway'] * rnd.uniform(0.5, 1.2):.0f}px;--sway-t:{rnd.uniform(2.5, 6):.1f}s;"
            f"--bob:{rnd.randint(10, 28)}px;--tempo:{motion['tempo']}s;"
            f"--c:{rnd.choice(colors)};--o:{rnd.uniform(0.25, 0.6):.2f};--b:{rnd.choice([0, 0, 2])}px"
        )
        cls = "bubble pulse" if motion["pulse"] else "bubble"
        items.append(f'<div class="{cls}" style="{style}"><i></i></div>')
    return f'<div class="bg-bubbles">{"".join(items)}</div>'


def background_html(images, theme="default"):
    """
    רקע דינמי: בועות שעולות ויורדות בקצב הסגנון, ומעליהן שלוש שורות של תמונות שזזות לסירוגין.
    בלי תמונות נשארות רק הבועות והצבעים.
    """
    bubbles = bubbles_html(theme)
    style = f"--color-t:{MOTION.get(theme, MOTION['default'])['colors']}s"
    if not images:
        return f'<div class="bg" aria-hidden="true" style="{style}">{bubbles}</div><div class="bg-shade light"></div>'
    rows = []
    for i in range(3):
        # כל שורה מתחילה מתמונה אחרת, וכל שורה מוכפלת כדי שהתנועה תהיה רציפה
        shifted = images[i * 3 % len(images):] + images[:i * 3 % len(images)]
        while len(shifted) < 8:
            shifted += shifted
        imgs = "".join(f'<img src="{escape(url)}" alt="" loading="lazy">' for url in shifted)
        rows.append(f'<div class="bg-row r{i + 1}"><div class="bg-track">{imgs}{imgs}</div></div>')
    return f'<div class="bg" aria-hidden="true" style="{style}">{bubbles}{"".join(rows)}</div><div class="bg-shade"></div>'


BACKGROUND_CSS = """
.bg {
  position: fixed; inset: 0; z-index: -2; overflow: hidden; direction: ltr;
  display: flex; flex-direction: column; justify-content: space-around;
  background: linear-gradient(120deg, var(--c1), var(--c2), var(--c3), var(--c1));
  background-size: 300% 300%; animation: colors var(--color-t, 18s) ease infinite;
}
.bg-bubbles { position: absolute; inset: 0; overflow: hidden; }
.bubble {
  position: absolute; bottom: -180px; left: var(--x); width: var(--s); height: var(--s);
  animation: rise var(--rise) linear infinite; animation-delay: var(--d); will-change: transform;
}
.bubble i {
  display: block; width: 100%; height: 100%; border-radius: 50%; opacity: var(--o);
  background: radial-gradient(circle at 32% 28%, rgba(255, 255, 255, .85), var(--c) 42%, transparent 72%);
  filter: blur(var(--b));
  animation: sway var(--sway-t) ease-in-out infinite alternate, bob var(--tempo) ease-in-out infinite;
}
.bubble.pulse i {
  animation: sway var(--sway-t) ease-in-out infinite alternate, bob var(--tempo) ease-in-out infinite,
    pulse var(--tempo) ease-in-out infinite;
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
@keyframes rise { from { transform: translateY(0); } to { transform: translateY(calc(-100vh - 280px)); } }
@keyframes sway { from { transform: translateX(calc(var(--sway) * -1)); } to { transform: translateX(var(--sway)); } }
@keyframes bob { 0%, 100% { translate: 0 0; } 50% { translate: 0 calc(var(--bob) * -1); } }
@keyframes pulse { 0%, 100% { scale: 1; } 50% { scale: 1.15; } }
@media (prefers-reduced-motion: reduce) {
  .bg, .bg-track, .bubble, .bubble i { animation: none; }
  .bg-bubbles { display: none; }
}
"""
