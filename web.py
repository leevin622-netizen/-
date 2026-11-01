"""
הבסיס של האתר: האפליקציה, אבטחה (טפסים, הגבלת קצב, כותרות, דחיסה), התחברות לספוטיפיי,
הסגנון של המשתמש (וייב), מבנה העמוד (page) ורכיבי HTML משותפים. הדפים עצמם בקבצי routes_*.py.
"""
import gzip
from datetime import timedelta
import hashlib
import os
import secrets
import time
from html import escape
from flask import Flask, g, has_request_context, redirect, request, session
from dotenv import load_dotenv
import requests
import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth, SpotifyOauthError
from lastfm import get_tags_for_artists
import build_playlists
import library
import ratelimit
import themes
from i18n import _, LANGS, lang, text_dir, translate_js
import taste
import json
from urllib.parse import urlsplit
from engine import HEBREW_GENRES, WORLD_GENRES, GENRE_CHOICES
from vibes import describe


load_dotenv()


app = Flask(__name__)


# בלי FLASK_SECRET ב-.env נוצר מפתח אקראי, וההתחברות תתאפס בכל הפעלה מחדש של השרת
app.secret_key = os.getenv("FLASK_SECRET") or secrets.token_hex(32)


# ההתחברות נשמרת 30 יום, ולא נמחקת כשסוגרים את הדפדפן. כל כניסה מאריכה אותה
app.config.update(
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30), SESSION_REFRESH_EACH_REQUEST=True,
)
# העיצוב בקובץ static/style.css. הדפדפן שומר אותו לשנה, והגרסה בכתובת (לפי התוכן) מתחלפת כשהוא משתנה
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 365 * 24 * 60 * 60
with open(os.path.join(app.static_folder, "style.css"), "rb") as _style:
    STYLE_VERSION = hashlib.sha256(_style.read()).hexdigest()[:10]


# כשהאפליקציה נגישה דרך https (למשל כתובת קבועה לחברים), הקוקי נשלח רק ב-https
PUBLIC_HTTPS = (os.getenv("SPOTIFY_REDIRECT_URI") or "").startswith("https://")


app.config["SESSION_COOKIE_SECURE"] = PUBLIC_HTTPS


if not os.getenv("FLASK_SECRET"):
    print("[פלייליסטור] אין FLASK_SECRET ב-.env, ולכן כל הפעלה מחדש של השרת מנתקת את כולם")


def csrf_token():
    """
    אסימון שכל טופס חייב לשלוח, כדי שאתר אחר לא יוכל לשמור פלייליסטים בשמך.
    בכל עמוד האסימון נראה אחרת (מוצפן עם מסכה אקראית), כי העמודים נשלחים דחוסים,
    ואסימון קבוע בעמוד דחוס אפשר לנחש לפי גודל התשובה (התקפת BREACH).
    """
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    secret = session["csrf"].encode()
    mask = secrets.token_bytes(len(secret))
    return (mask + bytes(a ^ b for a, b in zip(mask, secret))).hex()


def unmask_csrf(value):
    """האסימון המקורי מתוך אסימון עם מסכה, או הערך כמו שהוא אם הוא לא כזה."""
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return value
    half = len(raw) // 2
    if not raw or len(raw) % 2:
        return value
    return bytes(a ^ b for a, b in zip(raw[:half], raw[half:])).decode("latin-1")


@app.before_request
def check_csrf():
    # בלי אסימון בסשן אין מה לאמת, ולכן גם טופס בלי אסימון נדחה
    expected = session.get("csrf") or ""
    given = unmask_csrf(request.form.get("csrf") or "")
    if request.method == "POST" and not (
        expected and secrets.compare_digest(given.encode("latin-1", "replace"), expected.encode())
    ):
        return (
            _('<!doctype html><meta charset="utf-8"><p dir="rtl">הטופס פג תוקף. רעננו את העמוד ונסו שוב.</p>'),
            400,
        )


