"""
יצירת פלייליסט: הטופס, בניית השירים, התצוגה המקדימה, "הוסף עוד שירים" ושמירה בספוטיפיי.
"""
import secrets
import time
from html import escape
from flask import redirect, request, session
import library
import themes
from i18n import _, lang
import json
from playlist_names import suggest_names
from engine import (
    GENRE_HINTS, EVENT_HINTS, EVENT_GROUPS, LANGUAGES, find_tracks, find_liked_tracks, create_playlist,
    PLAYLIST_DESCRIPTION,
)
from vibes import get_features
import web
from web import (
    BACKGROUND_IMAGES, DECADES, GENRE_NAMES, MAX_SAVE, MAX_TRACKS, app, csrf_token, decade_options,
    genre_options, liked_artist_tags, my_genres, options, page, track_row, user_id,
)
from scripts import BUILD_CHECK_JS, LAZY_PLAY_JS, NAME_JS, SORT_JS


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


MISSING_CHOICE = "כדי לבנות פלייליסט, בחרו לפחות אחד: ז'אנר, מצב רוח או אירוע."


def field(label, control, hint=""):
    """שדה בטופס: תווית, הסבר קצר (רשות) והפקד עצמו."""
    hint = f'<span class="hint">{hint}</span>' if hint else ""
    return f'<label class="field">{label}{hint}{control}</label>'


def select(name, choices, first=None):
    """תפריט. first: אפשרות ריקה בראש התפריט (למשל "ללא")."""
    empty = f'<option value="">{escape(first)}</option>' if first else ""
    return f'<select name="{name}">{empty}{choices}</select>'


def build_form(error="", genre=""):
    """
    טופס יצירת פלייליסט, פשוט ככל האפשר: ז'אנר, מצב רוח וכפתור. כל השאר (אירוע, מקור, שפה, עשורים,
    כמות ואמנים מועדפים) מקופל תחת "אפשרויות נוספות", עם ברירות מחדל טובות.
    חובה לבחור לפחות אחד: ז'אנר, מצב רוח או אירוע.
    genre: הז'אנר שמסומן מראש (הז'אנר שהמשתמש הכי שומע).
    """
    req = '<span class="req" aria-hidden="true">*</span>'
    none = _("ללא")
    events = "".join(
        f'<optgroup label="{escape(_(group))}">{options(items.keys())}</optgroup>'
        for group, items in EVENT_GROUPS.items()
    )
    sources = (
        f'<option value="search">{escape(_("🌍 מכל ספוטיפיי"))}</option>'
        f'<option value="liked">{escape(_("❤️ רק מהשירים שאהבתי"))}</option>'
    )
    must_pick = (
        f'<fieldset class="group{" invalid" if error else ""}" id="must-pick">'
        f'<legend>{escape(_("מה מתאים לכם?"))}{req}</legend>'
        + field(escape(_("🎵 ז'אנר")), f'<select name="genre_choice">{genre_options(genre)}</select>')
        + field(escape(_("😊 מצב רוח")), select("mood", options(GENRE_HINTS.keys()), none))
        + "</fieldset>"
    )
    more = (
        '<details class="more-options">'
        f'<summary>{escape(_("⚙️ אפשרויות נוספות"))}<span class="hint">'
        f'{escape(_("אירוע, מקור השירים, שפה, עשורים וכמות"))}</span></summary>'
        + field(escape(_("📍 אירוע או סיטואציה")), select("event", events, none))
        + field(escape(_("מאיפה לקחת שירים")), f'<select name="source">{sources}</select>')
        + field(escape(_("🗣 שפה")), select("language", options(LANGUAGES)))
        + '<div class="toolbar">'
        + field(escape(_("📅 מעשור")), f'<select name="decade_from">{decade_options(_("כל העשורים"))}</select>')
        + field(escape(_("עד עשור")), f'<select name="decade_to">{decade_options(_("עד היום"))}</select>')
        + "</div>"
        + field(escape(_("כמות שירים")),
                f'<input name="count" type="number" value="20" min="5" max="{MAX_TRACKS}" required>',
                escape(_("בין 5 ל-{a0}", a0=MAX_TRACKS)))
        + f'<label class="check"><input type="checkbox" name="personal" checked> '
        f'{escape(_("לשלב שירים של האמנים המועדפים עליי"))}</label>'
        + "</details>"
    )
    return page(
        _("<h1>צור פלייליסט</h1>")
        + (f'<div class="form-error" role="alert" id="build-error">{escape(error)}</div>' if error
           else '<div class="form-error" role="alert" id="build-error" hidden></div>')
        + f'<form method="post" class="card" id="build-form" novalidate>'
        f'<input type="hidden" name="csrf" value="{csrf_token()}">'
        + must_pick + more
        + f'<button class="btn" type="submit">{escape(_("✨ הצג שירים"))}</button></form>',
        title=_("צור פלייליסט"), script=BUILD_CHECK_JS.replace("__MESSAGE__", json.dumps(_(MISSING_CHOICE), ensure_ascii=False)),
    )


