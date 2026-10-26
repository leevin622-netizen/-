import random
import re
from concurrent.futures import ThreadPoolExecutor

import requests
from spotipy.exceptions import SpotifyException

import index_store
from vibes import distance, get_features, profile_for, strength

HEBREW_RE = re.compile(r"[֐-׿]")

# כמה תוצאות ספוטיפיי מחזיר בכל בקשת חיפוש, וכמה עמודים לכל היותר נבקש לכל מונח
PAGE_SIZE = 10
MAX_PAGES = 20
# מכמה עמודים ראשונים מגרילים נקודת התחלה, כדי שכל פלייליסט ייצא שונה
RANDOM_START_PAGES = 3
# כמה מונחים נחפש במקביל. יותר מזה מתקרב להגבלת הבקשות של ספוטיפיי
TERM_WORKERS = 3
# מונחים דלים (כמו "sad" או "psytrance") מקבלים עוד חיפושים עם מילים נרדפות, כשהתוצאות מעטות
TERM_ALIASES = {
    "sad": ["sad songs", "heartbreak"],
    "psytrance": ["goa trance", "psychedelic trance"],
    "breakup": ["heartbreak", "sad songs"],
    "ballad": ["love ballad", "power ballad"],
    "nostalgia": ["throwback", "nostalgic"],
    "sing along": ["sing along songs"],
}

GENRE_HINTS = {
    "שמח": ["pop", "dance", "funk"],
    "עצוב": ["sad", "ballad", "indie"],
    "ממריץ": ["rock", "electronic", "hip hop"],
    "רגוע": ["chill", "acoustic", "jazz"],
}

# אירועים וסיטואציות, לפי קטגוריות בתפריט. לכל אחד: מונחי החיפוש בספוטיפיי
EVENT_GROUPS = {
    "ספורט ותנועה": {
        "ריצה": ["workout", "electronic", "hip hop"],
        "חדר כושר": ["workout", "hip hop", "rock"],
        "רכיבה על אופניים": ["workout", "dance", "electronic"],
        "יוגה ומדיטציה": ["meditation", "ambient", "chill"],
        "הליכה": ["pop", "indie", "acoustic"],
    },
    "יום יום": {
        "בוקר טוב": ["morning", "acoustic", "pop"],
        "נסיעה באוטו": ["road trip", "pop", "rock"],
        "בדרך לעבודה": ["pop", "indie", "hip hop"],
        "עבודה וריכוז": ["instrumental", "lo-fi", "chill"],
        "לימודים": ["lo-fi", "instrumental", "chill"],
        "בישול": ["jazz", "soul", "funk"],
        "ניקיון הבית": ["pop", "dance", "funk"],
        "מקלחת": ["pop", "dance", "sing along"],
        "לפני השינה": ["sleep", "ambient", "piano"],
    },
    "חברים ואירועים": {
        "מסיבה": ["party", "dance", "house"],
        "יום הולדת": ["party", "pop", "dance"],
        "חתונה": ["wedding", "pop", "dance"],
        "על האש": ["mizrahi", "pop", "reggae"],
        "ארוחת ערב עם חברים": ["jazz", "soul", "acoustic"],
        "ערב רומנטי": ["romantic", "r&b", "soul"],
        "קריוקי": ["sing along", "pop", "classic"],
        "ערב משחקים": ["funk", "indie", "pop"],
    },
    "שבת וחגים": {
        "שבת בבית": ["israeli folk", "acoustic", "jewish"],
        "חגים": ["jewish", "israeli folk", "mizrahi"],
        "ערב שירה בציבור": ["israeli folk", "sing along", "acoustic"],
    },
    "טבע וחופש": {
        "ים": ["summer", "reggae", "pop"],
        "טיול בטבע": ["folk", "acoustic", "indie"],
        "קמפינג ומדורה": ["folk", "acoustic", "sing along"],
        "חופשה בחו\"ל": ["summer", "latin", "pop"],
        "בריכה": ["summer", "dance", "reggaeton"],
    },
    "רגשות": {
        "פרידה": ["sad", "ballad", "breakup"],
        "געגועים": ["ballad", "nostalgia", "acoustic"],
        "נוסטלגיה": ["oldies", "80s", "90s"],
        "מוטיבציה": ["motivation", "hip hop", "rock"],
    },
}
EVENT_HINTS = {event: terms for group in EVENT_GROUPS.values() for event, terms in group.items()}