# כמה בקשות לכתובת אחת. הפעולות שעולות לספוטיפיי מוגבלות חזק, מה שנשאר מוגבל בעדינות
RATE_LIMITS = {
    ("POST", "/build"): ("build", 20, 60),
    ("POST", "/build/more"): ("build", 20, 60),
    ("POST", "/save"): ("save", 10, 60),
    # כל ▶ שולח עד 3 בקשות החוצה (Deezer ו-iTunes)
    ("GET", "/preview"): ("preview", 60, 60),
    ("GET", "/login"): ("login", 20, 600),
    ("GET", "/callback"): ("login", 20, 600),
}


DEFAULT_LIMIT = ("all", 300, 60)


@app.before_request
def note_activity():
    """כל ביקור באתר (חוץ מקבצים קבועים) עוצר לכמה דקות את העדכון ברקע, כדי שהמכסה של ספוטיפיי תישאר למשתמשים."""
    if request.endpoint not in ("static", None):
        build_playlists.note_user_activity()


@app.before_request
def check_rate_limit():
    ip = ratelimit.client_ip(request.remote_addr, request.headers.get("X-Forwarded-For"))
    bucket, limit, window = RATE_LIMITS.get((request.method, request.path), DEFAULT_LIMIT)
    if not ratelimit.allow(bucket, ip, limit, window):
        return (
            _('<!doctype html><meta charset="utf-8"><p dir="rtl">יותר מדי בקשות מהמכשיר הזה. נסו שוב בעוד כמה דקות.</p>'),
            429,
        )


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    response.headers["Referrer-Policy"] = "same-origin"
    if PUBLIC_HTTPS:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


# דחיסה: עמוד של 40KB יורד לכ-8KB. קטן מזה לא שווה דחיסה
COMPRESS_TYPES = {"text/html", "application/json", "text/css", "application/javascript"}


COMPRESS_MIN_BYTES = 1024


@app.after_request
def compress(response):
    if (
        "gzip" not in request.headers.get("Accept-Encoding", "")
        or response.direct_passthrough
        or response.status_code != 200
        or response.mimetype not in COMPRESS_TYPES
        or "Content-Encoding" in response.headers
    ):
        return response
    data = response.get_data()
    if len(data) < COMPRESS_MIN_BYTES:
        return response
    response.set_data(gzip.compress(data, compresslevel=6))
    response.headers["Content-Encoding"] = "gzip"
    response.vary.add("Accept-Encoding")
    return response


# user-follow-modify ו-user-library-modify מאפשרים לשמור אמנים ושירים בחשבון. שינוי ההרשאות דורש התחברות מחדש
# playlist-read-private מאפשר לראות את הפלייליסטים הפרטיים שנוצרו כאן, כדי לערוך אותם
SCOPE = (
    "user-library-read user-library-modify user-top-read user-follow-read user-follow-modify "
    "playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private"
)


RELOGIN_NOTE = (
    '<p class="note">כדי לאשר הרשאות חדשות, כמו שמירת אמנים ושירים בחשבון שלכם, צריך להתחבר שוב.</p>'
)


MAX_TRACKS = 200


# פלייליסט מסימון ידני בטבלת השירים שאהבת יכול להיות גדול יותר
MAX_SAVE = 2000


def make_auth():
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=SCOPE,
        # הטוקן נשמר רק בסשן של המשתמש ולא בקובץ .cache על הדיסק
        cache_handler=MemoryCacheHandler(),
    )


def get_spotify_client():
    token_info = session.get("token_info")
    if not token_info:
        return None
    auth = make_auth()
    if auth.is_token_expired(token_info):
        try:
            token_info = auth.refresh_access_token(token_info["refresh_token"])
        except SpotifyOauthError:
            # ההרשאה בוטלה או פגה, צריך להתחבר מחדש
            session.pop("token_info", None)
            return None
        session["token_info"] = token_info
    # language="he": ספוטיפיי מחזיר שם בעברית לאמנים שיש להם כזה (בעיקר ישראלים),
    # ואמנים מחו"ל נשארים באנגלית. כך אין צורך בבקשה נפרדת לכל אמן.
    return user_client(token_info["access_token"])


