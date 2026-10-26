import os
import secrets
from html import escape
from flask import Flask, redirect, request, session
from dotenv import load_dotenv
import requests
import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from lastfm import get_tags_for_artists, get_user_playcounts
import library
import themes
import favourites
import json
from urllib.parse import urlencode
from playlist_names import suggest_names
from engine import (
    GENRE_HINTS, EVENT_HINTS, EVENT_GROUPS, LANGUAGES, HEBREW_GENRES, WORLD_GENRES,
    find_tracks, find_liked_tracks, create_playlist, to_result,
)
from vibes import describe, get_features

load_dotenv()

app = Flask(__name__)
# בלי FLASK_SECRET ב-.env נוצר מפתח אקראי, וההתחברות תתאפס בכל הפעלה מחדש של השרת
app.secret_key = os.getenv("FLASK_SECRET") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


def csrf_token():
    """אסימון שכל טופס חייב לשלוח, כדי שאתר אחר לא יוכל לשמור פלייליסטים בשמך."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.before_request
def check_csrf():
    # בלי אסימון בסשן אין מה לאמת, ולכן גם טופס בלי אסימון נדחה
    expected = session.get("csrf") or ""
    given = request.form.get("csrf") or ""
    if request.method == "POST" and not (
        expected and secrets.compare_digest(given.encode(), expected.encode())
    ):
        return (
            '<!doctype html><meta charset="utf-8"><p dir="rtl">הטופס פג תוקף. רעננו את העמוד ונסו שוב.</p>',
            400,
        )


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    response.headers["Referrer-Policy"] = "same-origin"
    return response

# user-follow-modify ו-user-library-modify מאפשרים לשמור אמנים ושירים בחשבון. שינוי ההרשאות דורש התחברות מחדש
SCOPE = (
    "user-library-read user-library-modify user-top-read user-follow-read user-follow-modify "
    "playlist-modify-public playlist-modify-private"
)
RELOGIN_NOTE = (
    '<p class="note">כדי לאשר הרשאות חדשות, כמו שמירת אמנים ושירים בחשבון שלכם, צריך להתחבר שוב.</p>'
)
MAX_TRACKS = 200
# פלייליסט מסימון ידני בטבלת השירים שאהבת יכול להיות גדול יותר
MAX_SAVE = 2000

STYLE = """
:root {
  --bg: #121212; --card: rgba(18, 18, 18, .72); --card-hover: rgba(50, 50, 50, .8); --text: #f2f2f2;
  --muted: #c4c4c4; --border: rgba(255, 255, 255, .14);
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text); min-height: 100vh;
  font-family: "Segoe UI", Arial, sans-serif; line-height: 1.5;
}
.wrap { max-width: 640px; margin: 0 auto; padding: 16px 16px 48px; }
header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
header a.logo { color: var(--text); text-decoration: none; font-size: 22px; font-weight: 700; }
header .user { color: var(--muted); font-size: 14px; }
header .user a { color: var(--muted); margin-inline-start: 8px; }
h1 { font-size: 24px; margin: 8px 0 16px; }
a { color: var(--accent); }
.menu { display: grid; gap: 12px; }
.menu a {
  display: block; background: var(--card); color: var(--text); text-decoration: none;
  padding: 18px; border-radius: 12px; font-size: 17px;
}
.menu a:hover { background: var(--card-hover); }
.menu a small { display: block; color: var(--muted); font-size: 14px; }
.card { background: var(--card); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.menu a, .card, .list li, .stats div, .table-wrap, .vibe {
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
}
.vibe {
  display: inline-flex; gap: 6px; align-items: center; margin-bottom: 16px; padding: 6px 14px;
  border-radius: 999px; background: var(--card); border: 1px solid var(--accent); font-size: 14px;
}
h1 { text-shadow: 0 2px 12px rgba(0, 0, 0, .6); }
label.field { display: block; margin-bottom: 14px; color: var(--muted); font-size: 14px; }
input[type=text], input[type=number], select {
  display: block; width: 100%; margin-top: 4px; padding: 10px 12px; font-size: 16px;
  background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 8px;
}
label.check { display: flex; gap: 8px; align-items: center; margin-bottom: 14px; }
.btn {
  display: inline-block; width: 100%; padding: 14px; border: 0; border-radius: 999px;
  background: var(--accent); color: var(--on-accent); font-size: 17px; font-weight: 700;
  text-align: center; text-decoration: none; cursor: pointer;
}
.btn:hover { background: var(--accent-dark); }
.list { list-style: none; padding: 0; margin: 0; }
.list li {
  display: flex; align-items: center; gap: 12px; padding: 8px;
  border-radius: 8px; background: var(--card); margin-bottom: 6px;
}
.list img, .list .noimg { width: 48px; height: 48px; border-radius: 4px; flex: none; background: var(--border); }
.list .info { min-width: 0; flex: 1; }
.list .title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.list .sub { color: var(--muted); font-size: 14px; }
.list input[type=checkbox] { width: 20px; height: 20px; accent-color: var(--accent); flex: none; }
.note { color: var(--muted); font-size: 14px; }
.success { background: #133d24; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.wide { max-width: 1100px; }
.stats { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.stats div { background: var(--card); border-radius: 12px; padding: 12px 16px; flex: 1; min-width: 130px; }
.stats b { display: block; font-size: 22px; }
.stats span { color: var(--muted); font-size: 13px; }
input.search { margin-bottom: 12px; }
.table-wrap { overflow-x: auto; border-radius: 12px; background: var(--card); }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 8px 10px; text-align: start; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { color: var(--muted); font-weight: 600; cursor: pointer; user-select: none; position: sticky; top: 0; background: #181818; }
th:hover { color: var(--text); }
th.asc::after { content: " ▲"; } th.desc::after { content: " ▼"; }
td img, td .noimg { width: 36px; height: 36px; border-radius: 4px; display: block; background: var(--border); }
td.name { max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
td.muted { color: var(--muted); }
tr:hover td { background: var(--card-hover); }
td input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--accent); }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: end; margin-bottom: 12px; }
.toolbar label.field { flex: 1; min-width: 200px; margin: 0; }
.toolbar .btn { width: auto; padding: 10px 18px; font-size: 15px; }
.btn.secondary { background: var(--card); color: var(--text); border: 1px solid var(--border); }
a.sp { color: inherit; text-decoration: none; }
a.sp:hover { color: var(--accent); text-decoration: underline; }
.list form { margin: 0; flex: none; }
.list .btn { width: auto; padding: 8px 14px; font-size: 14px; white-space: nowrap; }
h2 { font-size: 19px; margin: 22px 0 10px; text-shadow: 0 2px 12px rgba(0, 0, 0, .6); }
""" + themes.BACKGROUND_CSS

# מיון טבלה בלחיצה על כותרת, וסינון לפי טקסט חופשי
# כפתור "שם אחר": עובר בין הצעות השמות
NAME_JS = """
var nameButton = document.getElementById("other-name");
if (nameButton) {
  var names = JSON.parse(nameButton.dataset.names), current = 0;
  nameButton.addEventListener("click", function () {
    current = (current + 1) % names.length;
    document.getElementById("title").value = names[current];
  });
}
"""

# מיון התצוגה המקדימה לפי BPM, אנרגיה או שמחה, ועירבוב
SORT_JS = """
var list = document.querySelector("ul.list"), sortSelect = document.getElementById("sort");
var shuffleButton = document.getElementById("shuffle");
if (list && sortSelect) {
  var originalOrder = Array.from(list.children);
  sortSelect.addEventListener("change", function () {
    var key = sortSelect.value;
    var items = key ? Array.from(list.children).sort(function (a, b) {
      return parseFloat(b.dataset[key]) - parseFloat(a.dataset[key]);
    }) : originalOrder;
    items.forEach(function (li) { list.appendChild(li); });
  });
}
if (list && shuffleButton) {
  shuffleButton.addEventListener("click", function () {
    var items = Array.from(list.children);
    for (var i = items.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1)), t = items[i];
      items[i] = items[j]; items[j] = t;
    }
    items.forEach(function (li) { list.appendChild(li); });
    if (sortSelect) sortSelect.value = "";
  });
}
"""

# תצוגת מספרים חיה לטווחים הידניים
RANGE_JS = """
document.querySelectorAll("output[id^='out-']").forEach(function (out) {
  var label = out.closest("label");
  var low = label.querySelector("input[name$='_min']"), high = label.querySelector("input[name$='_max']");
  function show() { out.textContent = low.value + "% עד " + high.value + "%"; }
  low.addEventListener("input", show);
  high.addEventListener("input", show);
  show();
});
"""

TABLE_JS = """
document.querySelectorAll("table.sortable").forEach(function (table) {
  var body = table.tBodies[0];
  table.querySelectorAll("th[data-type]").forEach(function (th, col) {
    th.addEventListener("click", function () {
      var desc = !th.classList.contains("desc");
      table.querySelectorAll("th").forEach(function (h) { h.classList.remove("asc", "desc"); });
      th.classList.add(desc ? "desc" : "asc");
      var numeric = th.dataset.type === "num";
      var rows = Array.from(body.rows);
      rows.sort(function (a, b) {
        var x = a.cells[th.cellIndex].dataset.v, y = b.cells[th.cellIndex].dataset.v;
        if (numeric) {
          x = x === "" ? -Infinity : parseFloat(x); y = y === "" ? -Infinity : parseFloat(y);
          return desc ? y - x : x - y;
        }
        return desc ? y.localeCompare(x, "he") : x.localeCompare(y, "he");
      });
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });
});
document.querySelectorAll("[data-check-visible]").forEach(function (button) {
  button.addEventListener("click", function () {
    var body = document.getElementById(button.dataset.checkVisible).tBodies[0];
    var check = button.dataset.state !== "on";
    Array.from(body.rows).forEach(function (r) {
      if (r.style.display !== "none") { r.querySelector("input[type=checkbox]").checked = check; }
    });
    button.dataset.state = check ? "on" : "off";
    button.textContent = check ? "בטל סימון של המוצגים" : "סמן את כל המוצגים";
  });
});
document.querySelectorAll("input.search").forEach(function (input) {
  var body = document.getElementById(input.dataset.table).tBodies[0];
  input.addEventListener("input", function () {
    var q = input.value.trim().toLowerCase();
    Array.from(body.rows).forEach(function (r) {
      r.style.display = r.textContent.toLowerCase().indexOf(q) === -1 ? "none" : "";
    });
  });
});
"""


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
    # retries=0: כשספוטיפיי מבקש להמתין שעות, המשתמש מקבל הודעה מיד במקום לחכות
    return spotipy.Spotify(auth=token_info["access_token"], language="he", retries=0, requests_timeout=10)


# כמה תמונות של אמנים ועטיפות לשים ברקע
BACKGROUND_IMAGES = 24


def image_url(images):
    """תמונה בגודל בינוני (ספוטיפיי מחזיר אותן מהגדולה לקטנה)."""
    if not images:
        return ""
    return images[min(1, len(images) - 1)]["url"]


def load_vibe(sp, uid):
    """הסגנון של המשתמש ותמונות לרקע, לפי האמנים והשירים שהוא הכי שומע."""
    artist_ranks, artist_objects = library.cached(uid, "top_artists", lambda: library.top_ranks(sp, "artists"))
    _, track_objects = library.cached(uid, "top_tracks", lambda: library.top_ranks(sp, "tracks"))
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
        # המפתח כולל גרסה, כדי שמטמון ישן בלי תמונות לפי סגנון לא ייטען
        return library.cached(uid, "vibe_v2", lambda: load_vibe(sp, uid))
    except Exception:
        return {"theme": "default", "images": []}


def page(body, title="פלייליסטור", wide=False, script="", theme=None, images=None):
    vibe = current_vibe()
    theme = theme or vibe["theme"]
    images = vibe["images"] if images is None else images
    user = session.get("user_name")
    user_html = (
        f'<span class="user">{escape(user)}<a href="/logout">התנתקות</a></span>' if user else ""
    )
    return (
        '<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}{themes.theme_css(theme)}</style></head><body>"
        + themes.background_html(images)
        + f'<div class="wrap{" wide" if wide else ""}">'
        f'<header><a class="logo" href="/">🎧 פלייליסטור</a>{user_html}</header>'
        + body
        + "</div>"
        + (f"<script>{script}</script>" if script else "")
        + "</body></html>"
    )


def options(values, selected=""):
    return "".join(
        f'<option value="{escape(v)}"{" selected" if v == selected else ""}>{escape(v)}</option>'
        for v in values
    )


def cover(url):
    return f'<img src="{escape(url)}" alt="" loading="lazy">' if url else '<div class="noimg"></div>'


def genre_options():
    groups = [("מוזיקה בעברית", HEBREW_GENRES), ("מוזיקה מהעולם", WORLD_GENRES)]
    return '<option value="">ללא</option>' + "".join(
        f'<optgroup label="{escape(label)}">'
        + "".join(f'<option value="{escape(term)}">{escape(name)}</option>' for name, term in genres)
        + "</optgroup>"
        for label, genres in groups
    )


GENRE_NAMES = {term: name for name, term in HEBREW_GENRES + WORLD_GENRES}


def liked_artist_tags(sp, uid, saved):
    """ז'אנרים ותגיות לכל אמן ברשימת השירים שאהבת, כדי לבנות ממנה פלייליסט לפי ז'אנר."""
    def load():
        _, top_objects = library.cached(uid, "top_artists", lambda: library.top_ranks(sp, "artists"))
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
    value = text if value is None else value
    cls_attr = f' class="{cls}"' if cls else ""
    return f'<td{cls_attr} data-v="{escape(str(value))}">{html or escape(str(text))}</td>'


def spotify_link(text, kind, item_id, inner_html=None):
    """קישור שפותח שיר, אלבום או אמן בספוטיפיי. בלי מזהה, רק הטקסט."""
    content = inner_html or escape(text)
    if not item_id:
        return content
    return (
        f'<a class="sp" href="https://open.spotify.com/{kind}/{escape(item_id)}"'
        f' target="_blank" rel="noopener">{content}</a>'
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
    return f"מקום {rank[0]} · {rank[1]}" if rank else ""


def track_row(track, checkbox=False, feat=None):
    check = (
        f'<input type="checkbox" name="uri" value="{escape(track["uri"])}" checked>' if checkbox else ""
    )
    # הנתונים מאפשרים מיון בדף, והתיאור מוצג ליד שם האמן
    attrs, info = "", ""
    if feat:
        attrs = f' data-bpm="{feat.get("tempo") or 0}" data-energy="{feat.get("energy") or 0}" data-valence="{feat.get("valence") or 0}"'
        info = describe(feat)
    return (
        f"<li{attrs}>{check}{spotify_link('', 'album', track.get('album_id'), cover(track.get('image', '')))}"
        f"<div class=\"info\"><div class=\"title\">{spotify_link(track['name'], 'track', track.get('id'))}</div>"
        f"<div class=\"sub\">{artist_links(track)}{(' · ' + escape(info)) if info else ''}</div></div></li>"
    )


@app.errorhandler(spotipy.SpotifyException)
def spotify_error(error):
    if error.http_status == 401:
        session.pop("token_info", None)
        return redirect("/login")
    if error.http_status == 429:
        return page("<p>ספוטיפיי קיבל יותר מדי בקשות. נסו שוב בעוד דקה.</p>"), 429
    return page("<p>ספוטיפיי החזיר שגיאה. נסו שוב בעוד כמה רגעים.</p>"), 502


@app.errorhandler(requests.RequestException)
def network_error(error):
    return page("<p>אין חיבור לספוטיפיי כרגע. בדקו את החיבור לאינטרנט ונסו שוב.</p>"), 503


def vibe_picker():
    """חלון הבחירה של העיצוב. ברירת המחדל אוטומטית, וכל סגנון זמין ידנית. השינוי משפיע על כל המסכים."""
    chosen = session.get("vibe_choice", "")
    options = '<option value="">אוטומטי (לפי מה שנשמע הכי הרבה)</option>' + "".join(
        f'<option value="{key}"{" selected" if key == chosen else ""}>{t["emoji"]} {t["label"]}</option>'
        for key, t in themes.THEMES.items()
    )
    return (
        '<form method="post" action="/vibe" class="card">'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        f'<label class="field">בחרו עיצוב<select name="vibe">{options}</select></label>'
        '<button class="btn secondary" type="submit">החל</button></form>'
    )


@app.route("/vibe", methods=["POST"])
def set_vibe():
    """שומר את העיצוב שנבחר. ריק או לא מוכר חוזר לאוטומטי."""
    choice = request.form.get("vibe", "")
    if choice in themes.THEMES:
        session["vibe_choice"] = choice
    else:
        session.pop("vibe_choice", None)
    return redirect("/")


def wants_favourites(sp):
    """האם להציג בדף הבית את כרטיס בחירת האמנים והשירים. אם ספוטיפיי לא עונה, לא מציגים אותו."""
    try:
        return favourites.needs_favourites(sp, user_id(sp))
    except (spotipy.SpotifyException, requests.RequestException):
        return False


def favourites_url(q=""):
    return "/favourites" + (f"?{urlencode({'q': q})}" if q else "")


def pick_form(action, item_id, q, label):
    """כפתור שמוסיף פריט לחשבון הספוטיפיי, ומחזיר לאותו חיפוש."""
    return (
        f'<form method="post" action="{action}">'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        f'<input type="hidden" name="id" value="{escape(item_id)}">'
        f'<input type="hidden" name="q" value="{escape(q)}">'
        f'<button class="btn" type="submit">{label}</button></form>'
    )


def artist_rows(artists, followed, q):
    if not artists:
        return '<p class="note">אין תוצאות להצגה.</p>'
    rows = []
    for artist in artists:
        if artist["id"] in followed:
            action = '<span class="note">✓ עוקב</span>'
        else:
            action = pick_form("/favourites/artist", artist["id"], q, "➕ עקוב")
        rows.append(
            f"<li>{cover(artist['image'])}"
            f'<div class="info"><div class="title">{spotify_link(artist["name"], "artist", artist["id"])}</div></div>'
            f"{action}</li>"
        )
    return f'<ul class="list">{"".join(rows)}</ul>'


def track_rows(tracks, saved, q):
    if not tracks:
        return '<p class="note">אין תוצאות להצגה.</p>'
    rows = []
    for track in tracks:
        if saved.get(track["id"]):
            action = '<span class="note">✓ שמור</span>'
        else:
            action = pick_form("/favourites/track", track["id"], q, "❤ שמור")
        rows.append(
            f"<li>{cover(track['image'])}"
            f'<div class="info"><div class="title">{spotify_link(track["name"], "track", track["id"])}</div>'
            f'<div class="sub">{artist_links(track)}</div></div>{action}</li>'
        )
    return f'<ul class="list">{"".join(rows)}</ul>'


@app.route("/favourites")
def favourites_page():
    """מסך בחירת אמנים ושירים אהובים, עם חיפוש והמלצות. הבחירות נשמרות בחשבון הספוטיפיי."""
    if session.get("scope") != SCOPE:
        # ההרשאות השתנו, ואי אפשר לשמור בלי להתחבר שוב
        session.pop("token_info", None)
        session["relogin"] = True
        return redirect("/login")
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")

    uid = user_id(sp)
    q = request.args.get("q", "").strip()[:100]
    followed = {a["id"] for a in favourites.followed_artists(sp, uid)}
    songs = favourites.saved_songs(sp, uid)
    body = (
        "<h1>אמנים ושירים שאתם אוהבים</h1>"
        '<p class="note">סמנו מה שאתם אוהבים, והבחירות יישמרו בחשבון הספוטיפיי שלכם: '
        "אמנים שתעקבו אחריהם, ושירים שתשמרו. לפיהם נמליץ לכם על שירים נוספים.</p>"
        + stat_boxes([("אמנים שאני עוקב אחריהם", len(followed)), ("שירים שמורים", songs)])
        + '<form method="get" action="/favourites" class="toolbar">'
        f'<label class="field">חיפוש<input type="text" name="q" value="{escape(q)}" placeholder="שם אמן או שיר"></label>'
        '<button class="btn secondary" type="submit">חיפוש</button></form>'
    )
    if q:
        artists, tracks = favourites.search(sp, q)
        saved = favourites.saved_flags(sp, [t["id"] for t in tracks])
        body += (
            "<h2>אמנים</h2>" + artist_rows(artists, followed, q)
            + "<h2>שירים</h2>" + track_rows(tracks, saved, q)
        )
    else:
        rec = favourites.recommendations(sp, uid)
        artists = [a for a in rec["artists"] if a["id"] not in followed]
        saved = favourites.saved_flags(sp, [t["id"] for t in rec["tracks"]])
        tracks = [t for t in rec["tracks"] if not saved.get(t["id"])]
        if rec["source"] == "well_known":
            heading = "זמרים מוכרים כדי להתחיל"
            note = "עדיין אין לכם אמנים או שירים אהובים, אז אלה זמרים מוכרים. סמנו מי שאתם אוהבים, ונמליץ על עוד לפי זה."
        else:
            heading = "המלצות בשבילכם"
            note = "אמנים דומים למה שאתם כבר אוהבים, ושירים מהם."
        body += (
            f'<h2>{heading}</h2><p class="note">{note}</p>'
            + artist_rows(artists, followed, "")
            + "<h2>שירים שאולי תאהבו</h2>"
            + track_rows(tracks, saved, "")
        )
    return page(body + '<p><a href="/">חזרה לדף הבית</a></p>', title="אמנים ושירים שאתם אוהבים")


@app.route("/favourites/artist", methods=["POST"])
def follow_artist():
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    artist_id = request.form.get("id", "")
    if favourites.is_spotify_id(artist_id):
        sp.user_follow_artists([artist_id])
        library.forget(user_id(sp), "followed")
    return redirect(favourites_url(request.form.get("q", "").strip()[:100]))


@app.route("/favourites/track", methods=["POST"])
def save_favourite_track():
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    track_id = request.form.get("id", "")
    if favourites.is_spotify_id(track_id):
        sp.current_user_saved_tracks_add([track_id])
        library.forget(user_id(sp), "saved", "saved_total")
    return redirect(favourites_url(request.form.get("q", "").strip()[:100]))


@app.route("/")
def home():
    if session.get("token_info") and session.get("scope") != SCOPE:
        # האפליקציה צריכה הרשאות חדשות (למשל רשימת האמנים שאתה עוקב אחריהם)
        session.pop("token_info", None)
        session["relogin"] = True
    if not session.get("token_info"):
        relogin = session.pop("relogin", False)
        return page(
            "<h1>פלייליסטים שמתאימים בדיוק לרגע</h1>"
            '<p class="note">בחרו ז\'אנר, מצב רוח ואירוע, ופלייליסטור יבנה לכם פלייליסט חדש בספוטיפיי.</p>'
            '<a class="btn" href="/login">התחברות עם ספוטיפיי</a>'
            + (RELOGIN_NOTE if relogin else "")
        )
    sp = get_spotify_client()
    onboarding_card = (
        '<a href="/favourites">🌟 בחרו אמנים ושירים שאתם אוהבים'
        '<small>ככה נוכל להמליץ לכם על שירים שמתאימים לטעם שלכם</small></a>'
        if sp is not None and wants_favourites(sp) else ""
    )
    vibe = themes.THEMES[current_vibe()["theme"]]
    auto = themes.THEMES[auto_vibe()["theme"]]
    return page(
        "<h1>מה נשמע היום?</h1>"
        f'<div class="vibe">{vibe["emoji"]} החוויה שלך: {escape(vibe["label"])}'
        f'<span class="note">· לפי מה שנשמע הכי הרבה: {escape(auto["label"])}</span></div>'
        + vibe_picker()
        + '<div class="menu">'
        + onboarding_card
        + '<a href="/build">✨ צור פלייליסט חדש<small>לפי ז\'אנר (גם בעברית), מצב רוח, אירוע ושפה, מכל ספוטיפיי או מהשירים שאהבתי</small></a>'
        '<a href="/saved-tracks">❤️ כל השירים שאהבתי<small>הרשימה המלאה, עם מיון לפי אמן, השמעות, תאריך ועוד</small></a>'
        '<a href="/my-artists">🎤 כל האמנים שאני אוהב<small>מי שאני עוקב אחריו, שומע הכי הרבה, או אוהב את השירים שלו</small></a>'
        "</div>"
        '<p class="note">הנתונים נשמרים לכמה שעות כדי שהאפליקציה תהיה מהירה. '
        '<a href="/refresh">רענון נתונים מספוטיפיי</a></p>'
    )


@app.route("/login")
def login():
    # מצב (state) אקראי שחוזר מספוטיפיי. בלעדיו אתר אחר יכול להתחבר בשם המשתמש לחשבון שלו
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return redirect(make_auth().get_authorize_url(state=state))


@app.route("/refresh")
def refresh():
    """טוען מחדש מספוטיפיי את השירים, האמנים והסגנון (למשל אחרי שאהבת שירים חדשים)."""
    if session.get("user_id"):
        library.clear_cache(session["user_id"])
    return redirect(request.referrer or "/")


@app.route("/logout")
def logout():
    if session.get("user_id"):
        library.clear_cache(session["user_id"])
    session.clear()
    return redirect("/")


@app.route("/callback")
def callback():
    code = request.args.get("code")
    expected_state = session.pop("oauth_state", None)
    if not code or not expected_state or request.args.get("state") != expected_state:
        return page("<p>ההתחברות בוטלה או נכשלה, או שהבקשה לא הגיעה מהאפליקציה. <a href=\"/login\">נסו שוב</a>.</p>"), 400

    try:
        token_info = make_auth().get_access_token(code, check_cache=False)
    except SpotifyOauthError:
        return page('<p>ההתחברות נכשלה. <a href="/login">נסו שוב</a>.</p>'), 400
    session["token_info"] = token_info
    sp = spotipy.Spotify(auth=token_info["access_token"])
    user = sp.current_user()
    session["user_name"] = user.get("display_name") or ""
    session["user_id"] = user["id"]
    session["scope"] = SCOPE
    return redirect("/")


@app.route("/saved-tracks")
def saved_tracks():
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")

    uid = user_id(sp)
    saved = library.cached(uid, "saved", lambda: library.all_saved_tracks(sp))
    track_ranks, _ = library.cached(uid, "top_tracks", lambda: library.top_ranks(sp, "tracks"))
    plays, _ = library.cached(uid, "lastfm", get_user_playcounts)

    tracks = []
    for item in saved:
        track = item["track"]
        result = to_result(track)
        result.update(
            album=track.get("album", {}).get("name", ""),
            added=item.get("added_at", "")[:10],
            duration=track.get("duration_ms") or 0,
            popularity=track.get("popularity"),
            rank=library.best_rank(track_ranks.get(track["id"])),
            plays=plays.get((track["artists"][0]["name"].lower(), track["name"].lower())) if plays else None,
        )
        tracks.append(result)

    columns = [("", None), ("", None), ("שיר", "text"), ("אמן", "text"), ("אלבום", "text"),
               ("נוסף בתאריך", "text"), ("אורך", "num"), ("פופולריות", "num"),
               ("הדירוג שלך", "num")]
    if plays is not None:
        columns.append(("השמעות (Last.fm)", "num"))
    rows = []
    for t in tracks:
        row = (
            f'<td><input type="checkbox" name="uri" value="{escape(t["uri"])}"></td>'
            f"<td>{spotify_link('', 'album', t['album_id'], cover(t['image']))}</td>"
            + cell(t["name"], cls="name", html=spotify_link(t["name"], "track", t["id"]))
            + cell(t["artist"], cls="name", html=artist_links(t))
            + cell(t["album"], cls="name muted", html=spotify_link(t["album"], "album", t["album_id"]))
            + cell(t["added"], cls="muted")
            + cell(format_duration(t["duration"]), t["duration"], "muted")
            + cell("" if t["popularity"] is None else t["popularity"], "" if t["popularity"] is None else t["popularity"])
            # בדירוג, מקום 1 הוא הכי טוב, ולכן ממיינים לפי מספר שלילי
            + cell(format_rank(t["rank"]), -t["rank"][0] if t["rank"] else "")
        )
        if plays is not None:
            row += cell("" if t["plays"] is None else t["plays"], "" if t["plays"] is None else t["plays"])
        rows.append(f"<tr>{row}</tr>")

    artists_count = len({a for t in tracks for a, _ in t["artists"]})
    total_hours = sum(t["duration"] for t in tracks) / 3_600_000
    note = (
        ""
        if plays is not None
        else '<p class="note">ספוטיפיי לא חושף כמה פעמים שמעת כל שיר. "הדירוג שלך" הוא המקום של השיר '
        "ב-50 השירים שאתה הכי שומע (ב-4 השבועות האחרונים, ב-6 החודשים האחרונים, או בכל הזמנים). "
        "למספר השמעות אמיתי, חבר את ספוטיפיי ל-Last.fm והוסף LASTFM_USER לקובץ .env.</p>"
    )
    return page(
        "<h1>כל השירים שאהבתי</h1>"
        + stat_boxes([("שירים", len(tracks)), ("אמנים", artists_count), ("שעות האזנה ברשימה", f"{total_hours:.1f}")])
        + note
        + '<input type="text" class="search" data-table="tracks" placeholder="חיפוש שיר, אמן או אלבום...">'
        + '<form method="post" action="/save">'
        + '<div class="toolbar">'
        + '<label class="field">שם לפלייליסט מהשירים שסימנתי'
        + '<input type="text" name="title" value="פלייליסטור - השירים שאהבתי" maxlength="100"></label>'
        + '<button type="button" class="btn secondary" data-check-visible="tracks">סמן את כל המוצגים</button>'
        + '<button type="submit" class="btn">צור פלייליסט מהמסומנים</button>'
        + "</div>"
        + '<p class="note">טיפ: חפשו אמן או אלבום, לחצו "סמן את כל המוצגים", ואז "צור פלייליסט". '
        + 'לפלייליסט לפי ז\'אנר או מצב רוח מתוך השירים שאהבתם, השתמשו ב<a href="/build">יצירת פלייליסט</a>.</p>'
        + f'<div class="table-wrap"><table id="tracks" class="sortable"><thead>{header(columns)}</thead>'
        + f'<tbody>{"".join(rows)}</tbody></table></div>'
        + "</form>",
        title="כל השירים שאהבתי", wide=True, script=TABLE_JS,
    )


@app.route("/my-artists")
def my_artists():
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")

    uid = user_id(sp)
    saved = library.cached(uid, "saved", lambda: library.all_saved_tracks(sp))
    followed = library.cached(uid, "followed", lambda: library.followed_artists(sp))
    artist_ranks, artist_objects = library.cached(uid, "top_artists", lambda: library.top_ranks(sp, "artists"))
    _, plays = library.cached(uid, "lastfm", get_user_playcounts)
    artists = library.collect_artists(saved, followed, artist_ranks, artist_objects)

    # תגיות מ-Last.fm רק לאמנים בלי ז'אנר מספוטיפיי שאתה עוקב אחריהם או שומע הרבה, כדי שהעמוד ייטען מהר
    need_tags = [a for a in artists if not a["genres"] and (a["followed"] or a["rank"])]
    for a, tags in zip(need_tags, get_tags_for_artists([a["name"] for a in need_tags])):
        a["genres"] = tags


    columns = [("", None), ("אמן", "text"), ("שירים שאהבתי", "num"), ("עוקב", "num"),
               ("הדירוג שלך", "num"), ("ז'אנרים", "text")]
    if plays is not None:
        columns.append(("השמעות (Last.fm)", "num"))
    artists.sort(key=lambda a: (a["rank"][0] if a["rank"] else 999, -a["liked"]))
    rows = []
    for a in artists:
        play_count = plays.get(a["name"].lower()) if plays else None
        row = (
            f"<td>{spotify_link('', 'artist', a['id'], cover(a['image']))}</td>"
            + cell(a["name"], cls="name", html=spotify_link(a["name"], "artist", a["id"]))
            + cell(a["liked"])
            + cell("✓" if a["followed"] else "", 1 if a["followed"] else 0)
            + cell(format_rank(a["rank"]), -a["rank"][0] if a["rank"] else "")
            + cell(", ".join(a["genres"][:3]), cls="name muted")
        )
        if plays is not None:
            row += cell("" if play_count is None else play_count, "" if play_count is None else play_count)
        rows.append(f"<tr>{row}</tr>")

    return page(
        "<h1>כל האמנים שאני אוהב</h1>"
        + stat_boxes([
            ("אמנים", len(artists)),
            ("אני עוקב אחריהם", sum(a["followed"] for a in artists)),
            ("בין המובילים שלי", sum(1 for a in artists if a["rank"])),
        ])
        + '<input type="text" class="search" data-table="artists" placeholder="חיפוש אמן או ז\'אנר...">'
        + f'<div class="table-wrap"><table id="artists" class="sortable"><thead>{header(columns)}</thead>'
        + f'<tbody>{"".join(rows)}</tbody></table></div>',
        title="כל האמנים שאני אוהב", wide=True, script=TABLE_JS,
    )


def _percent(value):
    try:
        return min(max(int(value), 0), 100)
    except (TypeError, ValueError):
        return None


def read_ranges():
    """טווחים ידניים מהטופס, באחוזים מ-0 עד 100. None אם לא סומן כוונון ידני."""
    if "manual" not in request.form:
        return None
    ranges = {}
    for key in ("energy", "danceability", "valence"):
        low, high = _percent(request.form.get(f"{key}_min")), _percent(request.form.get(f"{key}_max"))
        if low is None or high is None or low > high or (low == 0 and high == 100):
            continue
        ranges[key] = (low / 100 if low > 0 else None, high / 100 if high < 100 else None)
    return ranges or None


@app.route("/build", methods=["GET", "POST"])
def build():
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")

    if request.method == "GET":
        return page(
            "<h1>צור פלייליסט</h1>"
            '<form method="post" class="card">'
            f'<input type="hidden" name="csrf" value="{csrf_token()}">'
            '<label class="field">מאיפה לקחת שירים<select name="source">'
            '<option value="search">מכל ספוטיפיי</option>'
            '<option value="liked">רק מהשירים שאהבתי</option></select></label>'
            f'<label class="field">ז\'אנר<select name="genre_choice">{genre_options()}</select></label>'
            '<label class="field">או ז\'אנר אחר (באנגלית, למשל: reggaeton, afrobeats)'
            '<input type="text" name="genre" placeholder="לא חובה"></label>'
            '<label class="field">מצב רוח<select name="mood"><option value="">ללא</option>'
            + options(GENRE_HINTS.keys())
            + "</select></label>"
            '<label class="field">אירוע או סיטואציה<select name="event"><option value="">ללא</option>'
            + "".join(
                f'<optgroup label="{escape(group)}">{options(events.keys())}</optgroup>'
                for group, events in EVENT_GROUPS.items()
            )
            + "</select></label>"
            '<label class="field">שפה<select name="language">'
            + options(LANGUAGES)
            + "</select></label>"
            f'<label class="field">כמות שירים (5 עד {MAX_TRACKS})'
            f'<input name="count" type="number" value="20" min="5" max="{MAX_TRACKS}"></label>'
            '<label class="check"><input type="checkbox" name="personal" checked> שלב שירים של האמנים המועדפים עליי</label>'
            '<details class="card"><summary>כוונון ידני (אופציונלי)</summary>'
            '<label class="check"><input type="checkbox" name="manual"> להשתמש בטווחים שאני קובע, במקום ברירת המחדל לפי מצב הרוח והאירוע</label>'
            + "".join(
                f'<label class="field">{label}: <output id="out-{key}">0% עד 100%</output>'
                f'<input type="range" name="{key}_min" min="0" max="100" value="0">'
                f'<input type="range" name="{key}_max" min="0" max="100" value="100"></label>'
                for key, label in (("energy", "אנרגיה"), ("danceability", "ריקוד"), ("valence", "שמחה"))
            )
            + "</details>"
            '<button class="btn" type="submit">הצג שירים</button>'
            "</form>",
            script=RANGE_JS,
        )

    # קלט מהטופס: מגבילים אורך, ומקבלים רק ערכים מהתפריטים
    genre = (request.form.get("genre", "").strip() or request.form.get("genre_choice", ""))[:60]
    source = "liked" if request.form.get("source") == "liked" else "search"
    mood = request.form.get("mood", "")
    mood = mood if mood in GENRE_HINTS else ""
    event = request.form.get("event", "")
    event = event if event in EVENT_HINTS else ""
    language = request.form.get("language", "ביחד")
    language = language if language in LANGUAGES else "ביחד"
    try:
        count = min(max(int(request.form.get("count", 20)), 5), MAX_TRACKS)
    except ValueError:
        count = 20
    personal = "personal" in request.form
    ranges = read_ranges()
    # ז'אנר ישראלי מחפש שירים בעברית, אלא אם בחרת שפה אחרת במפורש
    if language == "ביחד" and (genre.startswith("israeli") or genre == "mizrahi"):
        language = "עברית"

    if source == "liked":
        uid = user_id(sp)
        saved = library.cached(uid, "saved", lambda: library.all_saved_tracks(sp))
        tags = liked_artist_tags(sp, uid, saved)
        tracks = find_liked_tracks(saved, tags, genre, mood, event, language, count, ranges)
    else:
        tracks = find_tracks(sp, genre, mood, event, language, count, personal=personal, ranges=ranges)
    if not tracks:
        return page('<p>לא נמצאו שירים. <a href="/build">נסו שילוב אחר</a>.</p>')

    # תצוגה מקדימה: מורידים את מה שלא מתאים, ורק אז שומרים בספוטיפיי
    # שם שמתאים לאווירה, ועוד כמה הצעות לכפתור "שם אחר"
    names = suggest_names(genre, mood, event, GENRE_NAMES.get(genre, genre), from_liked=source == "liked")
    title = names[0]
    feats = get_features([t["id"] for t in tracks if t.get("id")])
    rows = "".join(track_row(t, checkbox=True, feat=feats.get(t.get("id"))) for t in tracks)
    theme = themes.theme_for_choice(genre, mood, event)
    covers = list(dict.fromkeys(t["image"] for t in tracks if t["image"]))[:BACKGROUND_IMAGES]
    return page(
        f"<h1>{len(tracks)} שירים בשבילך</h1>"
        '<p class="note">בטלו את הסימון בשירים שלא מתאימים, ואז שמרו.</p>'
        '<form method="post" action="/save">'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        f'<input type="hidden" name="theme" value="{escape(theme or "")}">'
        '<div class="toolbar">'
        f'<label class="field">שם הפלייליסט<input type="text" id="title" name="title" value="{escape(title)}" maxlength="100"></label>'
        f'<button type="button" class="btn secondary" id="other-name" data-names="{escape(json.dumps(names, ensure_ascii=False))}">🔄 שם אחר</button>'
        "</div>"
        '<div class="toolbar">'
        '<label class="field">מיון<select id="sort">'
        '<option value="">הסדר המקורי</option><option value="bpm">קצב (BPM)</option>'
        '<option value="energy">אנרגיה</option><option value="valence">שמחה</option></select></label>'
        '<button type="button" class="btn secondary" id="shuffle">🔀 ערבב</button></div>'
        f'<ul class="list">{rows}</ul><br>'
        '<button class="btn" type="submit">שמור בספוטיפיי</button>'
        "</form>"
        '<p><a href="/build">התחלה מחדש</a></p>',
        theme=theme, images=covers or None, script=NAME_JS + SORT_JS,
    )


@app.route("/save", methods=["POST"])
def save():
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")

    uris = [u for u in request.form.getlist("uri") if u.startswith("spotify:track:")][:MAX_SAVE]
    if not uris:
        return page('<p>לא נבחרו שירים. <a href="/build">חזרה ליצירת פלייליסט</a>.</p>')
    title = request.form.get("title", "").strip()[:100] or "פלייליסטור - מיקס"
    url = create_playlist(sp, title, uris)
    theme = request.form.get("theme")
    return page(
        f'<div class="success"><h1>הפלייליסט נשמר! 🎉</h1><p>{escape(title)}, {len(uris)} שירים.</p>'
        f'<a class="btn" href="{escape(url)}" target="_blank" rel="noopener">פתיחה בספוטיפיי</a></div>'
        '<p><a href="/build">ליצירת פלייליסט נוסף</a></p>',
        theme=theme if theme in themes.THEMES else None,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG") == "1")