@app.route("/build", methods=["GET", "POST"])
def build():
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")

    if request.method == "GET":
        favourite = my_genres()
        return build_form(genre=favourite[0] if favourite else "")

    # קלט מהטופס: מגבילים אורך, ומקבלים רק ערכים מהתפריטים
    criteria = read_criteria()
    if not (criteria["genre"] or criteria["mood"] or criteria["event"]):
        return build_form(_(MISSING_CHOICE)), 400
    started = time.time()
    tracks = find_for(sp, criteria)
    print(f"[פלייליסטור] נבנו {len(tracks)} שירים תוך {time.time() - started:.1f} שניות")
    if not tracks:
        return page(_('<p>לא נמצאו שירים. <a href="/build">נסו שילוב אחר</a>.</p>'))
    token = remember_preview(user_id(sp), criteria, tracks)
    names = names_for(criteria)
    return render_preview(tracks, token, criteria, names[0], names, requested=criteria["count"])


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
        artist_tags=web.auto_vibe().get("artist_tags"),
    )


def names_for(criteria):
    """שם שמתאים לאווירה, ועוד כמה הצעות לכפתור "שם אחר". בשפות אחרות, שמות לפי מה שבחרתם."""
    if lang() != "he":
        parts = [_(GENRE_NAMES.get(criteria["genre"], criteria["genre"])) if criteria["genre"] else "",
                 _(criteria["mood"]) if criteria["mood"] else "", _(criteria["event"]) if criteria["event"] else ""]
        label = " · ".join(p for p in parts if p) or _("מיקס")
        heart = " ❤️" if criteria["source"] == "liked" else ""
        return [f"{label} 🎧{heart}", f"{label} · {_('מיקס')}{heart}", f"✨ {label}{heart}", f"{label} 🔥{heart}"]
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


def forget_previews(uid):
    """מוחק את התצוגות המקדימות של המשתמש (במחיקת הנתונים שלו)."""
    for token in [t for t, p in _previews.items() if p["uid"] == uid]:
        del _previews[token]


def preview_for(token):
    """התצוגה המקדימה אם היא של המשתמש המחובר ועוד לא פגה. אחרת None."""
    preview = _previews.get(token)
    if not preview or preview["uid"] != session.get("user_id"):
        return None
    return preview