def user_client(access_token):
    """
    לקוח ספוטיפיי למשתמש. retries=0: כשספוטיפיי מבקש להמתין שעות, המשתמש מקבל הודעה מיד,
    ולא נשאר תקוע (ברירת המחדל של spotipy מחכה כמה שספוטיפיי מבקש, גם שעות).
    """
    return spotipy.Spotify(auth=access_token, language="he", retries=0, requests_timeout=10)


def local_path(value):
    """כתובת בתוך האתר לחזרה אליה, או "/". "//" או "/\" היו שולחים לאתר אחר."""
    value = value or ""
    if value.startswith("/") and value[1:2] not in ("/", "\\") and value.isprintable():
        return value
    return "/"


def back_from_referrer():
    """הדף שממנו הגיעו, רק אם הוא באתר הזה. כותרת Referer יכולה להגיע מאתר אחר."""
    parts = urlsplit(request.referrer or "")
    if parts.netloc != request.host:
        return "/"
    return local_path(parts.path + (f"?{parts.query}" if parts.query else ""))


# כמה תמונות של אמנים ועטיפות לשים ברקע
BACKGROUND_IMAGES = 24


def image_url(images):
    """תמונה בגודל בינוני (ספוטיפיי מחזיר אותן מהגדולה לקטנה)."""
    if not images:
        return ""
    return images[min(1, len(images) - 1)]["url"]


def load_vibe(sp, uid):
    """
    הסגנון של המשתמש ותמונות לרקע, לפי האמנים והשירים שהוא הכי שומע.
    גם הז'אנרים שהוא הכי שומע (genres) והתגיות של האמנים המובילים (artist_tags), להתאמה אישית.
    """
    artist_ranks, artist_objects = library.cached(uid, "top_artists", lambda: library.top_ranks(sp, "artists"))
    _ranks, track_objects = library.cached(uid, "top_tracks", lambda: library.top_ranks(sp, "tracks"))
    artists = sorted(artist_objects.values(), key=lambda a: min(artist_ranks[a["id"]].values()))[:40]
    # ז'אנרים מספוטיפיי, ואם אין, תגיות מ-Last.fm
    no_genres = [a for a in artists if not a.get("genres")]
    tags = dict(zip([a["id"] for a in no_genres], get_tags_for_artists([a["name"] for a in no_genres])))
    artist_tags = {a["id"]: a.get("genres") or tags.get(a["id"], []) for a in artists}
    weighted = [(51 - min(artist_ranks[a["id"]].values()), artist_tags[a["id"]]) for a in artists]
    # תמונות לרקע לכל סגנון: רק אמנים שהתגיות שלהם מתאימות לו, והעטיפות של השירים שלהם
    by_theme = {}
    for name in themes.THEMES:
        fitting = {a["id"] for a in artists if name in themes.themes_for_tags(artist_tags[a["id"]])}
        faces = [image_url(a.get("images")) for a in artists if a["id"] in fitting]
        covers = [
            image_url(t.get("album", {}).get("images"))
            for t in track_objects.values()
            if any(artist.get("id") in fitting for artist in t.get("artists", []))
        ]
        by_theme[name] = mix_images(faces, covers)
    all_faces = [image_url(a.get("images")) for a in artists]
    all_covers = [image_url(t.get("album", {}).get("images")) for t in track_objects.values()]
    return {
        "theme": themes.detect_theme(weighted),
        "images": mix_images(all_faces, all_covers),
        "by_theme": by_theme,
        "genres": taste.genre_scores(weighted),
        "artist_tags": artist_tags,
    }


def mix_images(faces, covers):
    """תמונות לסירוגין: אמן, עטיפה, אמן, עטיפה. בלי כפילויות, בגודל שהרקע צריך."""
    mixed = [url for pair in zip(faces, covers) for url in pair] + faces[len(covers):] + covers[len(faces):]
    return list(dict.fromkeys(u for u in mixed if u))[:BACKGROUND_IMAGES]


