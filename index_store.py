"""
מסד הנתונים המקומי: לכל מונח חיפוש (אירוע, מצב רוח או ז'אנר) השירים שנמצאו בספוטיפיי.
נשמר בקובץ SQLite בתיקייה cache, כך שאין צורך בשרת. האינדקס נבנה ע"י build_index.py.
"""
import json
import os
import sqlite3
import time

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "index.sqlite")
# אינדקס ישן משבוע נחשב ריק, ואז מחפשים שוב בספוטיפיי
MAX_AGE_SECONDS = 7 * 24 * 60 * 60


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
    db.close()


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
