"""
בחירת אמנים ושירים שאתם אוהבים, למי שיש לו מעט אמנים ושירים שמורים בספוטיפיי.
המשתמש מחפש ומסמן, והבחירות נשמרות בחשבון הספוטיפיי שלו. ההמלצות באות ממה שכבר יש לו,
ואם אין לו אמנים או שירים אהובים בכלל, מציגים זמרים מוכרים.
"""
import re
from concurrent.futures import ThreadPoolExecutor

import lastfm
import library
from engine import to_result

# המסך מוצג רק למי שיש לו פחות מ-30 אמנים וגם פחות מ-300 שירים שמורים
FAVOURITE_ARTISTS = 30
FAVOURITE_SONGS = 300
# מכמה אמנים מתחילים להמליץ, וכמה אמנים דומים מביאים מכל אחד
SEED_ARTISTS = 5
SIMILAR_ARTISTS = 10
RECOMMENDED_ARTISTS = 8
TRACKS_PER_ARTIST = 2
WORKERS = 4

# זמרים מוכרים, למי שאין לו אמנים או שירים אהובים. הם אותם זמרים לכל המשתמשים
WELL_KNOWN = [
    "עומר אדם", "Taylor Swift", "נועה קירל", "Ed Sheeran", "אייל גולן", "Dua Lipa",
    "שרית חדד", "Bruno Mars", "אריק איינשטיין", "Coldplay", "סטטיק ובן אל", "Queen",
]
# הזמרים המוכרים נמצאים פעם אחת בספוטיפיי ונשמרים כאן, כדי לא לחפש אותם שוב לכל משתמש
_well_known = []


def is_spotify_id(value):
    """מזהה של ספוטיפיי הוא 22 תווים. בודקים אותו לפני שמשתמשים בו בבקשה."""
    return bool(re.fullmatch(r"[A-Za-z0-9]{22}", value or ""))


def saved_songs(sp, uid):
    return library.cached(uid, "saved_total", lambda: sp.current_user_saved_tracks(limit=1)["total"])


def followed_artists(sp, uid):
    return library.cached(uid, "followed", lambda: library.followed_artists(sp))


def favourite_artist_ids(sp, uid):
    """אמנים שהמשתמש עוקב אחריהם, ואמנים שהוא הכי שומע."""
    _, top_objects = library.cached(uid, "top_artists", lambda: library.top_ranks(sp, "artists"))
    return {a["id"] for a in followed_artists(sp, uid)} | set(top_objects)


def needs_favourites(sp, uid):
    """המסך מוצג רק כשיש מעט גם אמנים וגם שירים. אם יש מספיק מאחד מהם, לא מציגים."""
    if saved_songs(sp, uid) >= FAVOURITE_SONGS:
        return False
    return len(favourite_artist_ids(sp, uid)) < FAVOURITE_ARTISTS


def artist_summary(artist):
    images = artist.get("images") or []
    return {"id": artist["id"], "name": artist["name"], "image": images[-1]["url"] if images else ""}


def find_artist(sp, name):
    """האמן בספוטיפיי שנקרא כמו השם. אם אין התאמה מדויקת, התוצאה הכי רלוונטית. None אם לא נמצא."""
    items = [a for a in sp.search(q=name, type="artist", limit=5)["artists"]["items"] if a]
    exact = [a for a in items if a["name"].lower() == name.lower()]
    best = (exact or items or [None])[0]
    return artist_summary(best) if best else None