LANGUAGES = ["ביחד", "עברית", "אנגלית"]

# ז'אנרים לבחירה: (שם בתפריט, מונח החיפוש בספוטיפיי)
HEBREW_GENRES = [
    ("פופ ישראלי", "israeli pop"),
    ("מזרחית", "mizrahi"),
    ("ים תיכוני", "mediterranean"),
    ("רוק ישראלי", "israeli rock"),
    ("היפ הופ ישראלי", "israeli hip hop"),
    ("אינדי ישראלי", "israeli indie"),
    ("שירי ארץ ישראל", "israeli folk"),
    ("מוזיקה יהודית וחסידית", "jewish"),
    ("טראנס ישראלי", "psytrance"),
]
WORLD_GENRES = [
    ("פופ", "pop"), ("רוק", "rock"), ("היפ הופ", "hip hop"), ("R&B", "r&b"),
    ("דאנס ואלקטרוני", "dance"), ("לטיני", "latin"), ("ג'אז", "jazz"),
    ("קאנטרי", "country"), ("מטאל", "metal"), ("K-Pop", "k-pop"), ("קלאסית", "classical"),
]
HEBREW_GENRE_TERMS = {term for _, term in HEBREW_GENRES}


def is_hebrew(text):
    return bool(HEBREW_RE.search(text))


def build_terms(genre, mood, event, language):
    terms = []
    if genre:
        terms.append(genre)
    terms += GENRE_HINTS.get(mood, [])
    terms += EVENT_HINTS.get(event, [])
    if language == "עברית":
        terms.insert(0, "israeli")
    # בלי כפילויות, בלי לשנות את הסדר
    return list(dict.fromkeys(terms)) or ["pop"]


WORD_RE = re.compile(r"[^\W\d_]+")
# מילים נפוצות בספרדית, פורטוגזית, איטלקית וצרפתית, שכמעט לא מופיעות בשמות שירים באנגלית
FOREIGN_WORDS = {
    "el", "los", "las", "del", "que", "con", "por", "para", "una", "amor", "corazon",
    "vida", "noche", "cancion", "quiero", "campanas", "alba",
    "dos", "das", "nao", "voce", "meu", "minha",
    "della", "che", "sono", "je", "les", "et", "moi", "toi",
}


def is_english(title):
    """שם באנגלית: רק אותיות לטיניות בלי סימנים (ñ, é, ç...), ובלי מילים נפוצות משפות אחרות."""
    if not title.isascii():
        return False
    words = {w.lower() for w in WORD_RE.findall(title)}
    return bool(words) and not words & FOREIGN_WORDS


def passes_language(track, language):
    text = track["name"] + " " + " ".join(a["name"] for a in track["artists"])
    if language == "עברית":
        return is_hebrew(text)
    if language == "אנגלית":
        # שם השיר קובע, ושם האמן רק לא אמור להיות בעברית
        return is_english(track["name"]) and not is_hebrew(text)
    return True


def album_year(track):
    """שנת היציאה של האלבום, או None. ספוטיפיי נותן תאריך מלא, שנה בלבד, או שנה וחודש."""
    date = (track.get("album") or {}).get("release_date") or ""
    return int(date[:4]) if date[:4].isdigit() else None


def passes_years(track, years):
    """years הוא (מ-שנה, עד-שנה) או None. שיר בלי שנה ידועה לא עובר סינון לפי שנה."""
    if not years:
        return True
    year = album_year(track)
    return year is not None and years[0] <= year <= years[1]


def to_result(track):
    return {
        "id": track.get("id"),
        "album_id": track.get("album", {}).get("id"),
        "name": track["name"],
        "artist": ", ".join(a["name"] for a in track["artists"]),
        "artists": [(a["id"], a["name"]) for a in track["artists"]],
        "uri": track["uri"],
        "image": album_image(track),
        "duration": track.get("duration_ms") or 0,
        "year": album_year(track) or "",
    }


def album_image(track):
    """התמונה הקטנה ביותר של העטיפה, מספיקה לרשימה."""
    images = track.get("album", {}).get("images") or []
    return images[-1]["url"] if images else ""


