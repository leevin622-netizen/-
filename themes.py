from html import escape
import random

# ערכת עיצוב לכל סגנון: צבע מרכזי, צבע הטקסט עליו, ושלושה צבעים לרקע המשתנה
THEMES = {
    "pop": {"label": "פופ", "emoji": "✨", "accent": "#a5b4fc", "on_accent": "#111",
            "colors": ("#818cf8", "#38bdf8", "#fdba74")},
    "mizrahi": {"label": "מזרחית", "emoji": "🌙", "accent": "#f4c56a", "on_accent": "#111",
                "colors": ("#e0a84a", "#b45f3c", "#2f8f8a")},
    "rock": {"label": "רוק", "emoji": "🎸", "accent": "#f19a8b", "on_accent": "#111",
             "colors": ("#7a2e2a", "#c2564b", "#2a2a2e")},
    "hiphop": {"label": "ראפ", "emoji": "🎤", "accent": "#f6c177", "on_accent": "#111",
               "colors": ("#c97b3a", "#d9a441", "#34343a")},
    "electronic": {"label": "דאנס", "emoji": "⚡", "accent": "#7dd3fc", "on_accent": "#111",
                   "colors": ("#38bdf8", "#6d5bd0", "#2b8a9e")},
    "chill": {"label": "צ'יל", "emoji": "🌊", "accent": "#8ee3cf", "on_accent": "#111",
              "colors": ("#2c7a72", "#2f4a8a", "#6cc9b5")},
    "default": {"label": "מיקס", "emoji": "🎧", "accent": "#6ee7a0", "on_accent": "#111",
                "colors": ("#2f9e64", "#164a3a", "#2c4a8a")},
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
    "רומנטי": "chill", "מסיבתי": "electronic", "קיצי": "pop", "אופטימי": "pop",
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


# תנועה לכל סגנון, כמו נוזל על המסך. tempo: שניות בין טיפה לטיפה (קצב), drops: כמה מקומות שטיפות נולדות בהם,
# blobs: כמה כתמי צבע זזים לאט, morph: שניות לתנועה של הכתמים, colors: שניות למעבר הצבעים ברקע
# bars: עמודי אקולייזר שקופצים בקצב, notes: תווים שעולים, beam: קרן אור מסתובבת כמו דיסקו
MOTION = {
    "pop": {"tempo": 2.6, "drops": 6, "blobs": 3, "morph": 14, "colors": 18, "bars": 0, "notes": 6, "beam": False},
    "mizrahi": {"tempo": 3.2, "drops": 5, "blobs": 3, "morph": 18, "colors": 26, "bars": 0, "notes": 5, "beam": False},
    "rock": {"tempo": 1.2, "drops": 9, "blobs": 3, "morph": 6, "colors": 10, "bars": 28, "notes": 0, "beam": True},
    "hiphop": {"tempo": 1.6, "drops": 7, "blobs": 3, "morph": 9, "colors": 12, "bars": 24, "notes": 0, "beam": False},
    "electronic": {"tempo": 0.8, "drops": 12, "blobs": 4, "morph": 5, "colors": 8, "bars": 40, "notes": 4, "beam": True},
    "chill": {"tempo": 5, "drops": 4, "blobs": 3, "morph": 24, "colors": 30, "bars": 0, "notes": 8, "beam": False},
    "default": {"tempo": 2.6, "drops": 6, "blobs": 3, "morph": 14, "colors": 18, "bars": 14, "notes": 4, "beam": False},
}


def motion_html(theme):
    """
    תנועה נוזלית על המסך: טיפות שנולדות במקומות קבועים ומתפשטות כגלים, וכתמי צבע שזזים לאט.
    הקצב והכמות נקבעים לפי הסגנון.
    """
    motion = MOTION.get(theme, MOTION["default"])
    colors = THEMES.get(theme, THEMES["default"])["colors"]
    rnd = random.Random()
    blobs = []
    for i in range(motion["blobs"]):
        style = (
            f"--x:{rnd.randint(-10, 60)}%;--y:{rnd.randint(-10, 60)}%;--size:{rnd.randint(60, 90)}vmax;"
            f"--c:{colors[i % len(colors)]};--morph:{motion['morph'] * rnd.uniform(0.8, 1.2):.1f}s;"
            f"--drift:{rnd.randint(8, 20)}vmin"
        )
        blobs.append(f'<div class="blob" style="{style}"></div>')
    drops = []
    for _ in range(motion["drops"]):
        period = motion["tempo"] * rnd.uniform(0.8, 1.4)
        style = (
            f"--x:{rnd.randint(4, 96)}%;--y:{rnd.randint(4, 96)}%;--size:{rnd.randint(16, 34)}px;"
            f"--period:{period:.2f}s;--d:-{rnd.uniform(0, period):.2f}s;--c:{rnd.choice(colors)}"
        )
        drops.append(f'<div class="drop" style="{style}"></div>')
    tempo = motion["tempo"]
    beam = ""
    if motion["beam"]:
        beam = f'<div class="beam" style="--c:{colors[0]};--t:{tempo * 8:.1f}s"></div>'
    notes = []
    for _ in range(motion["notes"]):
        style = (
            f"--x:{rnd.randint(2, 94)}%;--size:{rnd.randint(22, 44)}px;--c:{rnd.choice(colors)};"
            f"--t:{rnd.uniform(7, 13):.1f}s;--d:-{rnd.uniform(0, 13):.1f}s"
        )
        notes.append(f'<span class="note-float" style="{style}">{rnd.choice("♪♫♬")}</span>')
    bars = []
    for _ in range(motion["bars"]):
        style = (
            f"--h:{rnd.uniform(0.35, 1):.2f};--t:{tempo * rnd.uniform(0.5, 1):.2f}s;"
            f"--d:-{rnd.uniform(0, tempo):.2f}s;--c:{rnd.choice(colors)}"
        )
        bars.append(f'<i style="{style}"></i>')
    eq = f'<div class="eq">{"".join(bars)}</div>' if bars else ""
    return f'<div class="bg-motion">{beam}{"".join(blobs)}{"".join(drops)}{"".join(notes)}{eq}</div>'


def background_html(images, theme="default"):
    """
    רקע דינמי: טיפות שנולדות ומתפשטות על המים, וכתמי צבע זזים מאחוריהן, לפי קצב הסגנון.
    מעליהם שלוש שורות של תמונות שזזות לסירוגין. בלי תמונות נשארות רק התנועה והצבעים.
    """
    motion = motion_html(theme)
    style = f"--color-t:{MOTION.get(theme, MOTION['default'])['colors']}s"
    if not images:
        return f'<div class="bg" aria-hidden="true" style="{style}">{motion}</div><div class="bg-shade light"></div>'
    rows = []
    for i in range(3):
        # כל שורה מתחילה מתמונה אחרת, וכל שורה מוכפלת כדי שהתנועה תהיה רציפה
        shifted = images[i * 3 % len(images):] + images[:i * 3 % len(images)]
        while len(shifted) < 8:
            shifted += shifted
        imgs = "".join(f'<img src="{escape(url)}" alt="" loading="lazy">' for url in shifted)
        rows.append(f'<div class="bg-row r{i + 1}"><div class="bg-track">{imgs}{imgs}</div></div>')
    # התנועה מעל התמונות, כדי שהטיפות יאירו את העטיפות
    return f'<div class="bg" aria-hidden="true" style="{style}">{"".join(rows)}{motion}</div><div class="bg-shade"></div>'


BACKGROUND_CSS = """
.bg {
  position: fixed; inset: 0; z-index: -2; overflow: hidden; direction: ltr;
  display: flex; flex-direction: column; justify-content: space-around;
  background: linear-gradient(120deg, var(--c1), var(--c2), var(--c3), var(--c1));
  background-size: 300% 300%; animation: colors var(--color-t, 18s) ease infinite;
}
.bg-motion { position: absolute; inset: 0; overflow: hidden; mix-blend-mode: screen; pointer-events: none; }
.blob {
  position: absolute; left: var(--x); top: var(--y); width: var(--size); height: var(--size);
  border-radius: 50%; background: radial-gradient(closest-side, var(--c), transparent 72%);
  opacity: .38; animation: drift var(--morph) ease-in-out infinite alternate; will-change: translate, scale;
}
.drop {
  position: absolute; left: var(--x); top: var(--y); width: var(--size); height: var(--size);
  margin: calc(var(--size) / -2) 0 0 calc(var(--size) / -2); border-radius: 50%;
  background: radial-gradient(circle, var(--c) 25%, transparent 70%); opacity: 0;
  animation: ripple var(--period) cubic-bezier(.2, .6, .3, 1) infinite; animation-delay: var(--d);
  will-change: scale, opacity;
}
.bg-row { overflow: hidden; }
.bg-track { display: flex; gap: 16px; width: max-content; animation: slide 70s linear infinite; }
.bg-row.r2 .bg-track { animation-direction: reverse; animation-duration: 90s; }
.bg-row.r3 .bg-track { animation-duration: 110s; }
.bg-track img {
  height: 28vh; aspect-ratio: 1; object-fit: cover; border-radius: 18px;
  opacity: .42; box-shadow: 0 8px 30px rgba(0,0,0,.4);
}
.bg-shade {
  position: fixed; inset: 0; z-index: -1;
  background: radial-gradient(ellipse at center, rgba(8,8,12,.55), rgba(8,8,12,.88));
}
.bg-shade.light { background: radial-gradient(ellipse at center, rgba(8,8,12,.3), rgba(8,8,12,.7)); }
@keyframes colors { 0%, 100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@keyframes slide { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.beam {
  position: absolute; top: 50%; left: 50%; width: 150vmax; height: 150vmax; margin: -75vmax 0 0 -75vmax;
  background: conic-gradient(from 0deg, transparent 0deg 14deg, var(--c) 22deg, transparent 32deg 180deg,
    var(--c) 192deg, transparent 200deg 360deg);
  opacity: .12; mix-blend-mode: screen; animation: spin var(--t) linear infinite;
}
.note-float {
  position: absolute; left: var(--x); bottom: -10vh; font-size: var(--size); line-height: 1; color: var(--c);
  text-shadow: 0 0 12px var(--c); opacity: 0; animation: note var(--t) ease-in infinite; animation-delay: var(--d);
}
.eq {
  position: absolute; left: 0; right: 0; bottom: 0; height: 26vh; display: flex; align-items: flex-end;
  gap: 4px; padding: 0 3vw; opacity: .45; mix-blend-mode: screen;
}
.eq i {
  flex: 1; height: 100%; border-radius: 4px 4px 0 0; transform-origin: 50% 100%;
  background: linear-gradient(to top, var(--c), transparent 95%);
  animation: eq var(--t) ease-in-out infinite alternate; animation-delay: var(--d);
}
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes note {
  0% { transform: translateY(0) rotate(-10deg); opacity: 0; }
  12% { opacity: .9; }
  50% { transform: translateY(-55vh) rotate(8deg); }
  100% { transform: translateY(-115vh) rotate(-6deg); opacity: 0; }
}
@keyframes eq { from { scale: 1 .15; } to { scale: 1 var(--h); } }
@keyframes drift {
  from { translate: 0 0; scale: 1; }
  to { translate: var(--drift) calc(var(--drift) * -.6); scale: 1.2; }
}
@keyframes ripple { 0% { scale: 0; opacity: 0; } 6% { scale: 1; opacity: .9; } 100% { scale: 8; opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .bg, .bg-track, .blob, .drop, .beam, .note-float, .eq i { animation: none; }
  .bg-motion { display: none; }
}
"""