def render_preview(tracks, token, criteria, title, names, requested=None):
    feats = get_features([t["id"] for t in tracks if t.get("id")])
    rows = "".join(track_row(t, checkbox=True, feat=feats.get(t.get("id"))) for t in tracks)
    short = ""
    if requested and len(tracks) < requested:
        short = (
            _("<div class=\"warn\">ביקשתם {a0} שירים, ומצאנו {a1} שמתאימים לבחירות שלכם. השלמנו כמה שאפשר בלי לצאת מהז'אנר, מהשפה ומהעשורים שבחרתם. כדי לקבל יותר, אפשר לבחור פחות הגבלות (למשל בלי עשור, או שפה \"ביחד\").</div>", a0=requested, a1=len(tracks))
        )
    theme = themes.theme_for_choice(criteria["genre"], criteria["mood"], criteria["event"])
    covers = list(dict.fromkeys(t["image"] for t in tracks if t["image"]))[:BACKGROUND_IMAGES]
    return page(
        _("<h1>{a0} שירים בשבילך</h1>", a0=len(tracks))
        + short
        + 
        _("<p class=\"note\">בטלו את הסימון בשירים שלא מתאימים, העבירו שירים למעלה ולמטה, ואז שמרו. לחיצה על ▶ משמיעה קטע מהשיר. אם אין קטע קצר, נפתח נגן ספוטיפיי של השיר בתחתית המסך. לחיצה על שם השיר פותחת אותו בספוטיפיי.</p><form method=\"post\" action=\"/save\"><input type=\"hidden\" name=\"csrf\" value=\"{a0}\"><input type=\"hidden\" name=\"theme\" value=\"{a1}\"><input type=\"hidden\" name=\"preview\" value=\"{a2}\"><div class=\"toolbar\"><label class=\"field\">שם הפלייליסט<input type=\"text\" id=\"title\" name=\"title\" value=\"{a3}\" maxlength=\"100\"></label><button type=\"button\" class=\"btn secondary\" id=\"other-name\" data-names=\"{a4}\">🔄 שם אחר</button></div><div class=\"toolbar\"><label class=\"field\">מיון<select id=\"sort\"><option value=\"\">הסדר המקורי</option><option value=\"name\">שם השיר</option><option value=\"artist\">שם האמן</option><option value=\"duration\">אורך</option><option value=\"year\">שנת יציאה (הישנים קודם)</option><option value=\"bpm\">קצב (BPM)</option><option value=\"energy\">אנרגיה</option><option value=\"valence\">שמחה</option></select></label><button type=\"button\" class=\"btn secondary\" id=\"shuffle\">🔀 ערבב</button></div><ul class=\"list numbered\" id=\"playlist\">{a5}</ul><br><div class=\"toolbar savebar\"><button class=\"btn\" type=\"submit\">שמור בספוטיפיי</button><button class=\"btn secondary\" type=\"submit\" formaction=\"/build/more\">➕ הוסף עוד {a6} שירים</button></div></form><p><a href=\"/build\">התחלה מחדש</a></p>", a0=csrf_token(), a1=escape(theme or ""), a2=escape(token), a3=escape(title), a4=escape(json.dumps(names, ensure_ascii=False)), a5=rows, a6=EXTRA_TRACKS),
        wide=True, theme=theme, images=covers or None, script=NAME_JS + SORT_JS + LAZY_PLAY_JS,
    )


@app.route("/build/more", methods=["POST"])
def build_more():
    """
    מוסיף שירים לתצוגה המקדימה. השירים שנשארו מסומנים נשמרים בסדר שסידרתם.
    שירים שהסרתם לא חוזרים, וגם לא שירים שכבר נבחרו.
    """
    sp = web.get_spotify_client()
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
        return page(_('<p>אין שירים להציג. <a href="/build">חזרה ליצירת פלייליסט</a>.</p>'))
    names = names_for(preview["criteria"])
    title = request.form.get("title", "").strip()[:100] or names[0]
    token = remember_preview(preview["uid"], preview["criteria"], tracks)
    return render_preview(tracks, token, preview["criteria"], title, names)


@app.route("/save", methods=["POST"])
def save():
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")

    uris = [u for u in request.form.getlist("uri") if u.startswith("spotify:track:")][:MAX_SAVE]
    if not uris:
        return page(_('<p>לא נבחרו שירים. <a href="/build">חזרה ליצירת פלייליסט</a>.</p>'))
    title = request.form.get("title", "").strip()[:100] or _("פלייליסטור - מיקס")
    playlist_id, url = create_playlist(sp, title, uris, _(PLAYLIST_DESCRIPTION))
    uid = user_id(sp)
    # זוכרים שהפלייליסט נוצר כאן, גם אם ספוטיפיי לא יחזיר את התיאור שלו
    library.remember_created(uid, playlist_id)
    library.forget(uid, "app_playlists")
    theme = request.form.get("theme")
    return page(
        _("<div class=\"success\"><h1>הפלייליסט נשמר! 🎉</h1><p>{a0}, {a1} שירים.</p><a class=\"btn\" href=\"{a2}\" target=\"_blank\" rel=\"noopener\">פתיחה בספוטיפיי</a></div><p><a href=\"/build\">ליצירת פלייליסט נוסף</a></p>", a0=escape(title), a1=len(uris), a2=escape(url)),
        theme=theme if theme in themes.THEMES else None,
    )