def search_page(sp, query, page):
    response = sp.search(q=query, type="track", limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    return response["tracks"]["items"]


def accepted(track, language, years):
    return passes_language(track, language) and passes_years(track, years)


def collect_for_query(sp, query, language, wanted, years=None):
    """אוסף עד wanted שירים לשאילתה, החל מעמוד אקראי."""
    start = random.randrange(RANDOM_START_PAGES)
    tracks = []
    # מנקודת ההתחלה עד הסוף, ואם עדיין חסר, גם העמודים שלפניה
    for pages in (range(start, MAX_PAGES), range(start)):
        for page in pages:
            items = search_page(sp, query, page)
            if not items:
                break
            tracks += [t for t in items if t and accepted(t, language, years)]
            if len(tracks) >= wanted:
                return tracks
    return tracks


def collect_for_term(sp, term, language, wanted, years=None):
    """קודם מהאינדקס המקומי (ראה build_index.py), ואם אין בו שירים מתאימים, מחפש בספוטיפיי."""
    indexed = [t for t in index_store.load_term(term) if accepted(t, language, years)]
    if indexed:
        return indexed
    try:
        return search_term(sp, term, language, wanted, years)
    except (SpotifyException, requests.RequestException) as error:
        # ספוטיפיי מוגבל או לא זמין: מדלגים על המונח הזה, והשאר ממשיכים לעבוד
        print(f"[פלייליסטור] מדלגים על {term}: {error}")
        return []


def search_term(sp, term, language, wanted, years=None):
    """
    קודם מחפש לפי ז'אנר אמיתי בספוטיפיי, ואם אין כזה ז'אנר, לפי מילת חיפוש רגילה.
    אם עדיין מעט מדי שירים, מוסיפים את המילים הנרדפות של המונח (TERM_ALIASES).
    """
    tracks = collect_for_query(sp, f'genre:"{term}"', language, wanted, years)
    if not tracks:
        tracks = collect_for_query(sp, term, language, wanted, years)
    for alias in TERM_ALIASES.get(term, []):
        if len(tracks) >= wanted:
            break
        known = {t["uri"] for t in tracks}
        tracks += [t for t in collect_for_query(sp, alias, language, wanted, years) if t["uri"] not in known]
    return tracks


def pick(pools, count, seen):
    """בוחר שירים לסירוגין מכל מאגר, כדי שכל מונח יקבל ייצוג."""
    for pool in pools:
        random.shuffle(pool)
    results = []
    while len(results) < count and any(pools):
        for pool in pools:
            while pool:
                track = pool.pop()
                if track["uri"] not in seen:
                    seen.add(track["uri"])
                    results.append(to_result(track))
                    break
            if len(results) >= count:
                break
    return results


def find_personal_tracks(sp, language, count, seen, years=None):
    """שירים של האמנים המועדפים על המשתמש."""
    artists = sp.current_user_top_artists(limit=20, time_range="medium_term")["items"]
    random.shuffle(artists)
    pools = []
    for artist in artists[:5]:
        items = search_page(sp, f'artist:"{artist["name"]}"', 0)
        pools.append([
            t for t in items
            if t and accepted(t, language, years)
            and any(a["id"] == artist["id"] for a in t["artists"])
        ])
    return pick(pools, count, seen)


def separate_artists(results):
    """שירים של אותו אמן לא יופיעו ברצף, אם יש ברירה. בשביל זה נשאר הסדר בתוך כל אמן."""
    remaining = list(results)
    ordered = []
    while remaining:
        last = ordered[-1]["artists"][0][0] if ordered and ordered[-1]["artists"] else None
        index = next(
            (i for i, t in enumerate(remaining) if not t["artists"] or t["artists"][0][0] != last), 0
        )
        ordered.append(remaining.pop(index))
    return ordered


def filter_by_vibe(pools, mood, event, wanted, ranges=None):
    """
    משאיר רק שירים שמתאימים לאווירה (קצב, אנרגיה, שמחה) לפי ReccoBeats.
    שירים שלא עומדים בטווח נזרקים, והמובהקים ביותר נשארים בראש כל מאגר.
    אם השירות לא עונה בכלל, מחזירים את המאגרים כמו שהם.
    """
    profile = profile_for(mood, event, ranges)
    if not profile:
        return pools
    ids = [t["id"] for pool in pools for t in pool if t.get("id")]
    features = get_features(ids)
    if not features:
        return pools
    filtered = []
    for pool in pools:
        fitting = [t for t in pool if t.get("id") in features and distance(features[t["id"]], profile) == 0]
        fitting.sort(key=lambda t: strength(features[t["id"]], profile), reverse=True)
        # מספיק מועמדים לכל מקום, כדי ש-pick יוכל לבחור ויגוון
        filtered.append(fitting[:max(wanted * 2, PAGE_SIZE)])
    return filtered


def find_tracks(sp, genre, mood, event, language, count, personal=False, ranges=None, years=None, exclude=()):
    """
    מחזיר רשימת שירים (dict עם name, artist, uri) לפי הקריטריונים.
    exclude: כתובות של שירים שכבר בפלייליסט, כדי לא להביא אותם שוב (הוסף עוד שירים).
    """
    seen = set(exclude)
    results = []
    if personal:
        try:
            results = find_personal_tracks(sp, language, count // 2, seen, years)
        except (SpotifyException, requests.RequestException) as error:
            # האמנים המועדפים הם תוספת. אם ספוטיפיי לא זמין, ממשיכים בלעדיהם
            print(f"[פלייליסטור] מדלגים על האמנים המועדפים: {error}")

    terms = build_terms(genre, mood, event, language)
    wanted = count - len(results)
    # כל מונח אוסף בערך פי שניים ממה שצריך, כדי שיהיה ממה לבחור
    per_term = max(PAGE_SIZE, -(-wanted * 2 // len(terms)))
    # המונחים נאספים במקביל, כך שבקשה לכמה ז'אנרים לא מחכה לכל אחד בתורו
    with ThreadPoolExecutor(max_workers=TERM_WORKERS) as pool:
        pools = list(pool.map(lambda term: collect_for_term(sp, term, language, per_term, years), terms))
    pools = filter_by_vibe(pools, mood, event, wanted, ranges)
    results += pick(pools, wanted, seen)
    random.shuffle(results)
    return separate_artists(results)


def matches(term, tags):
    """האם מונח (למשל "israeli pop") מתאים לתגיות של אמן. כל מילה במונח צריכה להופיע בתגיות."""
    words = " ".join(tags).lower()
    return all(word in words for word in term.lower().split())


def filter_liked_by_vibe(scored, mood, event, ranges=None):
    """
    אותו סינון אווירה כמו בחיפוש, רק לשירים שאהבת. שירים שלא מתאימים לקצב ולאנרגיה נזרקים,
    והמובהקים ביותר מקבלים ניקוד גבוה יותר. אם השירות לא עונה, לא משנים כלום.
    """
    profile = profile_for(mood, event, ranges)
    if not profile or not scored:
        return scored
    features = get_features([track["id"] for _, track in scored if track.get("id")])
    if not features:
        return scored
    fitting = []
    for score, track in scored:
        found = features.get(track.get("id"))
        if found and distance(found, profile) == 0:
            fitting.append((score + strength(found, profile), track))
    return fitting


def find_liked_tracks(saved, artist_tags, genre, mood, event, language, count, ranges=None, years=None, exclude=()):
    """
    פלייליסט מתוך השירים שאהבת. artist_tags: {id של אמן: [ז'אנרים ותגיות]}.
    אם בחרת ז'אנר, נשארים רק שירים שהאמן שלהם מתאים לו. מצב רוח ואירוע מעדיפים שירים מתאימים.
    """
    extra_terms = GENRE_HINTS.get(mood, []) + EVENT_HINTS.get(event, [])
    scored = []
    for item in saved:
        track = item["track"]
        if track.get("uri") in exclude or not track.get("uri", "").startswith("spotify:track:"):
            continue
        if not accepted(track, language, years):
            continue
        tags = [t for a in track["artists"] for t in artist_tags.get(a.get("id"), [])]
        if genre and not matches(genre, tags):
            continue
        score = sum(matches(term, tags) for term in extra_terms) + random.random()
        scored.append((score, track))
    scored = filter_liked_by_vibe(scored, mood, event, ranges)
    scored.sort(key=lambda pair: pair[0], reverse=True)
    results = [to_result(track) for _, track in scored[:count]]
    random.shuffle(results)
    return separate_artists(results)


def create_playlist(sp, name, uris):
    playlist = sp.current_user_playlist_create(name=name, public=False, description="נוצר ב-פלייליסטור")
    # ספוטיפיי מקבל עד 100 שירים בכל בקשת הוספה
    for start in range(0, len(uris), 100):
        sp.playlist_add_items(playlist["id"], uris[start:start + 100])
    return playlist["external_urls"]["spotify"]
