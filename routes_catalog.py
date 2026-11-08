"""
פלייליסטים קיימים: הקטלוג, סינון בשרת, 60 כרטיסים בכל פעם, והוספה לספרייה.
"""
from collections import Counter
from html import escape
from flask import redirect, request
import spotipy
from i18n import _
import build_playlists
import catalog
import favourites
import taste
import json
import web
from web import app, cover, csrf_token, page, user_id
from scripts import CATALOG_JS


MARKET_CHIPS = [("", "הכול"), ("US", "🇺🇸 ארצות הברית"), ("IL", "🇮🇱 ישראל (יוצרים ישראלים)")]


# כמה כרטיסים בכל פעם: בטעינת הדף, ובכל לחיצה על "הצג עוד"
CATALOG_PAGE = 60


def filter_catalog(items, cat="", market="", query=""):
    """
    הפלייליסטים שמתאימים לסינון, עם המקום של כל אחד בקטלוג המלא: [(מקום, פלייליסט)].
    ערכים לא מוכרים (קטגוריה או אזור שלא קיימים) לא מסננים כלום.
    """
    cat = cat if cat in catalog.CATEGORY_LABELS else ""
    market = market if market in ("US", "IL") else ""
    query = query.strip().lower()[:60]
    return [
        (rank, item) for rank, item in enumerate(items, 1)
        if (not cat or cat in item["categories"]) and (not market or market in item["markets"])
        and (not query or query in item["name"].lower())
    ]


def catalog_cards(ranked):
    return "".join(catalog_card(rank, item) for rank, item in ranked)


def catalog_card(rank, item):
    pid = escape(item["id"])
    # פלייליסט שעוד לא נמשך לו מספר עוקבים מוצג בלי השורה הזו
    followers = _("{a0} עוקבים", a0=catalog.short_number(item["followers"])) if item["followers"] is not None else None
    return (
        f'<li class="pl-card{f" hot hot{rank}" if rank <= 3 else ""}"><span class="rank">{rank}</span>{cover(item["image"])}<div class="info">'
        f'<div class="title"><a class="sp" href="https://open.spotify.com/playlist/{pid}" target="_blank" rel="noopener">{escape(item["name"])}</a></div>'
        f'<div class="sub">{escape(item["owner"] or "")}</div>{f'<div class="sub">👥 {followers}</div>' if followers else ""}</div>'
        + _('<button type="button" class="btn secondary add" data-id="{a0}">➕ לספרייה</button></li>', a0=pid)
    )