def current_vibe():
    """העיצוב שבחרו. אם לא בחרו, הסגנון שמתאים למה שנשמע הכי הרבה."""
    auto = auto_vibe()
    choice = session.get("vibe_choice")
    if choice in themes.THEMES and session.get("token_info"):
        # התמונות מאחורה הן של האמנים מאותו סגנון. אם אין כאלה, מציגים את התמונות הכלליות
        images = auto.get("by_theme", {}).get(choice) or auto["images"]
        return {"theme": choice, "images": images}
    return auto


def auto_vibe():
    """הסגנון של המשתמש המחובר לפי מה שנשמע הכי הרבה. אם משהו נכשל, העיצוב הקלאסי, כדי שהעמוד תמיד ייטען."""
    if not session.get("token_info"):
        return {"theme": "default", "images": []}
    try:
        sp = get_spotify_client()
        if sp is None:
            return {"theme": "default", "images": []}
        uid = user_id(sp)
        # המפתח כולל גרסה, כדי שמטמון ישן בלי ז'אנרים ותגיות לא ייטען
        return library.cached(uid, "vibe_v3", lambda: load_vibe(sp, uid))
    except Exception:
        return {"theme": "default", "images": []}


# זמרים ישראלים שאוהבים, לרקע מסך ההתחברות: תמונה של כל אחד ועטיפות של השירים שלו
ISRAELI_SINGERS = [
    "עומר אדם", "נועה קירל", "אייל גולן", "שרית חדד", "עדן בן זקן", "קרן פלס", "סטטיק ובן אל",
    "שלומי שבת", "רביד פלוטניק", "עידן רייכל", "עדן חסון", "אביב גפן", "מוש בן ארי", "אריק איינשטיין",
]


# התמונות של הזמרים כמעט לא משתנות, ולכן מתעדכנות פעם בשבוע (28 חיפושים בספוטיפיי בכל עדכון)
LOGIN_SECONDS = 7 * 24 * 60 * 60


LOGIN_RETRY_SECONDS = 15 * 60


_login_cache = {"until": 0.0, "images": []}


def _login_file():
    return os.path.join(library.CACHE_DIR, "login_images.json")


