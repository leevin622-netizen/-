"""
דף הבית, "בשבילך", התחברות והתנתקות, שפה ועיצוב, מחיקת נתונים, ובחירת אמנים ושירים אהובים.
"""
import secrets
import time
from html import escape
from flask import redirect, request, session
import requests
import spotipy
from spotipy.oauth2 import SpotifyOauthError
import library
import themes
from i18n import _, LANGS
import favourites
from urllib.parse import urlencode
from engine import GENRE_CHOICES
import web
import routes_build
from web import (
    RELOGIN_NOTE, SCOPE, app, artist_links, cover, csrf_token, current_vibe, login_images, make_auth,
    back_from_referrer, local_path, my_genres, page, spotify_link, stat_boxes, user_client, user_id,
)


@app.route("/lang", methods=["POST"])
def set_lang():
    code = request.form.get("lang", "he")
    session["lang"] = code if code in {c for c, _n, _d in LANGS} else "he"
    return redirect(local_path(request.form.get("back")))


@app.route("/vibe", methods=["POST"])
def set_vibe():
    """שומר את העיצוב שנבחר, וחוזר לאותו מסך. ריק או לא מוכר חוזר לאוטומטי."""
    choice = request.form.get("vibe", "")
    if choice in themes.THEMES:
        session["vibe_choice"] = choice
    else:
        session.pop("vibe_choice", None)
    return redirect(local_path(request.form.get("back")))


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
        return _('<p class="note">אין תוצאות להצגה.</p>')
    rows = []
    for artist in artists:
        if artist["id"] in followed:
            action = _('<span class="note">✓ עוקב</span>')
        else:
            action = pick_form("/favourites/artist", artist["id"], q, _("➕ עקוב"))
        rows.append(
            f"<li>{cover(artist['image'])}"
            f'<div class="info"><div class="title">{spotify_link(artist["name"], "artist", artist["id"])}</div></div>'
            f"{action}</li>"
        )
    return f'<ul class="list">{"".join(rows)}</ul>'


def track_rows(tracks, saved, q):
    if not tracks:
        return _('<p class="note">אין תוצאות להצגה.</p>')
    rows = []
    for track in tracks:
        if saved.get(track["id"]):
            action = _('<span class="note">✓ שמור</span>')
        else:
            action = pick_form("/favourites/track", track["id"], q, _("❤ שמור"))
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
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")

    uid = user_id(sp)
    q = request.args.get("q", "").strip()[:100]
    followed = {a["id"] for a in favourites.followed_artists(sp, uid)}
    songs = favourites.saved_songs(sp, uid)
    body = (
        _("<h1>אמנים ושירים שאתם אוהבים</h1>"
        '<p class="note">סמנו מה שאתם אוהבים, והבחירות יישמרו בחשבון הספוטיפיי שלכם: '
        "אמנים שתעקבו אחריהם, ושירים שתשמרו. לפיהם נמליץ לכם על שירים נוספים.</p>")
        + stat_boxes([(_("אמנים שאני עוקב אחריהם"), len(followed)), (_("שירים שמורים"), songs)])
        + _("<form method=\"get\" action=\"/favourites\" class=\"toolbar\"><label class=\"field\">חיפוש<input type=\"text\" name=\"q\" value=\"{a0}\" placeholder=\"שם אמן או שיר\"></label><button class=\"btn secondary\" type=\"submit\">חיפוש</button></form>", a0=escape(q))
    )
    if q:
        artists, tracks = favourites.search(sp, q)
        saved = favourites.saved_flags(sp, [t["id"] for t in tracks])
        body += (
            _("<h2>אמנים</h2>") + artist_rows(artists, followed, q)
            + _("<h2>שירים</h2>") + track_rows(tracks, saved, q)
        )
    else:
        rec = favourites.recommendations(sp, uid)
        artists = [a for a in rec["artists"] if a["id"] not in followed]
        saved = favourites.saved_flags(sp, [t["id"] for t in rec["tracks"]])
        tracks = [t for t in rec["tracks"] if not saved.get(t["id"])]
        if rec["source"] == "well_known":
            heading = _("זמרים מוכרים כדי להתחיל")
            note = _("עדיין אין לכם אמנים או שירים אהובים, אז אלה זמרים מוכרים. סמנו מי שאתם אוהבים, ונמליץ על עוד לפי זה.")
        else:
            heading = _("המלצות בשבילכם")
            note = _("אמנים דומים למה שאתם כבר אוהבים, ושירים מהם.")
        body += (
            f'<h2>{heading}</h2><p class="note">{note}</p>'
            + artist_rows(artists, followed, "")
            + _("<h2>שירים שאולי תאהבו</h2>")
            + track_rows(tracks, saved, "")
        )
    return page(body + _('<p><a href="/">חזרה לדף הבית</a></p>'), title=_("אמנים ושירים שאתם אוהבים"))