@app.route("/existing-playlists")
def existing_playlists():
    sp = web.get_spotify_client()
    if sp is None:
        return redirect("/login")
    # קטלוג ריק או ישן משבוע מתעדכן ברקע (אם עדכון כבר רץ, זה לא עושה כלום)
    build_playlists.refresh_in_background()
    items = catalog.load()
    back = _('<p><a href="/">חזרה לדף הבית</a></p>')
    if not items:
        return page(
            _("<h1>פלייליסטים קיימים</h1>")
            + _('<p class="note">הקטלוג נבנה ברקע ויתמלא בהדרגה. אם ספוטיפיי מגביל את הבקשות, הבנייה תמשיך אוטומטית כשהמגבלה תיגמר. נסו שוב בעוד כמה דקות.</p>')
            + back,
            title=_("פלייליסטים קיימים"),
        )
    updating = (
        _('<p class="note">הקטלוג מתעדכן ברקע ויתמלא בהדרגה. רעננו את העמוד בעוד כמה דקות.</p>')
        if build_playlists.is_running() or catalog.needs_refresh() else ""
    )
    per_category = Counter(c for item in items for c in item["categories"])
    # נפתח על הקטגוריה של הז'אנר שהמשתמש הכי שומע, אם יש בה פלייליסטים
    favourite = taste.favourite_category(web.auto_vibe().get("genres") or {})
    favourite = favourite if per_category[favourite] else ""
    chip = '<button type="button" class="chip" data-group="{g}" data-value="{v}" aria-pressed="{p}">{t}</button>'
    category_chips = chip.format(g="cat", v="", p=str(not favourite).lower(), t=escape(_("הכול"))) + "".join(
        chip.format(g="cat", v=key, p=str(key == favourite).lower(), t=f"{escape(_(label))} ({per_category[key]})")
        for key, label, _terms in catalog.CATEGORIES if per_category[key]
    )
    market_chips = "".join(
        chip.format(g="market", v=value, p="false" if value else "true", t=escape(_(label)))
        for value, label in MARKET_CHIPS
    )
    first = filter_catalog(items, favourite)
    texts = {
        "count": _("מוצגים {a} מתוך {b}"), "added": _("✓ נוסף · ↩ ביטול"),
        "failed": _("לא הצלחנו להוסיף את הפלייליסט. נסו שוב."),
        "undo_failed": _("לא הצלחנו לבטל את ההוספה. נסו שוב."),
        "load_failed": _("לא הצלחנו לטעון את הפלייליסטים. נסו שוב."),
    }
    return page(
        _("<h1>פלייליסטים קיימים</h1>")
        + _('<p class="note">{a0} הפלייליסטים הגדולים בספוטיפיי, מהגדול לקטן לפי מספר העוקבים. "ישראל" הם פלייליסטים שנוצרו ע"י משתמשים ישראלים (עברית בשם או בתיאור), ו"ארצות הברית" כל השאר. ספוטיפיי לא מפרסם מספר השמעות או מדינה של יוצר, ולכן אלה ההערכות הקרובות ביותר.</p>', a0=len(items))
        + updating
        + f'<div class="chips" role="group">{market_chips}</div><div class="chips" role="group">{category_chips}</div>'
        + _('<input type="text" id="pl-search" class="search" placeholder="חיפוש לפי שם פלייליסט" autocomplete="off">')
        + '<p class="note" id="pl-count"></p>'
        + f'<ul class="list cols" id="pl-grid" data-csrf="{csrf_token()}" data-total="{len(first)}" '
        f'data-shown="{min(len(first), CATALOG_PAGE)}">{catalog_cards(first[:CATALOG_PAGE])}</ul>'
        + '<br><button type="button" class="btn secondary" id="pl-more">' + escape(_("הצג עוד")) + "</button>"
        + back,
        title=_("פלייליסטים קיימים"), wide=True,
        script=CATALOG_JS.replace("__T__", json.dumps(texts, ensure_ascii=False)),
    )


@app.route("/existing-playlists/cards")
def catalog_more_cards():
    """עוד כרטיסים לפי הסינון (קטגוריה, אזור וחיפוש), מ-offset והלאה. משמש את "הצג עוד" ואת הסינון."""
    if web.get_spotify_client() is None:
        return {"html": "", "total": 0, "next": 0}, 401
    matching = filter_catalog(
        catalog.load(), request.args.get("cat", ""), request.args.get("market", ""), request.args.get("q", ""),
    )
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        offset = 0
    chunk = matching[offset:offset + CATALOG_PAGE]
    return {"html": catalog_cards(chunk), "total": len(matching), "next": offset + len(chunk)}


@app.route("/existing-playlists/follow", methods=["POST"])
def follow_catalog_playlist():
    sp = web.get_spotify_client()
    if sp is None:
        return {"ok": False}, 401
    playlist_id = request.form.get("id", "")
    if not favourites.is_spotify_id(playlist_id):
        return {"ok": False}, 400
    try:
        sp.current_user_follow_playlist(playlist_id)
    except spotipy.SpotifyException:
        return {"ok": False}, 502
    return {"ok": True}


@app.route("/existing-playlists/unfollow", methods=["POST"])
def unfollow_catalog_playlist():
    """ביטול הוספה בטעות. רק פלייליסט מהקטלוג שהוא לא של המשתמש עצמו, כדי שלא יימחק פלייליסט אישי."""
    sp = web.get_spotify_client()
    if sp is None:
        return {"ok": False}, 401
    playlist_id = request.form.get("id", "")
    if not favourites.is_spotify_id(playlist_id) or playlist_id not in {item["id"] for item in catalog.load()}:
        return {"ok": False}, 400
    try:
        owner = (sp.playlist(playlist_id, fields="owner.id").get("owner") or {}).get("id")
        if owner == user_id(sp):
            return {"ok": False}, 400
        sp.current_user_unfollow_playlist(playlist_id)
    except spotipy.SpotifyException:
        return {"ok": False}, 502
    return {"ok": True}
