"""
הפלייליסטים שיצרתי ועריכה שלהם: שינוי שם, הזזה והסרה של שירים, והסרה מהחשבון.
"""
from html import escape
from flask import redirect, request
from i18n import _
from translations import TRANSLATIONS
import favourites
from engine import PLAYLIST_DESCRIPTION
import web
from web import MAX_TRACKS, app, cover, csrf_token, image_url, page, spotify_link, user_id


def playlist_size(playlist):
    """מספר השירים בפלייליסט. ספוטיפיי קוראת לשדה הזה tracks בתשובות ישנות ו-items בחדשות."""
    block = playlist.get("items") or playlist.get("tracks") or {}
    return block.get("total") or 0


def playlist_item_track(item):
    """השיר בשורה של פלייליסט, או None אם הוא לא זמין. השדה נקרא track בתשובות ישנות ו-item בחדשות."""
    if not item:
        return None
    return item.get("item") or item.get("track")


# התיאור שהאפליקציה כותבת בספוטיפיי, בכל שפה. לפיו מזהים פלייליסטים שנוצרו כאן
DESCRIPTIONS = [PLAYLIST_DESCRIPTION] + list(TRANSLATIONS.get(PLAYLIST_DESCRIPTION, {}).values())


def made_here(playlist):
    description = playlist.get("description") or ""
    return any(text in description for text in DESCRIPTIONS)


def app_playlists(sp):
    """הפלייליסטים של המשתמש שנוצרו בפלייליסטור. לפי הבעלות והתיאור שהאפליקציה כותבת."""
    uid = user_id(sp)
    found, offset = [], 0
    while True:
        block = sp.current_user_playlists(limit=50, offset=offset)
        found += [
            p for p in block["items"]
            if p and p["owner"]["id"] == uid and made_here(p)
        ]
        if not block.get("next"):
            return found
        offset += 50


def owned_playlist(sp, playlist_id):
    """הפלייליסט אם הוא של המשתמש ונוצר בפלייליסטור. אחרת None, כדי לא לערוך פלייליסטים של אחרים."""
    if not favourites.is_spotify_id(playlist_id):
        return None
    playlist = sp.playlist(playlist_id, fields="id,name,description,owner.id,items.total,tracks.total")
    if playlist["owner"]["id"] != user_id(sp) or not made_here(playlist):
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
            _('<p>אפשר לערוך רק פלייליסטים שנוצרו בפלייליסטור. <a href="/my-playlists">לרשימה שלי</a>.</p>'),
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
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlists = app_playlists(sp)
    if not playlists:
        body = _('<p class="note">עדיין לא שמרתם פלייליסטים דרך פלייליסטור.</p>')
    else:
        rows = "".join(
            _("<li>{a0}<div class=\"info\"><div class=\"title\"><a class=\"sp\" href=\"/playlist/{a1}\">{a2}</a></div><div class=\"sub\">{a3} שירים</div></div></li>", a0=cover(image_url(p.get('images'))), a1=escape(p["id"]), a2=escape(p["name"]), a3=playlist_size(p))
            for p in playlists
        )
        body = f'<ul class="list">{rows}</ul>'
    return page(
        _("<h1>הפלייליסטים שיצרתי</h1>"
        '<p class="note">שינוי שם, הסרת שירים וסידור, לפלייליסטים ששמרתם דרך פלייליסטור.</p>')
        + body
        + _('<p><a href="/">חזרה לדף הבית</a></p>'),
        title=_("הפלייליסטים שיצרתי"),
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
        info = _('<div class="title">שיר לא זמין</div>')
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
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlist, error = editable_or_404(sp, playlist_id)
    if error:
        return error
    tracks = playlist_tracks(sp, playlist_id)
    token = csrf_token()
    rows = "".join(playlist_row(playlist_id, i, t, len(tracks), token) for i, t in enumerate(tracks))
    return page(
        _("<h1>{a0}</h1><p class=\"note\">{a1} שירים. הזיזו שירים למעלה ולמטה, או הסירו אותם.</p><form method=\"post\" action=\"/playlist/{a2}/rename\" class=\"toolbar\"><input type=\"hidden\" name=\"csrf\" value=\"{a3}\"><label class=\"field\">שם חדש<input type=\"text\" name=\"name\" value=\"{a4}\" maxlength=\"100\"></label><button class=\"btn secondary\" type=\"submit\">שמירת השם</button></form>", a0=escape(playlist['name']), a1=playlist_size(playlist), a2=escape(playlist_id), a3=token, a4=escape(playlist["name"]))
        + (f'<ul class="list cols">{rows}</ul>' if rows else _('<p class="note">הפלייליסט ריק.</p>'))
        + _("<form method=\"post\" action=\"/playlist/{a0}/unfollow\" class=\"card\" onsubmit=\"return confirm('להסיר את הפלייליסט מהחשבון שלכם?')\"><input type=\"hidden\" name=\"csrf\" value=\"{a1}\"><p class=\"note\">ספוטיפיי לא מאפשר למחוק פלייליסט לגמרי דרך האפליקציה. הסרה תוציא אותו מהחשבון שלכם.</p><button class=\"btn secondary\" type=\"submit\">הסרה מהחשבון</button></form>", a0=escape(playlist_id), a1=token)
        + _('<p><a href="/my-playlists">לרשימת הפלייליסטים</a></p>'),
        title=playlist["name"], wide=True,
    )


@app.route("/playlist/<playlist_id>/rename", methods=["POST"])
def rename_playlist(playlist_id):
    sp = web.get_spotify_client()
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
    sp = web.get_spotify_client()
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
    sp = web.get_spotify_client()
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
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")
    playlist, error = editable_or_404(sp, playlist_id)
    if error:
        return error
    sp.current_user_unfollow_playlist(playlist_id)
    return redirect("/my-playlists")
