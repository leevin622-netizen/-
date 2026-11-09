"""
סימולציה של בניית פלייליסטים על הנתונים האמיתיים שבמטמון המקומי (cache/index.sqlite ו-cache/features.json),
בלי שום בקשה לרשת. בודקת עד כמה השירים שנכנסו לפלייליסט מתאימים באמת למצב הרוח שנבחר.

    python tools/simulate_moods.py [מספר סימולציות] [seed] [סבילות להשלמה]
"""
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PLAYLISTOR_NO_REFRESH", "1")

import engine  # noqa: E402
import vibes  # noqa: E402

# מה נחשב "באמת" מתאים, בנפרד מהטווחים שהמערכת משתמשת בהם לסינון (אחרת הבדיקה הייתה מעגלית).
# מבוסס על המרחב הרגשי הרגיל: valence = כמה שמח, energy = כמה חזק. כל שורה: תנאי שחייב להתקיים.
CORE = {
    "שמח": lambda f: f["valence"] >= 0.6 and f["energy"] >= 0.5,
    "עצוב": lambda f: f["valence"] <= 0.35 and f["energy"] <= 0.6,
    "אנרגטי": lambda f: f["energy"] >= 0.75,
    "רגוע": lambda f: f["energy"] <= 0.45,
    "רומנטי": lambda f: f["energy"] <= 0.65 and 0.2 <= f["valence"] <= 0.8,
    "מוטיבציה": lambda f: f["energy"] >= 0.65 and f["valence"] >= 0.35,
    "שבור לב": lambda f: f["valence"] <= 0.35 and f["energy"] <= 0.7,
    "בא לרקוד": lambda f: f["energy"] >= 0.65 and f["danceability"] >= 0.6,
    "חולמני": lambda f: f["energy"] <= 0.55,
}
# ההפך הברור: שיר שהמשתמש בהחלט לא יצפה לו במצב הרוח הזה
OPPOSITE = {
    "עצוב": lambda f: f["valence"] >= 0.6,
    "שבור לב": lambda f: f["valence"] >= 0.6,
    "שמח": lambda f: f["valence"] <= 0.3,
    "רגוע": lambda f: f["energy"] >= 0.75,
    "חולמני": lambda f: f["energy"] >= 0.8,
    "רומנטי": lambda f: f["energy"] >= 0.85,
    "אנרגטי": lambda f: f["energy"] <= 0.4,
    "מוטיבציה": lambda f: f["energy"] <= 0.4,
    "בא לרקוד": lambda f: f["danceability"] <= 0.4,
}


# אותו רעיון לאירועים: מה שיר באמת צריך להיות כדי להתאים לאירוע
EVENT_CORE = {
    "ריצה": lambda f: f["energy"] >= 0.7 and f["danceability"] >= 0.5,
    "חדר כושר": lambda f: f["energy"] >= 0.68 and f["danceability"] >= 0.5,
    "נסיעה באוטו": lambda f: f["energy"] >= 0.5,
    "עבודה וריכוז": lambda f: f["energy"] <= 0.55,
    "לימודים": lambda f: f["energy"] <= 0.5,
    "בישול": lambda f: 0.35 <= f["energy"] <= 0.8 and f["valence"] >= 0.4,
    "ניקיון הבית": lambda f: f["energy"] >= 0.6 and f["danceability"] >= 0.55,
    "לפני השינה": lambda f: f["energy"] <= 0.35,
    "מסיבה": lambda f: f["energy"] >= 0.7 and f["danceability"] >= 0.6,
    "יום הולדת": lambda f: f["energy"] >= 0.6 and f["danceability"] >= 0.55 and f["valence"] >= 0.5,
    "חתונה": lambda f: f["energy"] >= 0.6 and f["danceability"] >= 0.55 and f["valence"] >= 0.45,
    "על האש": lambda f: f["energy"] >= 0.55 and f["danceability"] >= 0.55 and f["valence"] >= 0.45,
    "שבת בבית": lambda f: f["energy"] <= 0.65,
    "ים": lambda f: f["energy"] >= 0.5 and f["valence"] >= 0.5,
    "טיול בטבע": lambda f: 0.35 <= f["energy"] <= 0.75,
}
# שיר שבהחלט לא מתאים לאירוע
EVENT_OPPOSITE = {
    "ריצה": lambda f: f["energy"] <= 0.45, "חדר כושר": lambda f: f["energy"] <= 0.45,
    "מסיבה": lambda f: f["energy"] <= 0.4, "לפני השינה": lambda f: f["energy"] >= 0.65,
    "עבודה וריכוז": lambda f: f["energy"] >= 0.8, "לימודים": lambda f: f["energy"] >= 0.8,
    "יום הולדת": lambda f: f["valence"] <= 0.3, "חתונה": lambda f: f["valence"] <= 0.25,
}


class OfflineSpotify:
    """לא מחזיר כלום: כל הבנייה נשענת על האינדקס המקומי, ושום דבר לא יוצא לרשת."""

    def search(self, q, type="track", limit=10, offset=0, market=None):
        return {"tracks": {"items": []}}


def use_cached_features_only():
    vibes._fetch = lambda ids: None  # בלי ReccoBeats: רק מה שכבר במטמון
    vibes._cache = None


def features_of(track_id):
    return (vibes._load().get(track_id)) or None


def conflicts(mood, event):
    """האם האירוע דורש אנרגיה שסותרת את מצב הרוח (רגוע בחדר כושר). אז האירוע קובע את האנרגיה, ובודקים רק שמחה."""
    mood_energy = vibes.MOOD_PROFILES.get(mood, {}).get("energy")
    event_energy = vibes.EVENT_PROFILES.get(event, {}).get("energy")
    if not mood_energy or not event_energy:
        return False
    low = max(x for x in (mood_energy[0], event_energy[0], -1) if x is not None)
    high = min(x for x in (mood_energy[1], event_energy[1], 999) if x is not None)
    return low > high


