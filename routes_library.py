"""
הספרייה של המשתמש: השירים שאהבתי, האמנים שאני אוהב, והסטטיסטיקות עם כרטיס השיתוף.
"""
import os
from collections import Counter
from html import escape
from flask import redirect, request, session
from lastfm import get_tags_for_artists
import library
import themes
from i18n import _
from urllib.parse import urlsplit
from previews import preview_url
from engine import to_result, album_year
import web
from web import (
    GENRE_NAMES, app, artist_links, cell, cover, current_vibe, decade_label, format_duration, format_rank,
    header, liked_artist_tags, page, play_button, spotify_link, stat_boxes, user_id,
)
from scripts import COPY_JS, LAZY_PLAY_JS, SAVE_CARD_JS, TABLE_JS


@app.route("/saved-tracks")
def saved_tracks():
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")

    uid = user_id(sp)
    saved = library.cached(uid, "saved", lambda: library.all_saved_tracks(sp))
    track_ranks, _objects = library.cached(uid, "top_tracks", lambda: library.top_ranks(sp, "tracks"))

    tracks = []
    for item in saved:
        track = item["track"]
        result = to_result(track)
        result.update(
            album=track.get("album", {}).get("name", ""),
            added=item.get("added_at", "")[:10],
            duration=track.get("duration_ms") or 0,
            rank=library.best_rank(track_ranks.get(track["id"])),
        )
        tracks.append(result)

    columns = [("", None), ("", None), ("", None), (_("שיר"), "text"), (_("אמן"), "text"), (_("אלבום"), "text"),
               (_("נוסף"), "text"), (_("אורך"), "num"), (_("דירוג"), "num")]
    rows = []
    for t in tracks:
        added = t["added"]
        row = (
            _("<td><input type=\"checkbox\" name=\"uri\" value=\"{a0}\" aria-label=\"לסמן את {a1}\"></td><td>{a2}</td><td>{a3}</td>", a0=escape(t["uri"]), a1=escape(t["name"]), a2=play_button(t), a3=spotify_link('', 'album', t['album_id'], cover(t['image'])))
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

    artists_count = len({a for t in tracks for a, _name in t["artists"]})
    total_hours = sum(t["duration"] for t in tracks) / 3_600_000
    note = (
        _('<p class="note">לחיצה על ▶ משמיעה קטע מהשיר (ואם אין, נפתח נגן ספוטיפיי בתחתית). "דירוג" הוא המקום של השיר '
        "ב-50 השירים שאתם הכי שומעים (ב-4 השבועות האחרונים, ב-6 החודשים האחרונים, או בכל הזמנים).</p>")
    )
    return page(
        _("<h1>כל השירים שאהבתי</h1>")
        + stat_boxes([(_("שירים"), len(tracks)), (_("אמנים"), artists_count), (_("שעות האזנה ברשימה"), f"{total_hours:.1f}")])
        + note
        + _('<input type="text" class="search" data-table="tracks" placeholder="חיפוש שיר, אמן או אלבום...">')
        + '<form method="post" action="/save">'
        + '<div class="toolbar">'
        + _('<label class="field">שם לפלייליסט מהשירים שסימנתי')
        + _('<input type="text" name="title" value="פלייליסטור - השירים שאהבתי" maxlength="100"></label>')
        + _('<button type="button" class="btn secondary" data-check-visible="tracks">סמן את כל המוצגים</button>')
        + _('<button type="submit" class="btn">צור פלייליסט מהמסומנים</button>')
        + "</div>"
        + _('<p class="note">טיפ: חפשו אמן או אלבום, לחצו "סמן את כל המוצגים", ואז "צור פלייליסט". ')
        + _('לפלייליסט לפי ז\'אנר או מצב רוח מתוך השירים שאהבתם, השתמשו ב<a href="/build">יצירת פלייליסט</a>.</p>')
        + f'<div class="table-wrap"><table id="tracks" class="sortable numbered"><thead>{header(columns)}</thead>'
        + f'<tbody>{"".join(rows)}</tbody></table></div>'
        + "</form>",
        title=_("כל השירים שאהבתי"), wide=True, script=TABLE_JS + LAZY_PLAY_JS,
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
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")

    uid = user_id(sp)
    saved = library.cached(uid, "saved", lambda: library.all_saved_tracks(sp))
    followed = library.cached(uid, "followed", lambda: library.followed_artists(sp))
    artist_ranks, artist_objects = library.cached(uid, "top_artists", lambda: library.top_ranks(sp, "artists"))
    artists = library.collect_artists(saved, followed, artist_ranks, artist_objects)

    # תגיות מ-Last.fm רק לאמנים בלי ז'אנר מספוטיפיי שאתה עוקב אחריהם או שומע הרבה, כדי שהעמוד ייטען מהר
    need_tags = [a for a in artists if not a["genres"] and (a["followed"] or a["rank"])]
    for a, tags in zip(need_tags, get_tags_for_artists([a["name"] for a in need_tags])):
        a["genres"] = tags

    columns = [("", None), (_("אמן"), "text"), (_("שירים שאהבתי"), "num"),
               (_("הדירוג שלך"), "num"), (_("ז'אנרים"), "text"), (_("עוקב"), "num")]
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

    # בעברית הקופסה האחרונה מוצגת הכי שמאלה
    return page(
        _("<h1>כל האמנים שאני אוהב</h1>")
        + stat_boxes([
            (_("אמנים"), len(artists)),
            (_("בין המובילים שלי"), sum(1 for a in artists if a["rank"])),
            (_("אני עוקב אחריהם"), sum(a["followed"] for a in artists)),
        ])
        + _('<input type="text" class="search" data-table="artists" placeholder="חיפוש אמן או ז\'אנר...">')
        + f'<div class="table-wrap"><table id="artists" class="sortable numbered"><thead>{header(columns)}</thead>'
        + f'<tbody>{"".join(rows)}</tbody></table></div>',
        title=_("כל האמנים שאני אוהב"), wide=True, script=TABLE_JS,
    )


def bar_chart(rows):
    """שורות (שם, כמות) כגרף עמודות אופקיות. העמודה הארוכה ביותר היא 100%."""
    top = max((count for _label, count in rows), default=1) or 1
    return '<div class="bars">' + "".join(
        f'<div class="bar-row"><span>{escape(label)}</span>'
        f'<span class="track"><span class="fill" style="width:{count * 100 // top}%"></span></span>'
        f'<span class="num">{count}</span></div>'
        for label, count in rows
    ) + "</div>"


@app.route("/stats")
def my_stats():
    """גרף ז'אנרים ועשורים, האמנים הכי אהובים, וכרטיס טקסט לשיתוף. מבוסס על השירים שאהבתם."""
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")

    uid = user_id(sp)
    saved = library.cached(uid, "saved", lambda: library.all_saved_tracks(sp))
    if not saved:
        return page(
            _("<h1>הסטטיסטיקות שלי</h1>"
            '<p class="note">עדיין אין שירים שאהבתם בספוטיפיי. שמרו כמה שירים, ואז תופיע כאן התמונה המלאה.</p>')
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
    top_genres = [(_(GENRE_NAMES.get(tag, tag)), c) for tag, c in genre_counts.most_common(10)]
    decade_rows = [(decade_label(decade), c) for decade, c in sorted(decades.items())]

    # הכרטיס בלי אמוג'י (ראו share_card_svg), והטקסט לשיתוף עם אמוג'י
    tiles, lines = [], [_("🎧 ככה נשמע הטעם המוזיקלי שלי"), _("❤️ {a0:,} שירים שאהבתי. אפס חרטות 😎", a0=len(saved))]
    if top_artists:
        tiles.append((_("האמן שהכי אהבתי"), top_artists[0][0]))
        lines.append(_("🎤 האמן שהכי אהבתי: {a0}", a0=top_artists[0][0]))
    if top_genres:
        tiles.append((_("הז'אנר המוביל"), top_genres[0][0]))
        lines.append(_("🎶 הז'אנר המוביל: {a0}", a0=top_genres[0][0]))
    if decades:
        best_decade = decade_label(max(decades.items(), key=lambda kv: kv[1])[0])
        tiles.append((_("העשור האהוב"), best_decade))
        lines.append(_("📅 העשור האהוב: {a0}", a0=best_decade))
    if len(top_artists) >= 3:
        medals = ("🥇", "🥈", "🥉")
        lines.append(_("🏆 הטופ 3 שלי: ") + "  ".join(f"{m} {name}" for m, (name, _count) in zip(medals, top_artists)))
    lines.append(_("👀 חושבים שיש לכם טעם יותר טוב? תוכיחו 👉 {a0}", a0=public_site()))
    card_text = "\n".join(lines)
    theme = current_vibe()["theme"]

    genres_html = (
        bar_chart(top_genres) if top_genres
        else _('<p class="note">עוד אין מספיק תגיות ז\'אנר לאמנים שאהבתם.</p>')
    )
    return page(
        _("<h1>הסטטיסטיקות שלי</h1>")
        + stat_boxes([(_("שירים שאהבתי"), len(saved)), (_("אמנים שונים"), len(artist_counts))])
        + _("<h2>ז'אנרים שאתם הכי אוהבים</h2>")
        + _('<p class="note">לפי התגיות של האמנים שאהבתם. ככל שיש לכם יותר שירים מאמן, הוא שוקל יותר.</p>')
        + genres_html
        + _("<h2>עשורים</h2>")
        + (bar_chart(decade_rows) if decade_rows else _('<p class="note">אין מידע על שנות היציאה.</p>'))
        + _("<h2>האמנים שאהבתם הכי הרבה</h2>")
        + bar_chart(top_artists)
        + _("<h2>📸 כרטיס לשיתוף</h2>")
        + '<div class="share">'
        + share_card_svg(len(saved), tiles, theme)
        + _('<div><p class="note" style="margin-top:0">מוכן לסטורי או לפוסט. שתפו את התמונה, '
        'או העתיקו את הטקסט לוואטסאפ.</p>')
        + '<div class="toolbar">'
        + _('<button type="button" class="btn" id="share-card" hidden>📲 שיתוף</button>')
        + _('<button type="button" class="btn secondary" id="save-card">⬇️ שמירה כתמונה</button></div>')
        + _("<textarea id=\"card-text\" class=\"copy\" readonly aria-label=\"טקסט לשיתוף\">{a0}</textarea>", a0=escape(card_text))
        + _('<div class="toolbar"><button type="button" class="btn secondary" id="copy-card">📋 העתקת טקסט</button></div>')
        + "</div></div>"
        + _('<p><a href="/">חזרה לדף הבית</a></p>'),
        title=_("הסטטיסטיקות שלי"), wide=True, script=COPY_JS + SAVE_CARD_JS,
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
        _("<svg id=\"card-svg\" class=\"share-svg\" xmlns=\"http://www.w3.org/2000/svg\" role=\"img\" aria-label=\"כרטיס הטעם המוזיקלי שלי\" width=\"{a0}\" height=\"{a1}\" viewBox=\"0 0 {a2} {a3}\" direction=\"rtl\" font-family=\"Segoe UI, Arial, sans-serif\"><defs><radialGradient id=\"glow1\" cx=\"0.15\" cy=\"0.1\" r=\"0.75\"><stop offset=\"0\" stop-color=\"{a4}\" stop-opacity=\"0.75\"/><stop offset=\"1\" stop-color=\"{a5}\" stop-opacity=\"0\"/></radialGradient><radialGradient id=\"glow2\" cx=\"0.95\" cy=\"0.75\" r=\"0.7\"><stop offset=\"0\" stop-color=\"{a6}\" stop-opacity=\"0.65\"/><stop offset=\"1\" stop-color=\"{a7}\" stop-opacity=\"0\"/></radialGradient><radialGradient id=\"glow3\" cx=\"0.2\" cy=\"1\" r=\"0.55\"><stop offset=\"0\" stop-color=\"{a8}\" stop-opacity=\"0.45\"/><stop offset=\"1\" stop-color=\"{a9}\" stop-opacity=\"0\"/></radialGradient><linearGradient id=\"card-accent\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"0\"><stop offset=\"0\" stop-color=\"{a10}\"/><stop offset=\"1\" stop-color=\"{a11}\"/></linearGradient></defs><rect width=\"{a12}\" height=\"{a13}\" fill=\"#0f1016\"/><rect width=\"{a14}\" height=\"{a15}\" fill=\"url(#glow1)\"/><rect width=\"{a16}\" height=\"{a17}\" fill=\"url(#glow2)\"/><rect width=\"{a18}\" height=\"{a19}\" fill=\"url(#glow3)\"/><rect x=\"{a20}\" y=\"80\" width=\"300\" height=\"64\" rx=\"32\" fill=\"#ffffff\" fill-opacity=\"0.1\"/>", a0=CARD_WIDTH, a1=CARD_HEIGHT, a2=CARD_WIDTH, a3=CARD_HEIGHT, a4=c1, a5=c1, a6=c2, a7=c2, a8=c3, a9=c3, a10=c1, a11=accent, a12=CARD_WIDTH, a13=CARD_HEIGHT, a14=CARD_WIDTH, a15=CARD_HEIGHT, a16=CARD_WIDTH, a17=CARD_HEIGHT, a18=CARD_WIDTH, a19=CARD_HEIGHT, a20=mid - 150)
        + text(124, 32, _("פלייליסטור"), "#ffffff", "600", "0.9")
        + text(260, 80, _("הטעם המוזיקלי שלי"), "#ffffff", "700")
        + text(450, 180, f"{total:,}", accent, "800")
        + text(520, 44, _("שירים שאהבתי. אפס חרטות."), "#ffffff", "400", "0.78")
        + tile_html
        + bars
        + text(1280, 34, _("חושבים שיש לכם טעם יותר טוב? בדקו בפלייליסטור"), "#ffffff", "600", "0.85")
        + "</svg>"
    )
