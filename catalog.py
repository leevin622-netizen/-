"""
קטלוג "פלייליסטים קיימים": הפלייליסטים הגדולים בספוטיפיי בארצות הברית ובישראל, לפי קטגוריות.
ספוטיפיי לא חושף כמה פעמים פלייליסט הושמע, ולכן הדירוג הוא לפי מספר העוקבים (הכי קרוב שיש).
ספוטיפיי גם לא חושף מאיזו מדינה המשתמש שיצר את הפלייליסט. "ישראלי" כאן הוא פלייליסט עם עברית בשם,
בתיאור או בשם היוצר (או "Israeli" / "Mizrahi" בשם). כל השאר נחשבים ארצות הברית.
החיפוש לא מחזיר עוקבים, אז הבנייה היא בשני שלבים: איסוף מועמדים בחיפוש, ואז עוקבים לכל מועמד.
נשמר ב-cache\\catalog.sqlite ונבנה ע"י build_playlists.py (גם ברקע, מתוך האפליקציה).
"""
import json
import os
import re
import sqlite3
import time

from engine import FOREIGN_WORDS, WORD_RE, is_hebrew

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "catalog.sqlite")
# כמה פלייליסטים נשארים בקטלוג לכל אזור (ביחד 1000)
PER_REGION = 500
# ספוטיפיי מחזיר עד 10 תוצאות בעמוד. כמה עמודים לכל מונח
PAGE_SIZE = 10
PAGES = 6
# קטלוג ישן משבוע נבנה מחדש (חיפושים ועוקבים)
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
COMPLETE_KEY = "__complete__"

# (מפתח, שם בעברית, מונחי חיפוש באנגלית)
CATEGORIES = [
    ("hits", "להיטים", ["top hits", "viral hits", "today's top hits", "hot hits"]),
    ("pop", "פופ", ["pop", "pop hits", "pop rising"]),
    ("hiphop", "היפ הופ ורפ", ["hip hop", "rap", "trap"]),
    ("rock", "רוק", ["rock", "rock classics", "alternative rock"]),
    ("dance", "דאנס ואלקטרוני", ["dance", "edm", "house", "techno"]),
    ("rnb", "R&B וסול", ["r&b", "soul"]),
    ("country", "קאנטרי", ["country", "country hits"]),
    ("jazz", "ג'ז ובלוז", ["jazz", "blues"]),
    ("chill", "רגוע", ["chill", "acoustic", "lofi"]),
    ("workout", "ספורט", ["workout", "running", "gym"]),
    ("party", "מסיבה", ["party", "summer hits"]),
    ("focus", "ריכוז ולימודים", ["focus", "study", "instrumental"]),
    ("sleep", "שינה", ["sleep", "relax"]),
    ("mood", "מצב רוח", ["happy", "sad songs", "feel good", "love songs"]),
    ("throwback", "עשורים", ["80s", "90s", "2000s", "throwback"]),
    ("israeli", "ישראלי", ["israeli", "mizrahi", "hebrew", "israel"]),
]
CATEGORY_LABELS = {key: label for key, label, _terms in CATEGORIES}

# מונחים בעברית, שמחפשים רק בשוק הישראלי: כך מגיעים למשתמשים ישראלים שכותבים שמות בעברית
HEBREW_TERMS = {
    "hits": ["להיטים", "שירים בעברית", "הלהיטים הגדולים"],
    "pop": ["פופ ישראלי", "פופ"],
    "hiphop": ["היפ הופ ישראלי", "ראפ ישראלי", "ראפ"],
    "rock": ["רוק ישראלי", "רוק"],
    "dance": ["דאנס", "טראנס", "אלקטרוני"],
    "rnb": ["סול"],
    "chill": ["רגוע", "שקט"],
    "workout": ["אימון", "ריצה", "חדר כושר"],
    "party": ["מסיבה", "חתונה", "מזרחית"],
    "focus": ["ריכוז", "לימודים"],
    "sleep": ["שינה"],
    "mood": ["אהבה", "שירי אהבה", "עצוב", "שמח"],
    "throwback": ["שנות ה-80", "שנות ה-90", "שנות ה-2000", "נוסטלגיה"],
    "israeli": ["ישראלי", "מזרחית", "עברית", "ים תיכוני", "ישראל", "זמרים ישראלים"],
}

