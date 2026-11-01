"""
מסד הנתונים המקומי: לכל מונח חיפוש (אירוע, מצב רוח או ז'אנר) השירים שנמצאו בספוטיפיי.
נשמר בקובץ SQLite בתיקייה cache, כך שאין צורך בשרת. האינדקס נבנה ומתעדכן ברקע ע"י build_playlists.py
(או ידנית ע"י build_index.py).
"""
import json
import os
import sqlite3
import time

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "index.sqlite")
# מונח ישן משבוע מתעדכן ברקע. עד שהעדכון מגיע אליו, ממשיכים להשתמש בשירים הישנים
FRESH_SECONDS = 7 * 24 * 60 * 60
# רק אינדקס ישן מזה נחשב ריק, ואז מחפשים בספוטיפיי בזמן הבנייה
MAX_AGE_SECONDS = 60 * 24 * 60 * 60


def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.execute(
        """CREATE TABLE IF NOT EXISTS tracks (
            term TEXT NOT NULL,
            track_id TEXT NOT NULL,
            raw TEXT NOT NULL,
            built_at REAL NOT NULL,
            PRIMARY KEY (term, track_id)
        )"""
    )
    # אינדקס לשליפה לפי מונח: זה מה שהאפליקציה עושה בכל בקשה
    db.execute("CREATE INDEX IF NOT EXISTS idx_tracks_term ON tracks (term, built_at)")
    # מתי כל מונח נבנה, גם כשלא נמצאו לו שירים (כדי לא לחפש אותו שוב ושוב)
    db.execute("CREATE TABLE IF NOT EXISTS built (term TEXT PRIMARY KEY, built_at REAL NOT NULL)")
    return db


def save_term(term, tracks):
    """שומר את כל השירים של מונח. שמירה חוזרת מחליפה את הישנים."""
    now = time.time()
    db = _connect()
    with db:
        db.execute("DELETE FROM tracks WHERE term = ?", (term,))
        db.executemany(
            "INSERT OR REPLACE INTO tracks (term, track_id, raw, built_at) VALUES (?, ?, ?, ?)",
            [(term, t["id"], json.dumps(t, ensure_ascii=False), now) for t in tracks if t.get("id")],
        )
        db.execute("INSERT OR REPLACE INTO built (term, built_at) VALUES (?, ?)", (term, now))
    db.close()


def stale_terms(terms):
    """המונחים שצריך לבנות או לעדכן: אין להם אינדקס, או שהוא ישן משבוע."""
    db = _connect()
    stale = []
    for term in terms:
        row = db.execute("SELECT built_at FROM built WHERE term = ?", (term,)).fetchone()
        built_at = row[0] if row else db.execute("SELECT MAX(built_at) FROM tracks WHERE term = ?", (term,)).fetchone()[0]
        if built_at is None or time.time() - built_at > FRESH_SECONDS:
            stale.append(term)
    db.close()
    return stale


def load_term(term):
    """השירים של המונח כמו שספוטיפיי החזיר אותם. רשימה ריקה אם אין אינדקס טרי."""
    db = _connect()
    rows = db.execute("SELECT raw, built_at FROM tracks WHERE term = ?", (term,)).fetchall()
    db.close()
    if not rows or time.time() - rows[0][1] > MAX_AGE_SECONDS:
        return []
    return [json.loads(raw) for raw, _ in rows]


def stats():
    """כמה מונחים ושירים יש באינדקס, לתצוגה."""
    db = _connect()
    terms, tracks = db.execute("SELECT COUNT(DISTINCT term), COUNT(*) FROM tracks").fetchone()
    db.close()
    return {"terms": terms, "tracks": tracks}