def seed_artists(sp, uid):
    """
    מאיפה מתחילים להמליץ: קודם מי שעוקבים אחריו, אחר כך מי שהכי שומעים,
    ואם עדיין חסר, אמנים מהשירים השמורים. מחזיר רשימה של (מזהה, שם).
    """
    ranks, top_objects = library.cached(uid, "top_artists", lambda: library.top_ranks(sp, "artists"))
    ordered = sorted(top_objects.values(), key=lambda a: min(ranks[a["id"]].values()))
    found = {}
    for artist in [*followed_artists(sp, uid), *ordered]:
        found.setdefault(artist["id"], artist["name"])
    if len(found) < SEED_ARTISTS:
        for item in library.cached(uid, "saved", lambda: library.all_saved_tracks(sp)):
            for artist in item["track"]["artists"]:
                if artist.get("id"):
                    found.setdefault(artist["id"], artist["name"])
    return list(found.items())[:SEED_ARTISTS]


def similar_names(names):
    """
    שמות של אמנים דומים לכמה אמנים שהמשתמש אוהב, לפי Last.fm.
    מי שדומה להרבה מהם מופיע קודם. בלי מפתח Last.fm הרשימה ריקה.
    """
    known = {name.lower() for name in names}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        similar_lists = list(pool.map(lastfm.get_similar_artists, names))
    scores, spelling = {}, {}
    for similar in similar_lists:
        for item in similar:
            key = item["name"].lower()
            if key not in known:
                scores[key] = scores.get(key, 0) + item["match"]
                spelling.setdefault(key, item["name"])
    return [spelling[key] for key in sorted(scores, key=scores.get, reverse=True)][:SIMILAR_ARTISTS]


def artist_tracks(sp, artist):
    """שירים של האמן, רק כאלה שהוא האמן הראשון בהם, כדי שלא יופיעו שירי פיצ'ר."""
    query = artist["name"].replace('"', " ")
    items = sp.search(q=f'artist:"{query}"', type="track", limit=10)["tracks"]["items"]
    own = [t for t in items if t and t["artists"] and t["artists"][0].get("id") == artist["id"]]
    return [to_result(t) for t in own[:TRACKS_PER_ARTIST]]


def well_known_artists(sp):
    if not _well_known:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            found = [a for a in pool.map(lambda name: find_artist(sp, name), WELL_KNOWN) if a]
        _well_known.extend(found)
    return list(_well_known)


def build_recommendations(sp, uid):
    seeds = seed_artists(sp, uid)
    seed_ids = {artist_id for artist_id, _ in seeds}
    source, artists = "similar", []
    if seeds:
        names = similar_names([name for _, name in seeds])
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            found = list(pool.map(lambda name: find_artist(sp, name), names))
        artists = list({a["id"]: a for a in found if a and a["id"] not in seed_ids}.values())
    if not artists:
        # אין למשתמש אמנים או שירים אהובים, או שאין למי לדמות: מציעים זמרים מוכרים
        source = "well_known"
        artists = well_known_artists(sp)
    artists = artists[:RECOMMENDED_ARTISTS]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        track_lists = list(pool.map(lambda artist: artist_tracks(sp, artist), artists))
    return {
        "source": source,
        "artists": artists,
        "tracks": [track for tracks in track_lists for track in tracks],
    }


def recommendations(sp, uid):
    """המלצות למשתמש. הן דורשות כמה בקשות לספוטיפיי, לכן נשמרות לכמה שעות כמו שאר הנתונים."""
    return library.cached(uid, "recs", lambda: build_recommendations(sp, uid))


def saved_flags(sp, track_ids):
    """{מזהה: האם השיר כבר שמור אצל המשתמש}. בקשה אחת לכל 50 שירים."""
    ids = list(dict.fromkeys(i for i in track_ids if i))
    flags = {}
    for start in range(0, len(ids), 50):
        block = ids[start:start + 50]
        flags.update(zip(block, sp.current_user_saved_tracks_contains(block)))
    return flags


def search(sp, q):
    """חיפוש אחד שמחזיר גם אמנים וגם שירים, בבקשה אחת לספוטיפיי."""
    result = sp.search(q=q, type="artist,track", limit=8)
    artists = [artist_summary(a) for a in result["artists"]["items"] if a]
    tracks = [to_result(t) for t in result["tracks"]["items"] if t]
    return artists, tracks