ISRAEL_WORDS = re.compile(r"\b(israeli|mizrahi|mizrahit|tel[ -]?aviv)\b", re.I)


def search_jobs():
    """כל החיפושים: (שוק, קטגוריה, מונח). אנגלית בשני השווקים, עברית רק בישראל."""
    jobs = []
    for market in ("US", "IL"):
        for key, _label, terms in CATEGORIES:
            jobs += [(market, key, term) for term in terms]
    for key, terms in HEBREW_TERMS.items():
        jobs += [("IL", key, term) for term in terms]
    return jobs


def allowed_name(name):
    """רק אנגלית או עברית: כל אות בשם היא לטינית רגילה או עברית (אימוג'י וסימנים מותרים)."""
    letters = [c for c in name if c.isalpha()]
    if not letters:
        return False
    if any(not (c.isascii() or "֐" <= c <= "׿") for c in letters):
        return False
    return not {w.lower() for w in WORD_RE.findall(name)} & FOREIGN_WORDS


def is_israeli(name, owner, description=""):
    """פלייליסט ישראלי: עברית בשם, בתיאור או בשם היוצר, או Israeli / Mizrahi בשם."""
    return is_hebrew(f"{name} {owner} {description}") or bool(ISRAEL_WORDS.search(name))


def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    db = sqlite3.connect(DB_FILE, timeout=30)
    db.execute(
        """CREATE TABLE IF NOT EXISTS playlists (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner TEXT,
            image TEXT,
            followers INTEGER,
            markets TEXT NOT NULL,
            categories TEXT NOT NULL,
            selected INTEGER NOT NULL DEFAULT 0,
            built_at REAL NOT NULL
        )"""
    )
    # עמודות שנוספו אחר כך: מסד ישן מקבל אותן כאן
    have = {row[1] for row in db.execute("PRAGMA table_info(playlists)")}
    if "israeli" not in have:
        db.execute("ALTER TABLE playlists ADD COLUMN israeli INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE playlists SET israeli = 1")
        for pid, name, owner in db.execute("SELECT id, name, owner FROM playlists").fetchall():
            db.execute("UPDATE playlists SET israeli = ? WHERE id = ?", (int(is_israeli(name, owner or "")), pid))
        db.commit()
    if "description" not in have:
        db.execute("ALTER TABLE playlists ADD COLUMN description TEXT")
    if "followers_at" not in have:
        db.execute("ALTER TABLE playlists ADD COLUMN followers_at REAL")
        db.execute("UPDATE playlists SET followers_at = built_at WHERE followers IS NOT NULL")
        db.commit()
    db.execute("CREATE TABLE IF NOT EXISTS done (key TEXT PRIMARY KEY, built_at REAL NOT NULL)")
    return db


def is_done(key):
    db = _connect()
    row = db.execute("SELECT built_at FROM done WHERE key = ?", (key,)).fetchone()
    db.close()
    return bool(row) and time.time() - row[0] < MAX_AGE_SECONDS


def mark_done(key):
    db = _connect()
    with db:
        db.execute("INSERT OR REPLACE INTO done (key, built_at) VALUES (?, ?)", (key, time.time()))
    db.close()


def needs_refresh():
    """הקטלוג ריק, או שהבנייה האחרונה הסתיימה לפני יותר משבוע (או לא הסתיימה)."""
    return not is_done(COMPLETE_KEY)


