import os
import secrets
import time
from collections import Counter
from html import escape
from flask import Flask, g, has_request_context, redirect, request, session
from dotenv import load_dotenv
import requests
import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth, SpotifyOauthError
from lastfm import get_tags_for_artists, get_user_playcounts
import library
import ratelimit
import themes
import favourites
import json
from urllib.parse import urlencode, urlsplit
from playlist_names import suggest_names
from previews import preview_url
from concurrent.futures import ThreadPoolExecutor
from engine import (
    GENRE_HINTS, EVENT_HINTS, EVENT_GROUPS, LANGUAGES, HEBREW_GENRES, WORLD_GENRES,
    find_tracks, find_liked_tracks, create_playlist, to_result, album_year, PLAYLIST_DESCRIPTION,
)
from vibes import describe, get_features

load_dotenv()

app = Flask(__name__)
# בלי FLASK_SECRET ב-.env נוצר מפתח אקראי, וההתחברות תתאפס בכל הפעלה מחדש של השרת
app.secret_key = os.getenv("FLASK_SECRET") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
# כשהאפליקציה נגישה דרך https (למשל כתובת קבועה לחברים), הקוקי נשלח רק ב-https
PUBLIC_HTTPS = (os.getenv("SPOTIFY_REDIRECT_URI") or "").startswith("https://")
app.config["SESSION_COOKIE_SECURE"] = PUBLIC_HTTPS
if not os.getenv("FLASK_SECRET"):
    print("[פלייליסטור] אין FLASK_SECRET ב-.env, ולכן כל הפעלה מחדש של השרת מנתקת את כולם")


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


# כמה בקשות לכתובת אחת. הפעולות שעולות לספוטיפיי מוגבלות חזק, מה שנשאר מוגבל בעדינות
RATE_LIMITS = {
    ("POST", "/build"): ("build", 20, 60),
    ("POST", "/build/more"): ("build", 20, 60),
    ("POST", "/save"): ("save", 10, 60),
    ("GET", "/login"): ("login", 20, 600),
    ("GET", "/callback"): ("login", 20, 600),
}
DEFAULT_LIMIT = ("all", 300, 60)