def judge(results, mood, event=""):
    """(מתאימים, הפוכים, בלי נתונים, סה"כ) לפי CORE ו-OPPOSITE."""
    core, opposite = CORE.get(mood), OPPOSITE.get(mood)
    if conflicts(mood, event):
        core = None
        opposite = opposite if mood in ("עצוב", "שבור לב", "שמח") else None
    ok = bad = unknown = 0
    for track in results:
        f = features_of(track["id"])
        if not f or any(f.get(n) is None for n in ("valence", "energy", "danceability")):
            unknown += 1
            continue
        ok += bool(core(f)) if core else 1
        bad += bool(opposite and opposite(f))
    return ok, bad, unknown, len(results)


def simulate(n, seed=1):
    rnd = random.Random(seed)
    random.seed(seed)
    use_cached_features_only()
    sp = OfflineSpotify()
    moods = [m for m in engine.GENRE_HINTS if m in CORE]
    genres = [""] + [term for _name, term in engine.GENRE_CHOICES]
    events = [""] * 6 + list(engine.EVENT_HINTS)
    languages = list(engine.LANGUAGES)
    per_mood = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0])  # ok, bad, unknown, total, playlists, short, requested
    worst = []
    for _ in range(n):
        mood, genre = rnd.choice(moods), rnd.choice(genres)
        event, language = rnd.choice(events), rnd.choice(languages)
        count = rnd.choice((10, 20, 30, 50))
        results = engine.find_tracks(sp, genre, mood, event, language, count)
        ok, bad, unknown, total = judge(results, mood, event)
        row = per_mood[mood]
        for i, v in enumerate((ok, bad, unknown, total, 1, int(total < count), count)):
            row[i] += v
        if bad or (total and ok / total < 0.5):
            worst.append((bad, ok, unknown, total, mood, genre, event, language))
    return per_mood, worst


def simulate_events(n, seed=1):
    """בקשות עם אירוע בלבד (בלי מצב רוח), נבדקות מול EVENT_CORE: {אירוע: [מתאימים, הפוכים, סה"כ, פלייליסטים, קצרים]}."""
    rnd = random.Random(seed)
    random.seed(seed)
    use_cached_features_only()
    sp = OfflineSpotify()
    genres = [""] + [term for _name, term in engine.GENRE_CHOICES]
    table = defaultdict(lambda: [0, 0, 0, 0, 0])
    for _ in range(n):
        event, genre, language = rnd.choice(list(EVENT_CORE)), rnd.choice(genres), rnd.choice(list(engine.LANGUAGES))
        count = rnd.choice((10, 20, 30, 50))
        results = engine.find_tracks(sp, genre, "", event, language, count)
        row = table[event]
        for track in results:
            f = features_of(track["id"])
            if not f or any(f.get(k) is None for k in ("valence", "energy", "danceability")):
                continue
            row[0] += bool(EVENT_CORE[event](f))
            row[1] += bool(EVENT_OPPOSITE.get(event, lambda _f: False)(f))
        row[2] += len(results)
        row[3] += 1
        row[4] += int(len(results) < count)
    return table


def report_events(table):
    print(f"{'אירוע':<14}{'פלייליסטים':>11}{'שירים':>8}{'מתאימים':>10}{'הפוכים':>9}{'קצרים':>8}")
    total = [0, 0, 0, 0, 0]
    for event, row in sorted(table.items()):
        ok, bad, songs, lists, short = row
        pct = lambda x: f"{100 * x / songs:.1f}%" if songs else "-"
        print(f"{event:<14}{lists:>11}{songs:>8}{pct(ok):>10}{pct(bad):>9}{short:>8}")
        total = [a + b for a, b in zip(total, row)]
    ok, bad, songs, lists, short = total
    if songs:
        print(f"{'סה״כ':<14}{lists:>11}{songs:>8}{100 * ok / songs:>9.1f}%{100 * bad / songs:>8.1f}%{short:>8}")


def report(per_mood, worst):
    print(f"{'מצב רוח':<10}{'פלייליסטים':>11}{'שירים':>8}{'מתאימים':>10}{'הפוכים':>9}{'בלי נתונים':>12}{'קצרים':>8}{'מלאים':>8}")
    totals = [0] * 7
    for mood, (ok, bad, unknown, total, playlists, short, wanted) in sorted(per_mood.items()):
        pct = lambda x: f"{100 * x / total:.1f}%" if total else "-"
        print(f"{mood:<10}{playlists:>11}{total:>8}{pct(ok):>10}{pct(bad):>9}{pct(unknown):>12}{short:>8}{100 * total / wanted:>7.0f}%")
        totals = [a + b for a, b in zip(totals, (ok, bad, unknown, total, playlists, short, wanted))]
    ok, bad, unknown, total, playlists, short, wanted = totals
    if total:
        print(f"{'סה״כ':<10}{playlists:>11}{total:>8}{100 * ok / total:>9.1f}%{100 * bad / total:>8.1f}%{100 * unknown / total:>11.1f}%{short:>8}{100 * total / wanted:>7.0f}%")
    print(f"פלייליסטים עם שיר הפוך או פחות ממחצית מתאימים: {len(worst)}")
    for row in sorted(worst, reverse=True)[:8]:
        print("  ", row)


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    if len(sys.argv) > 3:
        engine.NEAR_VIBE = float(sys.argv[3])
    report(*simulate(runs, seed))
    print()
    report_events(simulate_events(runs, seed))