def add_candidates(items, market, category):
    """מוסיף מועמדים. פלייליסט שכבר קיים מקבל גם את השוק והקטגוריה החדשים."""
    now = time.time()
    db = _connect()
    with db:
        for item in items:
            israeli = int(is_israeli(item["name"], item["owner"], item.get("description", "")))
            row = db.execute("SELECT markets, categories FROM playlists WHERE id = ?", (item["id"],)).fetchone()
            markets = set(json.loads(row[0])) if row else set()
            categories = set(json.loads(row[1])) if row else set()
            markets.add(market)
            categories.add(category)
            if row:
                db.execute(
                    "UPDATE playlists SET markets = ?, categories = ?, israeli = MAX(israeli, ?) WHERE id = ?",
                    (json.dumps(sorted(markets)), json.dumps(sorted(categories)), israeli, item["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO playlists (id, name, owner, image, description, israeli, markets, categories, built_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item["id"], item["name"], item["owner"], item["image"], item.get("description", ""), israeli,
                     json.dumps(sorted(markets)), json.dumps(sorted(categories)), now),
                )
    db.close()


def reclassify():
    """מחשב מחדש מי ישראלי, אחרי שינוי בכללים או כשהתיאור התעדכן."""
    db = _connect()
    with db:
        for pid, name, owner, description in db.execute("SELECT id, name, owner, description FROM playlists").fetchall():
            db.execute("UPDATE playlists SET israeli = ? WHERE id = ?",
                       (int(is_israeli(name, owner or "", description or "")), pid))
    db.close()


def without_followers():
    """פלייליסטים בלי מספר עוקבים, או עם מספר ישן משבוע."""
    db = _connect()
    ids = [r[0] for r in db.execute(
        "SELECT id FROM playlists WHERE followers IS NULL OR followers_at IS NULL OR followers_at < ?",
        (time.time() - MAX_AGE_SECONDS,),
    )]
    db.close()
    return ids


def set_followers(playlist_id, followers):
    db = _connect()
    with db:
        db.execute(
            "UPDATE playlists SET followers = ?, followers_at = ? WHERE id = ?",
            (followers, time.time(), playlist_id),
        )
    db.close()


def forget(playlist_id):
    db = _connect()
    with db:
        db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    db.close()


def select_top():
    """
    מסמן את PER_REGION הגדולים בכל אזור: ישראלים (עברית), ואת כל השאר מהשוק האמריקאי.
    כך "ישראל" מציג רק פלייליסטים שנוצרו ע"י ישראלים, ולא סתם פלייליסטים ששמעו בישראל.
    """
    db = _connect()
    with db:
        db.execute("UPDATE playlists SET selected = 0")
        for israeli in (1, 0):
            rows = db.execute(
                # קודם אלה שיש להם עוקבים (מהגדול לקטן), ואחריהם אלה שעוד לא נמשכו, לפי סדר התוצאות בחיפוש
                "SELECT id FROM playlists WHERE israeli = ? AND markets LIKE ? "
                "ORDER BY followers IS NULL, followers DESC, rowid LIMIT ?",
                (israeli, '%' if israeli else '%"US"%', PER_REGION),
            ).fetchall()
            db.executemany("UPDATE playlists SET selected = 1 WHERE id = ?", rows)
    db.close()


def load():
    """הקטלוג, מהגדול לקטן. רשימה ריקה אם עוד לא נבנה. markets הוא ["IL"] לישראלי ו-["US"] לשאר."""
    db = _connect()
    rows = db.execute(
        "SELECT id, name, owner, image, followers, israeli, categories FROM playlists "
        "WHERE selected = 1 ORDER BY followers IS NULL, followers DESC, rowid"
    ).fetchall()
    db.close()
    return [
        {"id": r[0], "name": r[1], "owner": r[2], "image": r[3], "followers": r[4],
         "markets": ["IL"] if r[5] else ["US"], "categories": json.loads(r[6])}
        for r in rows
    ]


def short_number(value):
    """1234567 → 1.2M, 45300 → 45K."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value // 1_000}K"
    return str(value)