def _read_login_file():
    """התמונות שנשמרו בפעם האחרונה שספוטיפיי ענה. כך המסך לא נשאר ריק כשספוטיפיי מגביל."""
    try:
        with open(_login_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _login_file_time():
    try:
        return os.path.getmtime(_login_file())
    except OSError:
        return 0.0


def _write_login_file(images):
    try:
        os.makedirs(library.CACHE_DIR, exist_ok=True)
        with open(_login_file(), "w", encoding="utf-8") as f:
            json.dump(images, f)
    except OSError:
        pass


def login_images():
    """
    תמונות לרקע מסך ההתחברות. אין עדיין משתמש מחובר, אז משתמשים בפרטי האפליקציה.
    התוצאה נשמרת לכמה שעות. אם ספוטיפיי לא עונה, המסך נטען בלי תמונות ונסה שוב בעוד רבע שעה.
    """
    now = time.time()
    if now < _login_cache["until"]:
        return _login_cache["images"]
    # אחרי הפעלה מחדש: הקובץ מהעדכון האחרון, אם הוא מהשבוע האחרון
    saved_at = _login_file_time()
    if now - saved_at < LOGIN_SECONDS:
        images = _read_login_file()
        if images:
            _login_cache.update(until=saved_at + LOGIN_SECONDS, images=images)
            return images
    if now < limited_until():
        # ספוטיפיי מגביל: לא שולחים עוד בקשות, ומציגים את מה שנשמר
        images = _read_login_file()
        _login_cache.update(until=now + LOGIN_RETRY_SECONDS, images=images)
        return images
    try:
        # אותם שמות משתנים כמו בהתחברות (SPOTIFY_CLIENT_ID), לא השמות ברירת המחדל של spotipy
        credentials = SpotifyClientCredentials(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"), client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        )
        sp = spotipy.Spotify(auth_manager=credentials, retries=0, requests_timeout=10, language="he")
        faces, covers = [], []
        for name in ISRAELI_SINGERS:
            found = [a for a in sp.search(q=name, type="artist", limit=3)["artists"]["items"] if a]
            if not found:
                continue
            artist = next((a for a in found if a["name"] == name), found[0])
            faces.append(image_url(artist.get("images")))
            tracks = sp.search(q=f'artist:"{name}"', type="track", limit=5)["tracks"]["items"]
            own = [t for t in tracks if t and t["artists"] and t["artists"][0].get("id") == artist["id"]]
            covers += [image_url(t["album"].get("images")) for t in own[:2]]
        images, ttl = mix_images(faces, covers), LOGIN_SECONDS
        if images:
            _write_login_file(images)
    except (spotipy.SpotifyException, SpotifyOauthError, requests.RequestException):
        images, ttl = _read_login_file(), LOGIN_RETRY_SECONDS
    _login_cache.update(until=now + ttl, images=images)
    return images


# סמל האתר בלשונית הדפדפן, בתוך העמוד עצמו. בלעדיו הדפדפן מבקש /favicon.ico בכל ביקור ומקבל שגיאה
FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
    "%3Ctext y='.9em' font-size='90'%3E%F0%9F%8E%A7%3C/text%3E%3C/svg%3E"
)


def page(body, title=None, wide=False, script="", theme=None, images=None):
    # כשספוטיפיי מוגבל, לא מבקשים ממנו עוד נתונים בשביל העיצוב
    limited = time.time() < limited_until()
    vibe = {"theme": "default", "images": []} if limited else current_vibe()
    theme = theme or vibe["theme"]
    images = vibe["images"] if images is None else images
    user = session.get("user_name")
    user_html = (
        _("<span class=\"user\">{a0}<a href=\"/logout\">התנתקות</a></span>", a0=escape(user)) if user else ""
    )
    switch = vibe_switch() if session.get("token_info") else ""
    title = title or _("פלייליסטור")
    return (
        f'<!doctype html><html lang="{lang()}" dir="{text_dir()}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<link rel="icon" href="{FAVICON}">'
        f"<title>{escape(title)}</title><link rel='stylesheet' href='/static/style.css?v={STYLE_VERSION}'><style>{themes.theme_css(theme)}</style></head><body>"
        + themes.background_html(images, theme)
        + _("<main class=\"wrap{a0}\"><header><div class=\"brand\">{a1}<a class=\"logo\" href=\"/\">🎧 פלייליסטור</a></div>{a2}</header>", a0=" wide" if wide else "", a1=switch, a2=lang_switch() + user_html)
        + notices()
        + body
        + "</main>"
        + (f"<script>{translate_js(script)}</script>" if script else "")
        + "</body></html>"
    )


def options(values, selected=""):
    """אפשרויות לתפריט. הערך נשאר בעברית (כך הוא מוכר בשרת), והתווית בשפת הממשק."""
    return "".join(
        f'<option value="{escape(v)}"{" selected" if v == selected else ""}>{escape(_(v))}</option>'
        for v in values
    )


def lang_switch():
    """בחירת שפה קטנה בכותרת העליונה, בכל המסכים."""
    choices = "".join(
        f'<option value="{code}"{" selected" if code == lang() else ""}>{escape(name)}</option>'
        for code, name, _dir in LANGS
    )
    return (
        '<form method="post" action="/lang" class="vibe-switch lang-switch"><span aria-hidden="true">🌐</span>'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        f'<input type="hidden" name="back" value="{escape(request.full_path)}">'
        f'<select name="lang" aria-label="Language" onchange="this.form.submit()">{choices}</select>'
        '<noscript><button class="btn" type="submit">OK</button></noscript></form>'
    )


def cover(url):
    return f'<img src="{escape(url)}" alt="" loading="lazy">' if url else '<div class="noimg"></div>'


def genre_options(selected=""):
    return _('<option value="">ללא</option>') + "".join(
        f'<option value="{escape(term)}"{" selected" if term == selected else ""}>{escape(_(name))}</option>'
        for name, term in GENRE_CHOICES
    )


def my_genres():
    """הז'אנרים מטופס היצירה שהמשתמש המחובר הכי שומע, מהמוביל. רשימה ריקה אם עוד לא ידוע."""
    return taste.top_genres(auto_vibe().get("genres") or {})


GENRE_NAMES = {term: name for name, term in HEBREW_GENRES + WORLD_GENRES + GENRE_CHOICES}


def liked_artist_tags(sp, uid, saved):
    """ז'אנרים ותגיות לכל אמן ברשימת השירים שאהבת, כדי לבנות ממנה פלייליסט לפי ז'אנר."""
    def load():
        _ranks, top_objects = library.cached(uid, "top_artists", lambda: library.top_ranks(sp, "artists"))
        followed = library.cached(uid, "followed", lambda: library.followed_artists(sp))
        genres = {a["id"]: a.get("genres") or [] for a in list(followed) + list(top_objects.values())}
        names = {a["id"]: a["name"] for item in saved for a in item["track"]["artists"] if a.get("id")}
        missing = [i for i in names if not genres.get(i)]
        for artist_id, tags in zip(missing, get_tags_for_artists([names[i] for i in missing])):
            genres[artist_id] = tags
        return genres
    return library.cached(uid, "liked_tags", load)


def user_id(sp):
    if not session.get("user_id"):
        session["user_id"] = sp.current_user()["id"]
    return session["user_id"]


def cell(text, value=None, cls="", html=None):
    """
    תא בטבלה. value הוא הערך שלפיו ממיינים (ברירת מחדל: הטקסט עצמו).
    html, אם יש, מוצג במקום הטקסט (למשל קישור), והמיון עדיין לפי הטקסט.
    """
    cls_attr = f' class="{cls}"' if cls else ""
    # כשממיינים לפי הטקסט עצמו אין צורך לכתוב אותו פעמיים: המיון לוקח את הטקסט של התא (TABLE_JS)
    sort_attr = "" if value is None else f' data-v="{escape(str(value))}"'
    return f'<td{cls_attr}{sort_attr}>{html or escape(str(text))}</td>'


def spotify_link(text, kind, item_id, inner_html=None):
    """קישור שפותח שיר, אלבום או אמן בספוטיפיי. בלי מזהה, רק הטקסט."""
    content = inner_html or escape(text)
    if not item_id:
        return content
    # קישור שיש בו רק תמונה, למשל עטיפת אלבום, צריך שם שהקורא מסך יכול להקריא
    name = "" if text else _(' aria-label="פתיחה בספוטיפיי"')
    return (
        f'<a class="sp" href="https://open.spotify.com/{kind}/{escape(item_id)}"'
        # בלי rel="noopener": דפדפנים מוסיפים אותו לבד לכל target="_blank", וכך כל שורה בטבלה קצרה יותר
        f' target="_blank"{name}>{content}</a>'
    )


def artist_links(track):
    return ", ".join(spotify_link(name, "artist", artist_id) for artist_id, name in track["artists"])


def header(columns):
    """columns: רשימת (כותרת, סוג), כשהסוג הוא num, text או None (לא ממוין)."""
    return "<tr>" + "".join(
        f'<th data-type="{kind}">{escape(label)}</th>' if kind else f"<th>{escape(label)}</th>"
        for label, kind in columns
    ) + "</tr>"


def stat_boxes(stats):
    return '<div class="stats">' + "".join(
        f"<div><b>{escape(str(value))}</b><span>{escape(label)}</span></div>" for label, value in stats
    ) + "</div>"


def format_duration(ms):
    seconds = ms // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def format_rank(rank):
    return f"#{rank[0]} · {_(rank[1])}" if rank else ""


def play_button(track):
    """כפתור ▶ שטוען קטע רק בלחיצה (ראו LAZY_PLAY_JS)."""
    first_artist = track["artists"][0][1] if track.get("artists") else track.get("artist", "")
    return (
        _("<button type=\"button\" class=\"play\" data-artist=\"{a0}\" data-title=\"{a1}\" data-id=\"{a2}\" aria-pressed=\"false\" aria-label=\"השמעת קטע מ{a3}\">▶</button>", a0=escape(first_artist), a1=escape(track["name"]), a2=escape(track.get("id") or ""), a3=escape(track["name"]))
    )


def track_row(track, checkbox=False, feat=None):
    check = (
        _("<input type=\"checkbox\" name=\"uri\" value=\"{a0}\" aria-label=\"לכלול את {a1}\" checked>", a0=escape(track["uri"]), a1=escape(track["name"])) if checkbox else ""
    )
    # הנתונים מאפשרים מיון בדף, והתיאור מוצג ליד שם האמן
    sort_data = {
        "name": track["name"].lower(), "artist": track["artist"].lower(),
        "duration": track.get("duration") or 0, "year": track.get("year") or "",
    }
    attrs = "".join(f' data-{key}="{escape(str(value))}"' for key, value in sort_data.items())
    info = ""
    if feat:
        attrs += f' data-bpm="{feat.get("tempo") or 0}" data-energy="{feat.get("energy") or 0}" data-valence="{feat.get("valence") or 0}"'
        info = describe(feat, _("אנרגיה"), _("שמחה"))
    moves = (
        _('<span class="moves">'
        '<button type="button" class="move" data-dir="-1" aria-label="העברה למעלה">▲</button>'
        '<button type="button" class="move" data-dir="1" aria-label="העברה למטה">▼</button></span>')
    )
    return (
        f"<li{attrs}>{check}{spotify_link('', 'album', track.get('album_id'), cover(track.get('image', '')))}"
        f"<div class=\"info\"><div class=\"title\">{spotify_link(track['name'], 'track', track.get('id'))}</div>"
        f"<div class=\"sub\">{artist_links(track)}{(' · ' + escape(info)) if info else ''}</div></div>"
        f"{play_button(track)}{moves}</li>"
    )


# ספוטיפיי מגביל את האפליקציה כולה. כשהוא עונה "יותר מדי בקשות", זוכרים עד מתי, ומציגים את השעה לכולם
_limit = {"until": 0.0}


def retry_after(error):
    """
    כמה שניות ספוטיפיי מבקש להמתין. כש-spotipy מוותר בעצמו המספר לא בשגיאה אלא רק ביומן,
    ולכן לוקחים אותו משם (build_playlists קורא אותו). בלי מספר בכלל, דקה.
    """
    header = (getattr(error, "headers", None) or {}).get("Retry-After", "")
    if str(header).isdigit():
        return max(int(header), 1)
    return build_playlists._RetryAfterSpy.seconds or 60


def remember_limit(error):
    """
    זוכר את ההגבלה לכל העמודים, וגם לעדכון ברקע: הוא לא ישלח בקשות עד שהיא תיגמר.
    ההגבלה משותפת לכל האפליקציה, כך שמה שמשתמש נתקל בו חל גם על העדכון ברקע, ולהפך.
    """
    seconds = retry_after(error)
    _limit["until"] = max(_limit["until"], time.time() + seconds)
    if seconds > build_playlists.MAX_WAIT_SECONDS:
        build_playlists.remember_block(seconds)


def limited_until():
    """עד מתי ספוטיפיי מגביל: ממה שמשתמשים נתקלו בו, או ממה שהעדכון ברקע נתקל בו."""
    return max(_limit["until"], build_playlists.blocked_until())


def clock(timestamp):
    return time.strftime("%H:%M", time.localtime(timestamp))


def on_cache_stale(error, saved_at):
    """
    נתונים שמורים מוצגים במקום טעינה שנכשלה (library.on_stale).
    מסמנים לעמוד הנוכחי מאיזו שעה הנתונים, ואם זו הגבלה, זוכרים אותה לכל העמודים.
    """
    if isinstance(error, spotipy.SpotifyException) and error.http_status == 429:
        remember_limit(error)
    if has_request_context():
        g.stale_since = min(getattr(g, "stale_since", saved_at), saved_at)


library.on_stale = on_cache_stale


def notices():
    """הודעות שמופיעות מעל כל עמוד: ספוטיפיי מוגבל, או נתונים ישנים שמוצגים."""
    notes = []
    if time.time() < limited_until():
        until = clock(limited_until())
        notes.append(
            _("ספוטיפיי הגביל את הבקשות לזמן מה. אפשר לנסות שוב אחרי {a0}. עד אז מוצגים הנתונים שנשמרו בפעם האחרונה, כשיש כאלה.", a0=until)
        )
    since = getattr(g, "stale_since", None) if has_request_context() else None
    if since is not None:
        when = clock(since)
        notes.append(_("חלק מהנתונים מ-{a0}, כי ספוטיפיי לא ענה. הם יתעדכנו כשהוא יחזור.", a0=when))
    return "".join(f'<div class="warn">{escape(note)}</div>' for note in notes)


@app.errorhandler(spotipy.SpotifyException)
def spotify_error(error):
    if error.http_status == 401:
        session.pop("token_info", None)
        return redirect("/login")
    if error.http_status == 429:
        remember_limit(error)
        # ההודעה עם השעה מופיעה מעל העמוד (notices), כאן רק מה שקרה
        return page(_("<p>לא הצלחנו לטעון את העמוד כרגע. אפשר לחזור לדף הבית ולנסות שוב אחרי ההמתנה.</p>")), 429
    return page(_("<p>ספוטיפיי החזיר שגיאה. נסו שוב בעוד כמה רגעים.</p>")), 502


@app.errorhandler(requests.RequestException)
def network_error(error):
    return page(_("<p>אין חיבור לספוטיפיי כרגע. בדקו את החיבור לאינטרנט ונסו שוב.</p>")), 503


@app.errorhandler(404)
def not_found(error):
    return page(_('<h1>הדף לא נמצא</h1><p class="note">אולי הקישור ישן או שיש בו טעות. <a href="/">חזרה לדף הבית</a></p>')), 404


@app.errorhandler(405)
def wrong_method(error):
    # למשל רענון של דף שהגיע משליחת טופס
    return redirect("/")


@app.errorhandler(500)
def server_error(error):
    """תקלה בקוד. Flask כבר כתב את הפרטים ליומן. אם גם בניית העמוד נכשלת, מחזירים טקסט פשוט."""
    try:
        return page(_('<h1>משהו השתבש</h1><p class="note">קרתה תקלה אצלנו. נסו שוב בעוד רגע, או <a href="/">חזרו לדף הבית</a>.</p>')), 500
    except Exception:
        return "Playlistor: internal error", 500


def vibe_switch():
    """בחירת העיצוב, קטנה, בפינה הימנית למעלה בכל המסכים. ברירת המחדל אוטומטית, והבחירה משנה הכול."""
    chosen = session.get("vibe_choice", "")
    options = _('<option value="">אוטומטי</option>') + "".join(
        f'<option value="{key}"{" selected" if key == chosen else ""}>{t["emoji"]} {escape(_(t["label"]))}</option>'
        for key, t in themes.THEMES.items()
    )
    return (
        _("<form method=\"post\" action=\"/vibe\" class=\"vibe-switch\"><input type=\"hidden\" name=\"csrf\" value=\"{a0}\"><input type=\"hidden\" name=\"back\" value=\"{a1}\"><select name=\"vibe\" aria-label=\"בחרו עיצוב\" onchange=\"this.form.submit()\">{a2}</select><noscript><button class=\"btn\" type=\"submit\">החל</button></noscript></form>", a0=csrf_token(), a1=escape(request.full_path), a2=options)
    )


DECADES = list(range(1950, 2030, 10))


# שם עשור בכל שפה. short: 90 במקום 1990, למשל "שנות ה-90"
DECADE_FORMATS = {
    "he": ("שנות ה-{short}", "שנות ה-{full}"), "en": ("{short}s", "{full}s"),
}


def decade_label(decade):
    """1990 → "שנות ה-90", 2010 → "שנות ה-2010" (ובאנגלית 90s, 2010s)."""
    old, new = DECADE_FORMATS[lang()]
    return (old if decade < 2000 else new).format(short=f"{decade % 100:02d}", full=decade)


def decade_options(first_label):
    return f'<option value="">{escape(first_label)}</option>' + "".join(
        f'<option value="{d}">{escape(decade_label(d))}</option>' for d in DECADES
    )