@app.route("/favourites/artist", methods=["POST"])
def follow_artist():
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")
    artist_id = request.form.get("id", "")
    if favourites.is_spotify_id(artist_id):
        sp.user_follow_artists([artist_id])
        library.forget(user_id(sp), "followed")
    return redirect(favourites_url(request.form.get("q", "").strip()[:100]))


@app.route("/favourites/track", methods=["POST"])
def save_favourite_track():
    sp = web.get_spotify_client()
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
            _("<h1>פלייליסטים שמתאימים בדיוק לרגע</h1>"
            '<p class="note">בחרו ז\'אנר, מצב רוח ואירוע, ופלייליסטור יבנה לכם פלייליסט חדש בספוטיפיי.</p>'
            '<a class="btn" href="/login">התחברות עם ספוטיפיי</a>')
            + (_(RELOGIN_NOTE) if relogin else ""),
            images=login_images(),
        )
    sp = web.get_spotify_client()
    onboarding_card = (
        _('<a href="/favourites">🌟 בחרו אמנים ושירים שאתם אוהבים'
        '<small>ככה נוכל להמליץ לכם על שירים שמתאימים לטעם שלכם</small></a>')
        if sp is not None and wants_favourites(sp) else ""
    )
    vibe = themes.THEMES[current_vibe()["theme"]]
    auto = themes.THEMES[web.auto_vibe()["theme"]]
    return page(
        _("<h1>מה נשמע היום?</h1><div class=\"vibe\"><span class=\"vibe-emoji\" aria-hidden=\"true\">{a0}</span><span class=\"vibe-text\"><b>הווייב שלך עכשיו: {a1}</b>", a0=vibe["emoji"], a1=escape(_(vibe["label"])))
        + (
            _("<span>בול מה שהכי מתנגן אצלך לאחרונה 🔥</span>") if vibe is auto
            else _("<span>מה שהכי מתנגן אצלך: {a0} {a1} · אפשר להחליף בתפריט למעלה</span>", a0=auto["emoji"], a1=escape(_(auto["label"])))
        )
        + "</span></div>"
        + for_you()
        + '<div class="menu">'
        + onboarding_card
        + _("<a href=\"/build\">✨ צור פלייליסט חדש<small>לפי ז'אנר (גם בעברית), מצב רוח, אירוע ושפה, מכל ספוטיפיי או מהשירים שאהבתי</small></a><a href=\"/saved-tracks\">❤️ כל השירים שאהבתי<small>הרשימה המלאה, עם השמעת קטעים ומיון לפי אמן, תאריך ועוד</small></a><a href=\"/my-artists\">🎤 כל האמנים שאני אוהב<small>מי שאני עוקב אחריו, שומע הכי הרבה, או אוהב את השירים שלו</small></a><a href=\"/stats\">📊 הסטטיסטיקות שלי<small>ז'אנרים, עשורים, אמנים מובילים וכרטיס לשיתוף</small></a><a href=\"/existing-playlists\">📚 פלייליסטים קיימים<small>הפלייליסטים הגדולים בספוטיפיי בארצות הברית ובישראל, עם סינון לפי קטגוריות</small></a><a href=\"/my-playlists\">🛠 הפלייליסטים שיצרתי<small>שינוי שם, הסרת שירים וסידור</small></a></div><p class=\"note\">הנתונים נשמרים לכמה שעות כדי שהאפליקציה תהיה מהירה. <a href=\"/refresh\">רענון נתונים מספוטיפיי</a></p><form method=\"post\" action=\"/delete-data\" class=\"card\" onsubmit=\"return confirm('למחוק מהשרת את הנתונים ששמורים עליכם? חשבון הספוטיפיי שלכם לא ישתנה.')\"><input type=\"hidden\" name=\"csrf\" value=\"{a0}\"><p class=\"note\">הנתונים שנשמרו בשרת: הספרייה ושירים שאהבתם, כדי שהאפליקציה תהיה מהירה. מחיקה כאן לא משנה שום דבר בספוטיפיי.</p><button class=\"btn secondary\" type=\"submit\">מחיקת הנתונים שלי מהשרת</button></form>", a0=csrf_token())
    )