@app.before_request
def check_rate_limit():
    ip = ratelimit.client_ip(request.remote_addr, request.headers.get("X-Forwarded-For"))
    bucket, limit, window = RATE_LIMITS.get((request.method, request.path), DEFAULT_LIMIT)
    if not ratelimit.allow(bucket, ip, limit, window):
        return (
            '<!doctype html><meta charset="utf-8"><p dir="rtl">יותר מדי בקשות מהמכשיר הזה. נסו שוב בעוד כמה דקות.</p>',
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

STYLE = """
:root {
  --bg: #111216; --card: rgba(22, 23, 29, .84); --card-hover: rgba(44, 46, 56, .9); --text: #f4f4f6;
  --muted: #c9cad3; --soft: #a3a5b1; --border: rgba(255, 255, 255, .12); --field: #1b1c22;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text); min-height: 100vh;
  font-family: "Segoe UI", "Heebo", "Rubik", Arial, sans-serif; font-size: 17px; line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 680px; margin: 0 auto; padding: 18px 16px 56px; }
header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.brand { flex-wrap: wrap; }
header a.logo { color: var(--text); text-decoration: none; font-size: 23px; font-weight: 700; white-space: nowrap; }
header .user { color: var(--muted); font-size: 15px; }
header .user a { color: var(--muted); margin-inline-start: 8px; display: inline-flex; align-items: center; min-height: 40px; }
h1 { font-size: 30px; line-height: 1.25; margin: 6px 0 18px; font-weight: 700; }
h1, h2 { text-shadow: 0 2px 14px rgba(0, 0, 0, .55); }
h2 { font-size: 21px; line-height: 1.3; margin: 30px 0 12px; font-weight: 700; }
a { color: var(--accent); }
.menu { display: grid; gap: 12px; }
.menu a {
  display: block; background: var(--card); color: var(--text); text-decoration: none;
  padding: 18px 20px; border-radius: 16px; font-size: 18px; font-weight: 600;
  border: 1px solid var(--border); transition: background .15s, border-color .15s;
}
.menu a:hover { background: var(--card-hover); border-color: var(--accent); }
.menu a small { display: block; color: var(--muted); font-size: 15px; font-weight: 400; margin-top: 2px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 20px; margin-bottom: 16px; }
.menu a, .card, .list li, .stats div, .table-wrap, .vibe {
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
}
.vibe {
  display: flex; align-items: center; gap: 14px; margin-bottom: 20px; padding: 14px 18px;
  border-radius: 16px; background: var(--card); border: 1px solid var(--border);
  border-inline-start: 4px solid var(--accent);
}
.vibe-emoji { font-size: 30px; line-height: 1; flex: none; }
.vibe-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.vibe-text b { font-size: 18px; }
.vibe-text span { color: var(--muted); font-size: 15px; }
label.field { display: block; margin-bottom: 18px; color: var(--text); font-size: 16px; font-weight: 600; }
label.field .hint { display: block; color: var(--soft); font-size: 14px; font-weight: 400; }
.req { color: var(--accent); margin-inline-start: 3px; }
input[type=text], input[type=number], select {
  display: block; width: 100%; margin-top: 6px; padding: 11px 13px; font-size: 16px; font-family: inherit;
  background: var(--field); color: var(--text); border: 1px solid var(--border); border-radius: 10px;
}
input[type=text]:focus, input[type=number]:focus, select:focus { border-color: var(--accent); }
input::placeholder { color: var(--soft); }
fieldset.group { border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px 2px; margin: 0 0 18px; }
fieldset.group legend { padding: 0 6px; font-weight: 700; font-size: 16px; }
fieldset.group.invalid { border-color: #f19a8b; }
.form-error {
  background: rgba(241, 154, 139, .14); border: 1px solid #f19a8b; color: #ffd9d2;
  border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; font-size: 15px;
}
label.check { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; font-size: 16px; }
label.check input { width: 20px; height: 20px; accent-color: var(--accent); flex: none; }
details.card summary { cursor: pointer; font-weight: 600; }
.btn {
  display: inline-block; width: 100%; padding: 14px; border: 0; border-radius: 999px;
  background: var(--accent); color: var(--on-accent); font-size: 17px; font-weight: 700; font-family: inherit;
  text-align: center; text-decoration: none; cursor: pointer; transition: filter .15s;
}
.btn:hover { filter: brightness(1.08); }
.list { list-style: none; padding: 0; margin: 0; }
.list li {
  display: flex; align-items: center; gap: 12px; padding: 10px;
  border-radius: 12px; background: var(--card); margin-bottom: 6px;
}
.list img, .list .noimg { width: 50px; height: 50px; border-radius: 6px; flex: none; background: var(--border); }
.list .info { min-width: 0; flex: 1; }
.list .title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
.list .sub { color: var(--muted); font-size: 15px; }
.list input[type=checkbox] { width: 20px; height: 20px; accent-color: var(--accent); flex: none; }
.note { color: var(--muted); font-size: 15px; text-shadow: 0 1px 6px rgba(0, 0, 0, .45); }
.success {
  background: rgba(46, 125, 84, .35); border: 1px solid rgba(110, 231, 160, .4);
  border-radius: 16px; padding: 20px; margin-bottom: 16px;
}
.wide { max-width: 1180px; }
.stats { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
.stats div { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 14px 18px; flex: 1; min-width: 130px; }
.stats b { display: block; font-size: 26px; line-height: 1.2; }
.stats span { color: var(--muted); font-size: 14px; }
input.search { margin-bottom: 12px; }
.table-wrap { overflow-x: auto; border-radius: 16px; background: var(--card); border: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 7px 8px; text-align: start; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: 13px; cursor: pointer; user-select: none; position: sticky; top: 0; background: #1b1c22; }
th:hover { color: var(--text); }
th.asc::after { content: " ▲"; } th.desc::after { content: " ▼"; }
td img, td .noimg { width: 34px; height: 34px; border-radius: 4px; display: block; background: var(--border); }
td.name { max-width: 190px; overflow: hidden; text-overflow: ellipsis; }
td.short { max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
td.muted { color: var(--muted); }
tr:hover td { background: var(--card-hover); }
td input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--accent); }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: end; margin-bottom: 12px; }
.toolbar label.field { flex: 1; min-width: 200px; margin: 0; }
.toolbar .btn { width: auto; padding: 11px 20px; font-size: 15px; }
.btn.secondary { background: var(--card); color: var(--text); border: 1px solid var(--border); }
.btn.secondary:hover { border-color: var(--accent); }
a.sp { color: inherit; text-decoration: none; }
a.sp:hover { color: var(--accent); text-decoration: underline; }
.list form { margin: 0; flex: none; }
.list .btn { width: auto; padding: 8px 14px; font-size: 14px; white-space: nowrap; }
.brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
.vibe-switch { margin: 0; }
.vibe-switch select {
  display: block; width: auto; max-width: 140px; margin: 0; padding: 6px 10px; font-size: 14px;
  border-radius: 999px;
}
.vibe-switch .btn { width: auto; padding: 5px 10px; font-size: 13px; }
.warn {
  background: rgba(244, 197, 106, .14); border: 1px solid rgba(244, 197, 106, .45); color: #ffeac2;
  border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; font-size: 15px;
}
.moves { display: inline-flex; flex-direction: column; gap: 2px; flex: none; }
.list .move, .play {
  width: auto; min-width: 40px; min-height: 32px; padding: 2px 10px; font-size: 15px; line-height: 1.4; border-radius: 999px;
  background: var(--card-hover); color: var(--text); border: 1px solid var(--border); cursor: pointer; font-family: inherit;
}
.play { min-width: 44px; min-height: 44px; padding: 6px 10px; font-size: 16px; flex: none; }
td .play { min-width: 34px; min-height: 34px; padding: 2px 8px; font-size: 13px; }
.play.playing { background: var(--accent); color: var(--on-accent); }
.play.loading { opacity: .6; cursor: progress; }
.play.none { opacity: .35; cursor: default; }
.bars { display: grid; gap: 9px; margin-bottom: 8px; }
.bar-row { display: grid; grid-template-columns: minmax(90px, 160px) 1fr 48px; gap: 12px; align-items: center; font-size: 15px; }
.bar-row .track { display: block; background: var(--border); border-radius: 999px; height: 12px; overflow: hidden; }
.bar-row .fill { display: block; background: var(--accent); height: 100%; border-radius: 999px; opacity: .85; }
.bar-row .num { color: var(--muted); text-align: end; }
.share { display: grid; grid-template-columns: minmax(0, 380px) minmax(0, 1fr); gap: 24px; align-items: start; }
@media (max-width: 760px) { .share { grid-template-columns: 1fr; } }
.share-svg { display: block; width: 100%; max-width: 380px; height: auto; border-radius: 20px; box-shadow: 0 12px 40px rgba(0, 0, 0, .5); }
.share .toolbar .btn { flex: 1; min-width: 140px; }
textarea.copy {
  width: 100%; min-height: 200px; margin: 0 0 12px; padding: 12px 14px; font-size: 15px; line-height: 1.7; font-family: inherit;
  background: var(--field); color: var(--text); border: 1px solid var(--border); border-radius: 12px; resize: vertical;
}
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

# מיון התצוגה המקדימה לפי שם, אמן, אורך, שנה, BPM, אנרגיה או שמחה. מעבירים שירים למעלה ולמטה, ומערבבים
# כל קטע עטוף בפונקציה, כדי שהמשתנים לא יתנגשו עם קטעי JavaScript אחרים בעמוד
SORT_JS = """
(function () {
  var list = document.getElementById("playlist"), sortSelect = document.getElementById("sort");
  var shuffleButton = document.getElementById("shuffle");
  // סוג המיון לכל שדה: טקסט, מספר שעולה, או מספר שיורד
  var sortKinds = { name: "text", artist: "text", duration: "asc", year: "asc", bpm: "desc", energy: "desc", valence: "desc" };
  function number(value, kind) {
    var n = parseFloat(value);
    if (!isNaN(n)) return n;
    return kind === "asc" ? Infinity : -Infinity;
  }
  if (!list) return;
  var originalOrder = Array.from(list.children);
  if (sortSelect) {
    sortSelect.addEventListener("change", function () {
      var key = sortSelect.value, kind = sortKinds[key];
      var items = key ? Array.from(list.children).sort(function (a, b) {
        var x = a.dataset[key] || "", y = b.dataset[key] || "";
        if (kind === "text") return x.localeCompare(y, "he");
        var nx = number(x, kind), ny = number(y, kind);
        if (nx === ny) return 0;
        return (kind === "asc" ? nx < ny : nx > ny) ? -1 : 1;
      }) : originalOrder;
      items.forEach(function (li) { list.appendChild(li); });
    });
  }
  list.addEventListener("click", function (event) {
    var button = event.target.closest(".move");
    if (!button) return;
    var li = button.closest("li"), dir = Number(button.dataset.dir);
    if (dir < 0 && li.previousElementSibling) list.insertBefore(li, li.previousElementSibling);
    if (dir > 0 && li.nextElementSibling) list.insertBefore(li.nextElementSibling, li);
    if (sortSelect) sortSelect.value = "";
  });
  if (shuffleButton) {
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
})();
"""

# השמעה של קטע של 30 שניות. נטען מ-Deezer רק כשלוחצים, וקטע אחד מתנגן בכל פעם
# השמעת 30 השניות הראשונות. הכתובת כבר בשורה של השיר, אז אין בקשה נוספת בלחיצה
PLAY_JS = """
(function () {
  var list = document.getElementById("playlist");
  if (!list) return;
  var player = new Audio(), playingButton = null;
  function stop() {
    player.pause();
    if (playingButton) {
      playingButton.classList.remove("playing");
      playingButton.setAttribute("aria-pressed", "false");
      playingButton.textContent = "▶";
    }
    playingButton = null;
  }
  player.addEventListener("ended", stop);
  list.addEventListener("click", function (event) {
    var button = event.target.closest(".play");
    if (!button) return;
    if (playingButton === button) { stop(); return; }
    stop();
    player.src = button.dataset.src;
    playingButton = button;
    button.classList.add("playing");
    button.setAttribute("aria-pressed", "true");
    button.textContent = "⏸";
    player.play().catch(stop);
  });
})();
"""

# כפתור ▶ בטבלת השירים שאהבת. הכתובת נטענת מהשרת רק בלחיצה, כי יש מאות שירים בטבלה
LAZY_PLAY_JS = """
(function () {
  var player = new Audio(), playingButton = null;
  function stop() {
    player.pause();
    if (playingButton) {
      playingButton.classList.remove("playing");
      playingButton.setAttribute("aria-pressed", "false");
      playingButton.textContent = "▶";
    }
    playingButton = null;
  }
  function start(button, url) {
    stop();
    player.src = url;
    playingButton = button;
    button.classList.add("playing");
    button.setAttribute("aria-pressed", "true");
    button.textContent = "⏸";
    player.play().catch(stop);
  }
  player.addEventListener("ended", stop);
  document.addEventListener("click", function (event) {
    var button = event.target.closest("td .play");
    if (!button || button.classList.contains("none") || button.classList.contains("loading")) return;
    if (playingButton === button) { stop(); return; }
    if (button.dataset.src) { start(button, button.dataset.src); return; }
    button.classList.add("loading");
    var query = new URLSearchParams({ artist: button.dataset.artist, title: button.dataset.title });
    fetch("/preview?" + query).then(function (r) { return r.json(); }).then(function (data) {
      button.classList.remove("loading");
      if (!data.url) {
        button.classList.add("none");
        button.textContent = "–";
        button.title = "לא נמצא קטע לשיר הזה";
        button.setAttribute("aria-label", "לא נמצא קטע לשיר הזה");
        return;
      }
      button.dataset.src = data.url;
      start(button, data.url);
    }).catch(function () { button.classList.remove("loading"); });
  });
})();
"""

# העתקת כרטיס השיתוף של הסטטיסטיקות
COPY_JS = """
(function () {
  var copyButton = document.getElementById("copy-card"), box = document.getElementById("card-text");
  if (!copyButton || !box) return;
  copyButton.addEventListener("click", function () {
    box.select();
    function done() { copyButton.textContent = "✅ הועתק"; }
    if (navigator.clipboard) { navigator.clipboard.writeText(box.value).then(done); }
    else { document.execCommand("copy"); done(); }
  });
})();
"""

# כרטיס השיתוף הוא SVG. מציירים אותו על קנבס בגודל המלא שלו ומורידים כ-PNG, או משתפים (בטלפון: סטורי, וואטסאפ)
SAVE_CARD_JS = """
(function () {
  var saveButton = document.getElementById("save-card"), shareButton = document.getElementById("share-card");
  var svg = document.getElementById("card-svg"), box = document.getElementById("card-text");
  if (!saveButton || !svg) return;
  var width = Number(svg.getAttribute("width")), height = Number(svg.getAttribute("height"));
  function makePng(done) {
    var source = new XMLSerializer().serializeToString(svg);
    var svgUrl = URL.createObjectURL(new Blob([source], { type: "image/svg+xml;charset=utf-8" }));
    var image = new Image();
    image.onload = function () {
      var canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d").drawImage(image, 0, 0, width, height);
      URL.revokeObjectURL(svgUrl);
      canvas.toBlob(done, "image/png");
    };
    image.src = svgUrl;
  }
  saveButton.addEventListener("click", function () {
    makePng(function (png) {
      var link = document.createElement("a");
      link.href = URL.createObjectURL(png);
      link.download = "playlistor-card.png";
      document.body.appendChild(link);
      link.click();
      link.remove();
    });
  });
  // שיתוף עם התמונה, רק בדפדפנים שתומכים בשיתוף קבצים (בעיקר בטלפון)
  var probe = new File([""], "card.png", { type: "image/png" });
  if (shareButton && navigator.canShare && navigator.canShare({ files: [probe] })) {
    shareButton.hidden = false;
    shareButton.addEventListener("click", function () {
      makePng(function (png) {
        var file = new File([png], "playlistor-card.png", { type: "image/png" });
        navigator.share({ files: [file], text: box ? box.value : "" }).catch(function () {});
      });
    });
  }
})();
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

# בדיקה לפני שליחה: לפחות ז'אנר, מצב רוח או אירוע. השרת בודק שוב (ראו build)
BUILD_CHECK_JS = """
(function () {
  var form = document.getElementById("build-form"), box = document.getElementById("build-error");
  var group = document.getElementById("must-pick");
  if (!form) return;
  form.addEventListener("submit", function (event) {
    var picked = ["genre_choice", "genre", "mood", "event"].some(function (name) {
      return form.elements[name].value.trim() !== "";
    });
    if (picked) return;
    event.preventDefault();
    box.textContent = __MESSAGE__;
    box.hidden = false;
    group.classList.add("invalid");
    group.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  group.addEventListener("change", function () { group.classList.remove("invalid"); box.hidden = true; });
})();
"""

TABLE_JS = """
document.querySelectorAll("table.sortable").forEach(function (table) {
  var body = table.tBodies[0];
  table.querySelectorAll("th[data-type]").forEach(function (th, col) {
    th.tabIndex = 0;
    th.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); th.click(); }
    });
    th.addEventListener("click", function () {
      var desc = !th.classList.contains("desc");
      table.querySelectorAll("th").forEach(function (h) { h.classList.remove("asc", "desc"); h.removeAttribute("aria-sort"); });
      th.classList.add(desc ? "desc" : "asc");
      th.setAttribute("aria-sort", desc ? "descending" : "ascending");
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


# זמרים ישראלים שאוהבים, לרקע מסך ההתחברות: תמונה של כל אחד ועטיפות של השירים שלו
ISRAELI_SINGERS = [
    "עומר אדם", "נועה קירל", "אייל גולן", "שרית חדד", "עדן בן זקן", "קרן פלס", "סטטיק ובן אל",
    "שלומי שבת", "רביד פלוטניק", "עידן רייכל", "עדן חסון", "אביב גפן", "מוש בן ארי", "אריק איינשטיין",
]
LOGIN_SECONDS = 6 * 60 * 60
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


def page(body, title="פלייליסטור", wide=False, script="", theme=None, images=None):
    # כשספוטיפיי מוגבל, לא מבקשים ממנו עוד נתונים בשביל העיצוב
    limited = time.time() < _limit["until"]
    vibe = {"theme": "default", "images": []} if limited else current_vibe()
    theme = theme or vibe["theme"]
    images = vibe["images"] if images is None else images
    user = session.get("user_name")
    user_html = (
        f'<span class="user">{escape(user)}<a href="/logout">התנתקות</a></span>' if user else ""
    )
    switch = vibe_switch() if session.get("token_info") else ""
    return (
        '<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}{themes.theme_css(theme)}</style></head><body>"
        + themes.background_html(images, theme)
        + f'<main class="wrap{" wide" if wide else ""}">'
        f'<header><div class="brand">{switch}<a class="logo" href="/">🎧 פלייליסטור</a></div>{user_html}</header>'
        + notices()
        + body
        + "</main>"
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
    groups = [("מוזיקה בעברית", HEBREW_GENRES)]
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
    # קישור שיש בו רק תמונה, למשל עטיפת אלבום, צריך שם שהקורא מסך יכול להקריא
    name = "" if text else ' aria-label="פתיחה בספוטיפיי"'
    return (
        f'<a class="sp" href="https://open.spotify.com/{kind}/{escape(item_id)}"'
        f' target="_blank" rel="noopener"{name}>{content}</a>'
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
    return f"#{rank[0]} · {rank[1]}" if rank else ""


PREVIEW_WORKERS = 8


def preview_links(tracks):
    """כתובת הקטע של כל שיר שיש לו קטע, לפי uri. שיר בלי קטע לא מקבל כפתור ▶."""
    def lookup(track):
        first_artist = track["artists"][0][1] if track.get("artists") else track["artist"]
        return track["uri"], preview_url(first_artist, track["name"])

    with ThreadPoolExecutor(max_workers=PREVIEW_WORKERS) as pool:
        return {uri: url for uri, url in pool.map(lookup, tracks) if url}


def track_row(track, checkbox=False, feat=None, preview=""):
    check = (
        f'<input type="checkbox" name="uri" value="{escape(track["uri"])}" '
        f'aria-label="לכלול את {escape(track["name"])}" checked>' if checkbox else ""
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
        info = describe(feat)
    play = (
        f'<button type="button" class="play" data-src="{escape(preview)}" aria-pressed="false" '
        'aria-label="השמעת 30 השניות הראשונות של השיר">▶</button>'
    ) if preview else ""
    moves = (
        '<span class="moves">'
        '<button type="button" class="move" data-dir="-1" aria-label="העברה למעלה">▲</button>'
        '<button type="button" class="move" data-dir="1" aria-label="העברה למטה">▼</button></span>'
    )
    return (
        f"<li{attrs}>{check}{spotify_link('', 'album', track.get('album_id'), cover(track.get('image', '')))}"
        f"<div class=\"info\"><div class=\"title\">{spotify_link(track['name'], 'track', track.get('id'))}</div>"
        f"<div class=\"sub\">{artist_links(track)}{(' · ' + escape(info)) if info else ''}</div></div>"
        f"{play}{moves}</li>"
    )


# ספוטיפיי מגביל את האפליקציה כולה. כשהוא עונה "יותר מדי בקשות", זוכרים עד מתי, ומציגים את השעה לכולם
_limit = {"until": 0.0}


def retry_after(error):
    """כמה שניות ספוטיפיי מבקש להמתין. בלי מספר, דקה. לא יותר משש שעות."""
    try:
        return min(max(int((error.headers or {}).get("Retry-After", 60)), 1), 6 * 60 * 60)
    except (TypeError, ValueError):
        return 60


def remember_limit(error):
    _limit["until"] = max(_limit["until"], time.time() + retry_after(error))


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
    if time.time() < _limit["until"]:
        until = clock(_limit["until"])
        notes.append(
            f"ספוטיפיי הגביל את הבקשות לזמן מה. אפשר לנסות שוב אחרי {until}. "
            "עד אז מוצגים הנתונים שנשמרו בפעם האחרונה, כשיש כאלה."
        )
    since = getattr(g, "stale_since", None) if has_request_context() else None
    if since is not None:
        when = clock(since)
        notes.append(f"חלק מהנתונים מ-{when}, כי ספוטיפיי לא ענה. הם יתעדכנו כשהוא יחזור.")
    return "".join(f'<div class="warn">{escape(note)}</div>' for note in notes)


@app.errorhandler(spotipy.SpotifyException)
def spotify_error(error):
    if error.http_status == 401:
        session.pop("token_info", None)
        return redirect("/login")
    if error.http_status == 429:
        remember_limit(error)
        # ההודעה עם השעה מופיעה מעל העמוד (notices), כאן רק מה שקרה
        return page("<p>לא הצלחנו לטעון את העמוד כרגע. אפשר לחזור לדף הבית ולנסות שוב אחרי ההמתנה.</p>"), 429
    return page("<p>ספוטיפיי החזיר שגיאה. נסו שוב בעוד כמה רגעים.</p>"), 502


@app.errorhandler(requests.RequestException)
def network_error(error):
    return page("<p>אין חיבור לספוטיפיי כרגע. בדקו את החיבור לאינטרנט ונסו שוב.</p>"), 503


def vibe_switch():
    """בחירת העיצוב, קטנה, בפינה הימנית למעלה בכל המסכים. ברירת המחדל אוטומטית, והבחירה משנה הכול."""
    chosen = session.get("vibe_choice", "")
    options = '<option value="">אוטומטי</option>' + "".join(
        f'<option value="{key}"{" selected" if key == chosen else ""}>{t["emoji"]} {t["label"]}</option>'
        for key, t in themes.THEMES.items()
    )
    return (
        '<form method="post" action="/vibe" class="vibe-switch">'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        f'<input type="hidden" name="back" value="{escape(request.full_path)}">'
        f'<select name="vibe" aria-label="בחרו עיצוב" onchange="this.form.submit()">{options}</select>'
        '<noscript><button class="btn" type="submit">החל</button></noscript></form>'
    )


@app.route("/vibe", methods=["POST"])
def set_vibe():
    """שומר את העיצוב שנבחר, וחוזר לאותו מסך. ריק או לא מוכר חוזר לאוטומטי."""
    choice = request.form.get("vibe", "")
    if choice in themes.THEMES:
        session["vibe_choice"] = choice
    else:
        session.pop("vibe_choice", None)
    back = request.form.get("back", "/")
    # רק כתובת מהאתר הזה. "//" או "/\" היו שולחים לאתר אחר
    if not (back.startswith("/") and back[1:2] not in ("/", "\\") and back.isprintable()):
        back = "/"
    return redirect(back)


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
            + (RELOGIN_NOTE if relogin else ""),
            images=login_images(),
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
        f'<div class="vibe"><span class="vibe-emoji" aria-hidden="true">{vibe["emoji"]}</span>'
        f'<span class="vibe-text"><b>החוויה שלך: {escape(vibe["label"])}</b>'
        f'<span>לפי מה שאתם שומעים הכי הרבה: {auto["emoji"]} {escape(auto["label"])}</span></span></div>'
        + '<div class="menu">'
        + onboarding_card
        + '<a href="/build">✨ צור פלייליסט חדש<small>לפי ז\'אנר (גם בעברית), מצב רוח, אירוע ושפה, מכל ספוטיפיי או מהשירים שאהבתי</small></a>'
        '<a href="/saved-tracks">❤️ כל השירים שאהבתי<small>הרשימה המלאה, עם השמעת קטעים ומיון לפי אמן, תאריך ועוד</small></a>'
        '<a href="/my-artists">🎤 כל האמנים שאני אוהב<small>מי שאני עוקב אחריו, שומע הכי הרבה, או אוהב את השירים שלו</small></a>'
        '<a href="/stats">📊 הסטטיסטיקות שלי<small>ז\'אנרים, עשורים, אמנים מובילים וכרטיס לשיתוף</small></a>'
        '<a href="/my-playlists">🛠 הפלייליסטים שיצרתי<small>שינוי שם, הסרת שירים וסידור</small></a>'
        "</div>"
        '<p class="note">הנתונים נשמרים לכמה שעות כדי שהאפליקציה תהיה מהירה. '
        '<a href="/refresh">רענון נתונים מספוטיפיי</a></p>'
        '<form method="post" action="/delete-data" class="card" '
        'onsubmit="return confirm(\'למחוק מהשרת את הנתונים ששמורים עליכם? חשבון הספוטיפיי שלכם לא ישתנה.\')">'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        '<p class="note">הנתונים שנשמרו בשרת: הספרייה ושירים שאהבתם, כדי שהאפליקציה תהיה מהירה. '
        'מחיקה כאן לא משנה שום דבר בספוטיפיי.</p>'
        '<button class="btn secondary" type="submit">מחיקת הנתונים שלי מהשרת</button></form>'
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


@app.route("/delete-data", methods=["POST"])
def delete_data():
    """מוחק מהשרת את הנתונים ששמורים על המשתמש, ואת התצוגות המקדימות שלו, ומתנתק. לא נוגע בספוטיפיי."""
    uid = session.get("user_id")
    if uid:
        library.clear_cache(uid)
        for token in [t for t, p in _previews.items() if p["uid"] == uid]:
            del _previews[token]
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
        )
        tracks.append(result)

    columns = [("", None), ("", None), ("", None), ("שיר", "text"), ("אמן", "text"), ("אלבום", "text"),
               ("נוסף", "text"), ("אורך", "num"), ("דירוג", "num")]
    rows = []
    for t in tracks:
        first_artist = t["artists"][0][1] if t["artists"] else t["artist"]
        added = t["added"]
        row = (
            f'<td><input type="checkbox" name="uri" value="{escape(t["uri"])}" aria-label="לסמן את {escape(t["name"])}"></td>'
            f'<td><button type="button" class="play" data-artist="{escape(first_artist)}" data-title="{escape(t["name"])}" '
            f'aria-pressed="false" aria-label="השמעת קטע מ{escape(t["name"])}">▶</button></td>'
            f"<td>{spotify_link('', 'album', t['album_id'], cover(t['image']))}</td>"
            + cell(t["name"], cls="name", html=spotify_link(t["name"], "track", t["id"]))
            + cell(t["artist"], cls="short", html=artist_links(t))
            + cell(t["album"], cls="short muted", html=spotify_link(t["album"], "album", t["album_id"]))
            # התאריך מוצג קצר (31.12.24), והמיון לפי התאריך המלא
            + cell(f"{added[8:10]}.{added[5:7]}.{added[2:4]}" if len(added) == 10 else added, added, "muted")
            + cell(format_duration(t["duration"]), t["duration"], "muted")
            # בדירוג, מקום 1 הוא הכי טוב, ולכן ממיינים לפי מספר שלילי
            + cell(format_rank(t["rank"]), -t["rank"][0] if t["rank"] else "", "muted")
        )
        rows.append(f"<tr>{row}</tr>")

    artists_count = len({a for t in tracks for a, _ in t["artists"]})
    total_hours = sum(t["duration"] for t in tracks) / 3_600_000
    note = (
        '<p class="note">לחיצה על ▶ משמיעה קטע של 30 שניות. "דירוג" הוא המקום של השיר '
        "ב-50 השירים שאתם הכי שומעים (ב-4 השבועות האחרונים, ב-6 החודשים האחרונים, או בכל הזמנים).</p>"
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
        title="כל השירים שאהבתי", wide=True, script=TABLE_JS + LAZY_PLAY_JS,
    )


@app.route("/preview")
def preview_lookup():
    """כתובת קטע של 30 שניות לשיר, לכפתור ▶ בטבלת השירים שאהבת. נטען רק כשלוחצים."""
    if not session.get("token_info"):
        return {"url": ""}, 401
    url = preview_url(request.args.get("artist", ""), request.args.get("title", ""))
    return {"url": url}


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


    columns = [("", None), ("אמן", "text"), ("שירים שאהבתי", "num"),
               ("הדירוג שלך", "num"), ("ז'אנרים", "text"), ("עוקב", "num")]
    artists.sort(key=lambda a: (a["rank"][0] if a["rank"] else 999, -a["liked"]))
    rows = []
    for a in artists:
        row = (
            f"<td>{spotify_link('', 'artist', a['id'], cover(a['image']))}</td>"
            + cell(a["name"], cls="name", html=spotify_link(a["name"], "artist", a["id"]))
            + cell(a["liked"])
            + cell(format_rank(a["rank"]), -a["rank"][0] if a["rank"] else "")
            + cell(", ".join(a["genres"][:3]), cls="name muted")
            + cell("✓" if a["followed"] else "", 1 if a["followed"] else 0)
        )
        rows.append(f"<tr>{row}</tr>")

    return page(
        "<h1>כל האמנים שאני אוהב</h1>"
        + stat_boxes([
            ("אמנים", len(artists)),
            ("בין המובילים שלי", sum(1 for a in artists if a["rank"])),
            ("אני עוקב אחריהם", sum(a["followed"] for a in artists)),
        ])
        + '<input type="text" class="search" data-table="artists" placeholder="חיפוש אמן או ז\'אנר...">'
        + f'<div class="table-wrap"><table id="artists" class="sortable"><thead>{header(columns)}</thead>'
        + f'<tbody>{"".join(rows)}</tbody></table></div>',
        title="כל האמנים שאני אוהב", wide=True, script=TABLE_JS,
    )


def bar_chart(rows):
    """שורות (שם, כמות) כגרף עמודות אופקיות. העמודה הארוכה ביותר היא 100%."""
    top = max((count for _, count in rows), default=1) or 1
    return '<div class="bars">' + "".join(
        f'<div class="bar-row"><span>{escape(label)}</span>'
        f'<span class="track"><span class="fill" style="width:{count * 100 // top}%"></span></span>'
        f'<span class="num">{count}</span></div>'
        for label, count in rows
    ) + "</div>"


@app.route("/stats")
def my_stats():
    """גרף ז'אנרים ועשורים, האמנים הכי אהובים, וכרטיס טקסט לשיתוף. מבוסס על השירים שאהבתם."""
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")

    uid = user_id(sp)
    saved = library.cached(uid, "saved", lambda: library.all_saved_tracks(sp))
    if not saved:
        return page(
            "<h1>הסטטיסטיקות שלי</h1>"
            '<p class="note">עדיין אין שירים שאהבתם בספוטיפיי. שמרו כמה שירים, ואז תופיע כאן התמונה המלאה.</p>'
        )
    tags = liked_artist_tags(sp, uid, saved)

    decades, artist_counts, names = Counter(), Counter(), {}
    for item in saved:
        track = item["track"]
        year = album_year(track)
        if year:
            decades[year // 10 * 10] += 1
        for a in track["artists"]:
            if a.get("id"):
                artist_counts[a["id"]] += 1
                names[a["id"]] = a["name"]
    # ז'אנר נספר לפי כמות השירים שאהבתם מהאמנים שלו, כדי שאמן שאוהבים הרבה ישפיע יותר
    genre_counts = Counter()
    for artist_id, count in artist_counts.items():
        for tag in set(tags.get(artist_id, [])):
            genre_counts[tag] += count

    top_artists = [(names[i], c) for i, c in artist_counts.most_common(10)]
    top_genres = [(GENRE_NAMES.get(tag, tag), c) for tag, c in genre_counts.most_common(10)]
    decade_rows = [(decade_label(decade), c) for decade, c in sorted(decades.items())]

    # הכרטיס בלי אמוג'י (ראו share_card_svg), והטקסט לשיתוף עם אמוג'י
    tiles, lines = [], ["🎧 הטעם המוזיקלי שלי", f"❤️ {len(saved):,} שירים שאהבתי"]
    if top_artists:
        tiles.append(("האמן שהכי אהבתי", top_artists[0][0]))
        lines.append(f"🎤 האמן שהכי אהבתי: {top_artists[0][0]}")
    if top_genres:
        tiles.append(("הז'אנר המוביל", top_genres[0][0]))
        lines.append(f"🎶 הז'אנר המוביל: {top_genres[0][0]}")
    if decades:
        best_decade = decade_label(max(decades.items(), key=lambda kv: kv[1])[0])
        tiles.append(("העשור האהוב", best_decade))
        lines.append(f"📅 העשור האהוב: {best_decade}")
    if len(top_artists) >= 3:
        medals = ("🥇", "🥈", "🥉")
        lines.append("🏆 הטופ 3 שלי: " + "  ".join(f"{m} {name}" for m, (name, _) in zip(medals, top_artists)))
    lines.append(f"✨ ומה הטעם שלכם? גלו בפלייליסטור 👉 {public_site()}")
    card_text = "\n".join(lines)
    theme = current_vibe()["theme"]

    genres_html = (
        bar_chart(top_genres) if top_genres
        else '<p class="note">עוד אין מספיק תגיות ז\'אנר לאמנים שאהבתם.</p>'
    )
    return page(
        "<h1>הסטטיסטיקות שלי</h1>"
        + stat_boxes([("שירים שאהבתי", len(saved)), ("אמנים שונים", len(artist_counts))])
        + "<h2>ז'אנרים שאתם הכי אוהבים</h2>"
        + '<p class="note">לפי התגיות של האמנים שאהבתם. ככל שיש לכם יותר שירים מאמן, הוא שוקל יותר.</p>'
        + genres_html
        + "<h2>עשורים</h2>"
        + (bar_chart(decade_rows) if decade_rows else '<p class="note">אין מידע על שנות היציאה.</p>')
        + "<h2>האמנים שאהבתם הכי הרבה</h2>"
        + bar_chart(top_artists)
        + "<h2>📸 כרטיס לשיתוף</h2>"
        + '<div class="share">'
        + share_card_svg(len(saved), tiles, theme)
        + '<div><p class="note" style="margin-top:0">מוכן לסטורי או לפוסט. שתפו את התמונה, '
        'או העתיקו את הטקסט לוואטסאפ.</p>'
        + '<div class="toolbar">'
        + '<button type="button" class="btn" id="share-card" hidden>📲 שיתוף</button>'
        + '<button type="button" class="btn secondary" id="save-card">⬇️ שמירה כתמונה</button></div>'
        + f'<textarea id="card-text" class="copy" readonly aria-label="טקסט לשיתוף">{escape(card_text)}</textarea>'
        + '<div class="toolbar"><button type="button" class="btn secondary" id="copy-card">📋 העתקת טקסט</button></div>'
        + "</div></div>"
        + '<p><a href="/">חזרה לדף הבית</a></p>',
        title="הסטטיסטיקות שלי", wide=True, script=COPY_JS + SAVE_CARD_JS,
    )


CARD_WIDTH, CARD_HEIGHT = 1080, 1350


def public_site():
    """כתובת האתר לשיתוף, למשל https://example.ngrok-free.dev, לפי כתובת החזרה של ספוטיפיי."""
    parts = urlsplit(os.getenv("SPOTIFY_REDIRECT_URI") or request.host_url)
    return f"{parts.scheme}://{parts.netloc}"


def share_card_svg(total, tiles, theme):
    """
    כרטיס לשיתוף בגודל 1080 על 1350, היחס של פוסט באינסטגרם. הדפדפן ממיר אותו ל-PNG (ראו SAVE_CARD_JS).
    tiles: עד שלוש שורות (כותרת, ערך). הכול ממורכז, כדי שהעברית לא תתהפך בתמונה שנוצרת מחוץ לעמוד.
    בלי אמוג'י, כי הם לא נראים נכון בתמונה שנוצרת בדפדפן.
    """
    t = themes.THEMES.get(theme, themes.THEMES["default"])
    c1, c2, c3 = t["colors"]
    accent = t["accent"]
    mid = CARD_WIDTH // 2

    def text(y, size, content, fill="#ffffff", weight="400", opacity="1"):
        return (
            f'<text x="{mid}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'fill-opacity="{opacity}" text-anchor="middle">{escape(content)}</text>'
        )

    tile_html = ""
    for i, (label, value) in enumerate(tiles[:3]):
        y = 600 + i * 170
        tile_html += (
            f'<rect x="90" y="{y}" width="900" height="146" rx="36" fill="#ffffff" fill-opacity="0.07" '
            'stroke="#ffffff" stroke-opacity="0.14" stroke-width="2"/>'
            + text(y + 52, 32, label, "#ffffff", "400", "0.7")
            + text(y + 112, 54, value[:26], "#ffffff", "700")
        )
    # עמודי אקולייזר קטנים בתחתית, כקישוט
    bars = "".join(
        f'<rect x="{150 + i * 32}" y="{1196 - h}" width="18" height="{h}" rx="9" fill="url(#card-accent)" fill-opacity="0.8"/>'
        for i, h in enumerate([28, 52, 76, 44, 92, 60, 36, 84, 56, 98, 40, 70, 30, 88, 62, 46, 80, 34, 66, 50, 90, 38, 58])
    )
    return (
        f'<svg id="card-svg" class="share-svg" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="כרטיס הטעם המוזיקלי שלי" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" '
        f'viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" direction="rtl" font-family="Segoe UI, Arial, sans-serif">'
        "<defs>"
        f'<radialGradient id="glow1" cx="0.15" cy="0.1" r="0.75"><stop offset="0" stop-color="{c1}" stop-opacity="0.75"/>'
        f'<stop offset="1" stop-color="{c1}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="glow2" cx="0.95" cy="0.75" r="0.7"><stop offset="0" stop-color="{c2}" stop-opacity="0.65"/>'
        f'<stop offset="1" stop-color="{c2}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="glow3" cx="0.2" cy="1" r="0.55"><stop offset="0" stop-color="{c3}" stop-opacity="0.45"/>'
        f'<stop offset="1" stop-color="{c3}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="card-accent" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c1}"/>'
        f'<stop offset="1" stop-color="{accent}"/></linearGradient>'
        "</defs>"
        f'<rect width="{CARD_WIDTH}" height="{CARD_HEIGHT}" fill="#0f1016"/>'
        f'<rect width="{CARD_WIDTH}" height="{CARD_HEIGHT}" fill="url(#glow1)"/>'
        f'<rect width="{CARD_WIDTH}" height="{CARD_HEIGHT}" fill="url(#glow2)"/>'
        f'<rect width="{CARD_WIDTH}" height="{CARD_HEIGHT}" fill="url(#glow3)"/>'
        f'<rect x="{mid - 150}" y="80" width="300" height="64" rx="32" fill="#ffffff" fill-opacity="0.1"/>'
        + text(124, 32, "פלייליסטור", "#ffffff", "600", "0.9")
        + text(260, 80, "הטעם המוזיקלי שלי", "#ffffff", "700")
        + text(450, 180, f"{total:,}", accent, "800")
        + text(520, 44, "שירים שאהבתי", "#ffffff", "400", "0.78")
        + tile_html
        + bars
        + text(1280, 34, "ומה הטעם שלכם?", "#ffffff", "600", "0.85")
        + "</svg>"
    )


def playlist_size(playlist):
    """מספר השירים בפלייליסט. ספוטיפיי קוראת לשדה הזה tracks בתשובות ישנות ו-items בחדשות."""
    block = playlist.get("items") or playlist.get("tracks") or {}
    return block.get("total") or 0


def playlist_item_track(item):
    """השיר בשורה של פלייליסט, או None אם הוא לא זמין. השדה נקרא track בתשובות ישנות ו-item בחדשות."""
    if not item:
        return None
    return item.get("item") or item.get("track")


def app_playlists(sp):
    """הפלייליסטים של המשתמש שנוצרו בפלייליסטור. לפי הבעלות והתיאור שהאפליקציה כותבת."""
    uid = user_id(sp)
    found, offset = [], 0
    while True:
        block = sp.current_user_playlists(limit=50, offset=offset)
        found += [
            p for p in block["items"]
            if p and p["owner"]["id"] == uid and PLAYLIST_DESCRIPTION in (p.get("description") or "")
        ]
        if not block.get("next"):
            return found
        offset += 50


def owned_playlist(sp, playlist_id):
    """הפלייליסט אם הוא של המשתמש ונוצר בפלייליסטור. אחרת None, כדי לא לערוך פלייליסטים של אחרים."""
    if not favourites.is_spotify_id(playlist_id):
        return None
    playlist = sp.playlist(playlist_id, fields="id,name,description,owner.id,items.total,tracks.total")
    if playlist["owner"]["id"] != user_id(sp) or PLAYLIST_DESCRIPTION not in (playlist.get("description") or ""):
        return None
    return playlist


def playlist_tracks(sp, playlist_id, limit=MAX_TRACKS * 2):
    """השירים לפי הסדר, עד limit. שיר שלא זמין הוא None, אבל המיקום נשמר."""
    tracks, offset = [], 0
    while offset < limit:
        block = sp.playlist_items(playlist_id, limit=100, offset=offset, additional_types=("track",))
        tracks += [playlist_item_track(item) for item in block["items"]]
        if not block.get("next"):
            break
        offset += 100
    return tracks[:limit]


def editable_or_404(sp, playlist_id):
    playlist = owned_playlist(sp, playlist_id)
    if playlist is None:
        return None, (page(
            '<p>אפשר לערוך רק פלייליסטים שנוצרו בפלייליסטור. <a href="/my-playlists">לרשימה שלי</a>.</p>',
        ), 404)
    return playlist, None


def parse_position(value, total):
    """מספר מקום בפלייליסט, אם הוא בטווח. אחרת None."""
    try:
        position = int(value)
    except (TypeError, ValueError):
        return None
    return position if 0 <= position < total else None


@app.route("/my-playlists")
def my_playlists():
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlists = app_playlists(sp)
    if not playlists:
        body = '<p class="note">עדיין לא שמרתם פלייליסטים דרך פלייליסטור.</p>'
    else:
        rows = "".join(
            f"<li>{cover(image_url(p.get('images')))}"
            f'<div class="info"><div class="title"><a class="sp" href="/playlist/{escape(p["id"])}">'
            f'{escape(p["name"])}</a></div>'
            f'<div class="sub">{playlist_size(p)} שירים</div></div></li>'
            for p in playlists
        )
        body = f'<ul class="list">{rows}</ul>'
    return page(
        "<h1>הפלייליסטים שיצרתי</h1>"
        '<p class="note">שינוי שם, הסרת שירים וסידור, לפלייליסטים ששמרתם דרך פלייליסטור.</p>'
        + body
        + '<p><a href="/">חזרה לדף הבית</a></p>',
        title="הפלייליסטים שיצרתי",
    )


def playlist_row(playlist_id, position, track, count, token):
    """שורה בעריכה: שיר, ומה אפשר לעשות איתו (להזיז למעלה או למטה, או להסיר)."""
    base = f"/playlist/{playlist_id}"

    def button(action, label, extra="", disabled=False):
        attr = " disabled" if disabled else ""
        return (
            f'<form method="post" action="{base}/{action}">'
            f'<input type="hidden" name="csrf" value="{token}">'
            f'<input type="hidden" name="position" value="{position}">{extra}'
            f'<button class="btn secondary" type="submit"{attr}>{label}</button></form>'
        )

    if track is None:
        info = '<div class="title">שיר לא זמין</div>'
        cover_html = '<div class="noimg"></div>'
        remove_extra = ""
    else:
        info = (
            f'<div class="title">{spotify_link(track["name"], "track", track.get("id"))}</div>'
            f'<div class="sub">{", ".join(escape(a["name"]) for a in track.get("artists", []))}</div>'
        )
        cover_html = cover(image_url((track.get("album") or {}).get("images")))
        remove_extra = f'<input type="hidden" name="uri" value="{escape(track["uri"])}">'
    return (
        f"<li>{cover_html}<div class=\"info\">{info}</div>"
        + button("move", "▲", '<input type="hidden" name="direction" value="up">', disabled=position == 0)
        + button("move", "▼", '<input type="hidden" name="direction" value="down">', disabled=position == count - 1)
        + button("remove", "✕", remove_extra)
        + "</li>"
    )


@app.route("/playlist/<playlist_id>")
def edit_playlist(playlist_id):
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlist, error = editable_or_404(sp, playlist_id)
    if error:
        return error
    tracks = playlist_tracks(sp, playlist_id)
    token = csrf_token()
    rows = "".join(playlist_row(playlist_id, i, t, len(tracks), token) for i, t in enumerate(tracks))
    return page(
        f"<h1>{escape(playlist['name'])}</h1>"
        f'<p class="note">{playlist_size(playlist)} שירים. הזיזו שירים למעלה ולמטה, או הסירו אותם.</p>'
        f'<form method="post" action="/playlist/{escape(playlist_id)}/rename" class="toolbar">'
        f'<input type="hidden" name="csrf" value="{token}">'
        f'<label class="field">שם חדש<input type="text" name="name" value="{escape(playlist["name"])}" maxlength="100"></label>'
        '<button class="btn secondary" type="submit">שמירת השם</button></form>'
        + (f'<ul class="list">{rows}</ul>' if rows else '<p class="note">הפלייליסט ריק.</p>')
        + f'<form method="post" action="/playlist/{escape(playlist_id)}/unfollow" class="card" '
        'onsubmit="return confirm(\'להסיר את הפלייליסט מהחשבון שלכם?\')">'
        f'<input type="hidden" name="csrf" value="{token}">'
        '<p class="note">ספוטיפיי לא מאפשר למחוק פלייליסט לגמרי דרך האפליקציה. הסרה תוציא אותו מהחשבון שלכם.</p>'
        '<button class="btn secondary" type="submit">הסרה מהחשבון</button></form>'
        + '<p><a href="/my-playlists">לרשימת הפלייליסטים</a></p>',
        title=playlist["name"],
    )


@app.route("/playlist/<playlist_id>/rename", methods=["POST"])
def rename_playlist(playlist_id):
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlist, error = editable_or_404(sp, playlist_id)
    if error:
        return error
    name = request.form.get("name", "").strip()[:100]
    if name:
        sp.playlist_change_details(playlist_id, name=name)
    return redirect(f"/playlist/{playlist_id}")


@app.route("/playlist/<playlist_id>/remove", methods=["POST"])
def remove_from_playlist(playlist_id):
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlist, error = editable_or_404(sp, playlist_id)
    if error:
        return error
    position = parse_position(request.form.get("position"), playlist_size(playlist))
    uri = request.form.get("uri", "")
    if position is not None and uri.startswith("spotify:track:"):
        # ספוטיפיי מסיר רק אם השיר נמצא במקום הזה, כך שלא נמחק שיר אחר בטעות
        sp.playlist_remove_specific_occurrences_of_items(playlist_id, [{"uri": uri, "positions": [position]}])
    return redirect(f"/playlist/{playlist_id}")


@app.route("/playlist/<playlist_id>/move", methods=["POST"])
def move_in_playlist(playlist_id):
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlist, error = editable_or_404(sp, playlist_id)
    if error:
        return error
    total = playlist_size(playlist)
    position = parse_position(request.form.get("position"), total)
    direction = request.form.get("direction")
    # ספוטיפיי מקבל את המקום שלפניו מכניסים, לפי הרשימה לפני ההזזה
    if position is not None and direction == "up" and position > 0:
        sp.playlist_reorder_items(playlist_id, position, position - 1)
    elif position is not None and direction == "down" and position < total - 1:
        sp.playlist_reorder_items(playlist_id, position, position + 2)
    return redirect(f"/playlist/{playlist_id}")


@app.route("/playlist/<playlist_id>/unfollow", methods=["POST"])
def unfollow_playlist(playlist_id):
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlist, error = editable_or_404(sp, playlist_id)
    if error:
        return error
    sp.current_user_unfollow_playlist(playlist_id)
    return redirect("/my-playlists")


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


DECADES = list(range(1950, 2030, 10))
MISSING_CHOICE = "כדי לבנות פלייליסט, בחרו לפחות אחד: ז'אנר, מצב רוח או אירוע."


def decade_label(decade):
    """1990 → "שנות ה-90", 2010 → "שנות ה-2010"."""
    return f"שנות ה-{decade % 100:02d}" if decade < 2000 else f"שנות ה-{decade}"


def decade_options(first_label):
    return f'<option value="">{escape(first_label)}</option>' + "".join(
        f'<option value="{d}">{escape(decade_label(d))}</option>' for d in DECADES
    )


def build_form(error=""):
    """
    טופס יצירת פלייליסט. חובה לבחור לפחות אחד מהשלושה: ז'אנר, מצב רוח או אירוע,
    והם מסומנים יחד בקבוצה אחת עם כוכבית. השאר רשות.
    """
    req = '<span class="req" aria-hidden="true">*</span>'
    return page(
        "<h1>צור פלייליסט</h1>"
        + (f'<div class="form-error" role="alert" id="build-error">{escape(error)}</div>' if error
           else '<div class="form-error" role="alert" id="build-error" hidden></div>')
        + '<form method="post" class="card" id="build-form" novalidate>'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        f'<label class="field">מאיפה לקחת שירים{req}<select name="source" required>'
        '<option value="search">🌍 מכל ספוטיפיי</option>'
        '<option value="liked">❤️ רק מהשירים שאהבתי</option></select></label>'
        f'<fieldset class="group{" invalid" if error else ""}" id="must-pick">'
        f'<legend>מה מתאים לכם?{req}</legend>'
        '<p class="note" style="margin-top:0">חובה לבחור לפחות אחד מהשלושה.</p>'
        f'<label class="field">🎵 ז\'אנר<select name="genre_choice">{genre_options()}</select></label>'
        '<label class="field">😊 מצב רוח<select name="mood"><option value="">ללא</option>'
        + options(GENRE_HINTS.keys())
        + "</select></label>"
        '<label class="field">📍 אירוע או סיטואציה<select name="event"><option value="">ללא</option>'
        + "".join(
            f'<optgroup label="{escape(group)}">{options(events.keys())}</optgroup>'
            for group, events in EVENT_GROUPS.items()
        )
        + "</select></label></fieldset>"
        '<label class="field">🗣 שפה<select name="language">'
        + options(LANGUAGES)
        + "</select></label>"
        '<div class="toolbar">'
        f'<label class="field">📅 מעשור<select name="decade_from">{decade_options("כל העשורים")}</select></label>'
        f'<label class="field">עד עשור<select name="decade_to">{decade_options("עד היום")}</select></label>'
        "</div><br>"
        f'<label class="field">כמות שירים{req}<span class="hint">בין 5 ל-{MAX_TRACKS}</span>'
        f'<input name="count" type="number" value="20" min="5" max="{MAX_TRACKS}" required></label>'
        '<label class="check"><input type="checkbox" name="personal" checked> לשלב שירים של האמנים המועדפים עליי</label>'
        f'<p class="note"><span class="req">*</span> שדה חובה</p>'
        '<button class="btn" type="submit">✨ הצג שירים</button>'
        "</form>",
        title="צור פלייליסט", script=RANGE_JS + BUILD_CHECK_JS.replace("__MESSAGE__", json.dumps(MISSING_CHOICE)),
    )


@app.route("/build", methods=["GET", "POST"])
def build():
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")

    if request.method == "GET":
        return build_form()

    # קלט מהטופס: מגבילים אורך, ומקבלים רק ערכים מהתפריטים
    criteria = read_criteria()
    if not (criteria["genre"] or criteria["mood"] or criteria["event"]):
        return build_form(MISSING_CHOICE), 400
    started = time.time()
    tracks = find_for(sp, criteria)
    print(f"[פלייליסטור] נבנו {len(tracks)} שירים תוך {time.time() - started:.1f} שניות")
    if not tracks:
        return page('<p>לא נמצאו שירים. <a href="/build">נסו שילוב אחר</a>.</p>')
    token = remember_preview(user_id(sp), criteria, tracks)
    names = names_for(criteria)
    return render_preview(tracks, token, criteria, names[0], names)


def read_criteria():
    """הבחירות מהטופס, אחרי בדיקה: רק ערכים מהתפריטים, ומספרים בטווח."""
    genre = (request.form.get("genre", "").strip() or request.form.get("genre_choice", ""))[:60]
    source = "liked" if request.form.get("source") == "liked" else "search"
    mood = request.form.get("mood", "")
    mood = mood if mood in GENRE_HINTS else ""
    event = request.form.get("event", "")
    event = event if event in EVENT_HINTS else ""
    language = request.form.get("language", "ביחד")
    language = language if language in LANGUAGES else "ביחד"
    # ז'אנר ישראלי מחפש שירים בעברית, אלא אם בחרת שפה אחרת במפורש
    if language == "ביחד" and (genre.startswith("israeli") or genre == "mizrahi"):
        language = "עברית"
    try:
        count = min(max(int(request.form.get("count", 20)), 5), MAX_TRACKS)
    except ValueError:
        count = 20
    return {
        "source": source, "genre": genre, "mood": mood, "event": event, "language": language,
        "count": count, "personal": "personal" in request.form,
        "ranges": read_ranges(), "years": read_years(),
    }


def read_years():
    """
    טווח שנות יציאה לפי עשורים, למשל משנות ה-90 עד שנות ה-2000 → 1990 עד 2009.
    עשור אחד חסר פותח את הטווח. None אם לא נבחר כלום.
    """
    def decade(key):
        try:
            value = int(request.form.get(key, ""))
        except ValueError:
            return None
        return value if value in DECADES else None
    low, high = decade("decade_from"), decade("decade_to")
    if low is None and high is None:
        return None
    low, high = low or 1900, high or 2100
    low, high = min(low, high), max(low, high)
    return (low, high + 9 if high < 2100 else high)


def find_for(sp, criteria, exclude=(), count=None):
    """השירים לפי הבחירות. exclude: שירים שכבר יש בתצוגה, כדי לא לחזור עליהם."""
    count = count or criteria["count"]
    if criteria["source"] == "liked":
        uid = user_id(sp)
        saved = library.cached(uid, "saved", lambda: library.all_saved_tracks(sp))
        tags = liked_artist_tags(sp, uid, saved)
        return find_liked_tracks(
            saved, tags, criteria["genre"], criteria["mood"], criteria["event"], criteria["language"],
            count, criteria["ranges"], criteria["years"], exclude,
        )
    return find_tracks(
        sp, criteria["genre"], criteria["mood"], criteria["event"], criteria["language"], count,
        personal=criteria["personal"], ranges=criteria["ranges"], years=criteria["years"], exclude=exclude,
    )


def names_for(criteria):
    """שם שמתאים לאווירה, ועוד כמה הצעות לכפתור "שם אחר"."""
    return suggest_names(
        criteria["genre"], criteria["mood"], criteria["event"],
        GENRE_NAMES.get(criteria["genre"], criteria["genre"]), from_liked=criteria["source"] == "liked",
    )


# תצוגה מקדימה שנבנתה. "הוסף עוד שירים" צריך את השירים והבחירות המקוריות, ולכן הם נשמרים בזיכרון לשעה
PREVIEW_SECONDS = 60 * 60
PREVIEW_LIMIT = 100
EXTRA_TRACKS = 10
_previews = {}


def remember_preview(uid, criteria, tracks):
    now = time.time()
    for token in [t for t, p in _previews.items() if now - p["at"] > PREVIEW_SECONDS]:
        del _previews[token]
    while len(_previews) >= PREVIEW_LIMIT:
        del _previews[next(iter(_previews))]
    token = secrets.token_urlsafe(16)
    _previews[token] = {"uid": uid, "at": now, "criteria": criteria, "tracks": {t["uri"]: t for t in tracks}}
    return token


def preview_for(token):
    """התצוגה המקדימה אם היא של המשתמש המחובר ועוד לא פגה. אחרת None."""
    preview = _previews.get(token)
    if not preview or preview["uid"] != session.get("user_id"):
        return None
    return preview


def render_preview(tracks, token, criteria, title, names):
    feats = get_features([t["id"] for t in tracks if t.get("id")])
    links = preview_links(tracks)
    rows = "".join(
        track_row(t, checkbox=True, feat=feats.get(t.get("id")), preview=links.get(t["uri"], ""))
        for t in tracks
    )
    theme = themes.theme_for_choice(criteria["genre"], criteria["mood"], criteria["event"])
    covers = list(dict.fromkeys(t["image"] for t in tracks if t["image"]))[:BACKGROUND_IMAGES]
    return page(
        f"<h1>{len(tracks)} שירים בשבילך</h1>"
        '<p class="note">בטלו את הסימון בשירים שלא מתאימים, העבירו שירים למעלה ולמטה, ואז שמרו. '
        "לחיצה על ▶ משמיעה את 30 השניות הראשונות, והכפתור מופיע רק בשירים שיש להם קטע. "
        "לחיצה על שם השיר פותחת אותו בספוטיפיי.</p>"
        '<form method="post" action="/save">'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        f'<input type="hidden" name="theme" value="{escape(theme or "")}">'
        f'<input type="hidden" name="preview" value="{escape(token)}">'
        '<div class="toolbar">'
        f'<label class="field">שם הפלייליסט<input type="text" id="title" name="title" value="{escape(title)}" maxlength="100"></label>'
        f'<button type="button" class="btn secondary" id="other-name" data-names="{escape(json.dumps(names, ensure_ascii=False))}">🔄 שם אחר</button>'
        "</div>"
        '<div class="toolbar">'
        '<label class="field">מיון<select id="sort">'
        '<option value="">הסדר המקורי</option>'
        '<option value="name">שם השיר</option><option value="artist">שם האמן</option>'
        '<option value="duration">אורך</option><option value="year">שנת יציאה (הישנים קודם)</option>'
        '<option value="bpm">קצב (BPM)</option><option value="energy">אנרגיה</option>'
        '<option value="valence">שמחה</option></select></label>'
        '<button type="button" class="btn secondary" id="shuffle">🔀 ערבב</button></div>'
        f'<ul class="list" id="playlist">{rows}</ul><br>'
        '<div class="toolbar">'
        '<button class="btn" type="submit">שמור בספוטיפיי</button>'
        f'<button class="btn secondary" type="submit" formaction="/build/more">➕ הוסף עוד {EXTRA_TRACKS} שירים</button>'
        "</div>"
        "</form>"
        '<p><a href="/build">התחלה מחדש</a></p>',
        theme=theme, images=covers or None, script=NAME_JS + SORT_JS + PLAY_JS,
    )


@app.route("/build/more", methods=["POST"])
def build_more():
    """
    מוסיף שירים לתצוגה המקדימה. השירים שנשארו מסומנים נשמרים בסדר שסידרתם.
    שירים שהסרתם לא חוזרים, וגם לא שירים שכבר נבחרו.
    """
    sp = get_spotify_client()
    if sp is None:
        return redirect("/login")
    preview = preview_for(request.form.get("preview", ""))
    if preview is None:
        return redirect("/build")
    known = preview["tracks"]
    kept = [known[uri] for uri in request.form.getlist("uri") if uri in known]
    extra = find_for(sp, preview["criteria"], exclude=set(known), count=EXTRA_TRACKS)
    tracks = (kept + extra)[:MAX_TRACKS]
    if not tracks:
        return page('<p>אין שירים להציג. <a href="/build">חזרה ליצירת פלייליסט</a>.</p>')
    names = names_for(preview["criteria"])
    title = request.form.get("title", "").strip()[:100] or names[0]
    token = remember_preview(preview["uid"], preview["criteria"], tracks)
    return render_preview(tracks, token, preview["criteria"], title, names)


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