# כמה שירים בפלייליסט "בשבילך" מדף הבית
FOR_YOU_TRACKS = 30


def for_you():
    """
    "בשבילך": פלייליסט בלחיצה אחת לכל אחד מהז'אנרים שהמשתמש הכי שומע, עם האמנים המועדפים שלו מאותו ז'אנר.
    טופס אחד: הכפתור שנלחץ שולח את הז'אנר שלו. ריק אם הטעם עוד לא ידוע.
    """
    genres = my_genres()
    if not genres:
        return ""
    names = {term: name for name, term in GENRE_CHOICES}
    buttons = "".join(
        f'<button class="btn secondary" type="submit" name="genre_choice" value="{escape(term)}">'
        f'{escape(_(names[term]))}</button>'
        for term in genres
    )
    return (
        '<form method="post" action="/build" class="card for-you">'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        '<input type="hidden" name="source" value="search"><input type="hidden" name="language" value="ביחד">'
        f'<input type="hidden" name="count" value="{FOR_YOU_TRACKS}"><input type="hidden" name="personal" value="on">'
        + _("<h2>🎧 בשבילך</h2><p class=\"note\">פלייליסט של {a0} שירים בלחיצה אחת, לפי הז'אנרים שאתם הכי שומעים, עם האמנים שאתם אוהבים.</p>", a0=FOR_YOU_TRACKS)
        + f'<div class="toolbar">{buttons}</div></form>'
    )


@app.route("/login")
def login():
    # מצב (state) אקראי שחוזר מספוטיפיי. בלעדיו אתר אחר יכול להתחבר בשם המשתמש לחשבון שלו
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return redirect(make_auth().get_authorize_url(state=state))


# רענון מלא שולח הרבה בקשות לספוטיפיי, שהמכסה שלו משותפת לכל האתר. לכן פעם ב-10 דקות לכל היותר
REFRESH_SECONDS = 10 * 60


@app.route("/refresh")
def refresh():
    """טוען מחדש מספוטיפיי את השירים, האמנים והסגנון (למשל אחרי שאהבת שירים חדשים)."""
    now = time.time()
    if session.get("user_id") and now - session.get("refreshed_at", 0) > REFRESH_SECONDS:
        library.clear_cache(session["user_id"])
        session["refreshed_at"] = now
    return redirect(back_from_referrer())


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
        routes_build.forget_previews(uid)
        library.forget_created(uid)
    session.clear()
    return redirect("/")


@app.route("/callback")
def callback():
    code = request.args.get("code")
    expected_state = session.pop("oauth_state", None)
    if not code or not expected_state or request.args.get("state") != expected_state:
        return page(_("<p>ההתחברות בוטלה או נכשלה, או שהבקשה לא הגיעה מהאפליקציה. <a href=\"/login\">נסו שוב</a>.</p>")), 400

    try:
        token_info = make_auth().get_access_token(code, check_cache=False)
    except SpotifyOauthError:
        return page(_('<p>ההתחברות נכשלה. <a href="/login">נסו שוב</a>.</p>')), 400
    session["token_info"] = token_info
    session.permanent = True
    user = user_client(token_info["access_token"]).current_user()
    session["user_name"] = user.get("display_name") or ""
    session["user_id"] = user["id"]
    session["scope"] = SCOPE
    return redirect("/")
