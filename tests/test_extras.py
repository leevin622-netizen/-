"""תוספות: פרופיל מוזיקלי בסטטיסטיקות, ייצוא, "מתנגן עכשיו", מסע אנרגיה, "שוב כמו מקודם", ושירים כפולים."""
import routes_build
import routes_library
import routes_playlists
import taste
from conftest import PLAYLIST_ID
from i18n import JS_TEXTS
from scripts import EXPORT_JS, LAZY_PLAY_JS, SAVED_JS, SORT_JS
from translations import TRANSLATIONS

FEATURES = {"energy": 0.8, "danceability": 0.7, "valence": 0.6, "acousticness": 0.1, "tempo": 124.0}


def test_mood_profile_needs_enough_tracks_and_averages_the_rest():
    assert taste.mood_profile([FEATURES] * 9 + [None] * 50) is None
    quiet = dict(FEATURES, energy=0.2, valence=None)
    profile = taste.mood_profile([FEATURES] * 10 + [quiet] * 10 + [None])
    assert profile["tracks"] == 20 and round(profile["energy"], 2) == 0.5
    assert round(profile["valence"], 2) == 0.6      # שיר בלי valence לא נכנס לממוצע של valence
    assert round(profile["tempo"]) == 124


def test_personality_and_mainstream_labels_are_translated():
    cases = [(0.8, 0.7, "🎉"), (0.8, 0.3, "🔥"), (0.3, 0.3, "🌙"), (0.3, 0.7, "😌"), (0.55, 0.5, "🎧"), (None, None, "🎧")]
    for energy, valence, emoji in cases:
        found, name, text = taste.personality({"energy": energy, "valence": valence})
        assert found == emoji and TRANSLATIONS[name]["en"] and TRANSLATIONS[text]["en"]
    assert taste.mainstream([50] * 9) is None
    assert taste.mainstream([80] * 10 + [None] * 5)[:2] == (80, "📻")
    assert taste.mainstream([50] * 10)[1] == "🎯" and taste.mainstream([10] * 10)[1] == "💎"
    for popularity in (80, 50, 10):
        _average, _emoji, name, text = taste.mainstream([popularity] * 10)
        assert TRANSLATIONS[name]["en"] and TRANSLATIONS[text]["en"]


def test_stats_page_shows_profile_when_features_exist(logged_in, monkeypatch):
    client, sp, _csrf = logged_in
    for track in sp.tracks:
        track["popularity"] = 30
    asked = []

    def features(ids):
        asked.append(len(ids))
        return {i: FEATURES for i in ids}

    monkeypatch.setattr(routes_library, "get_features", features)
    html = client.get("/stats").get_data(as_text=True)
    assert asked == [routes_library.PROFILE_SAMPLE]     # רק השירים האחרונים, לא כל הספרייה
    assert "הפרופיל המוזיקלי שלי" in html and "נשמת המסיבה" in html and "width:80%" in html
    assert "124 BPM" in html and "מיינסטרים: 30%" in html and "ציידי פנינים" in html
    # בפעם השנייה הפרופיל מגיע מהמטמון, בלי לבקש שוב
    client.get("/stats")
    assert len(asked) == 1


def test_stats_page_without_features_has_no_profile_and_retries(logged_in, monkeypatch):
    client, _sp, _csrf = logged_in
    asked = []
    monkeypatch.setattr(routes_library, "get_features", lambda ids: asked.append(1) or {})
    for _ in range(2):
        response = client.get("/stats")
        assert response.status_code == 200 and "הפרופיל המוזיקלי שלי" not in response.get_data(as_text=True)
    assert len(asked) == 2      # כישלון לא נשמר, ולכן מנסים שוב בכניסה הבאה


def test_saved_tracks_page_has_export_and_youtube(logged_in):
    client, _sp, _csrf = logged_in
    html = client.get("/saved-tracks").get_data(as_text=True)
    assert 'data-export="tracks"' in html and 'data-kind="copy"' in html and 'data-kind="csv"' in html
    assert "playlistor.csv" in html and '"youtube": "חיפוש ביוטיוב"' in html
    assert "youtube.com/results?search_query=" in SAVED_JS and "encodeURIComponent" in SAVED_JS


def test_export_script_handles_csv_quotes_and_hebrew():
    assert "0xFEFF" in EXPORT_JS            # BOM, כדי שאקסל יזהה עברית
    assert 'replace(/"/g, \'""\')' in EXPORT_JS
    assert "__X__" in EXPORT_JS and "__X__" not in routes_library.export_js()


def test_artists_page_has_youtube_links(logged_in):
    client, _sp, _csrf = logged_in
    html = client.get("/my-artists").get_data(as_text=True)
    assert html.count('class="yt"') >= 7 and "search_query=Artist+1" in html


def test_now_playing_bar_and_its_text_are_translated():
    assert "now-bar" in LAZY_PLAY_JS and "now-progress" in LAZY_PLAY_JS and "עצירת ההשמעה" in LAZY_PLAY_JS
    assert "עצירת ההשמעה" in JS_TEXTS and TRANSLATIONS["עצירת ההשמעה"]["en"]
    assert "if (now) now.hidden = true;" in LAZY_PLAY_JS


def build(client, csrf, **data):
    return client.post("/build", data={"csrf": csrf, "count": "8", **data})


def test_preview_has_summary_export_and_energy_journey(logged_in, monkeypatch):
    client, _sp, csrf = logged_in
    html = build(client, csrf, genre_choice="rock").get_data(as_text=True)
    assert 'class="note summary"' in html and "דקות" in html and "אמנים" in html
    assert 'data-export="playlist"' in html
    assert html.index("</form>") < html.index('data-export="playlist"') < html.index('<a href="/build">התחלה מחדש')
    # בלי נתוני אווירה אין מה למיין לפי אנרגיה
    assert 'value="flow"' not in html
    monkeypatch.setattr(routes_build, "get_features", lambda ids: {i: FEATURES for i in ids})
    html = build(client, csrf, genre_choice="rock").get_data(as_text=True)
    assert 'value="flow"' in html and "אנרגיה ממוצעת 80%" in html and "124 BPM" in html
    assert html.index('value="valence"') < html.index('value="flow"') < html.index('id="shuffle"')
    assert 'key === "flow"' in SORT_JS


def test_preview_extras_also_work_in_english(logged_in, monkeypatch):
    client, _sp, csrf = logged_in
    monkeypatch.setattr(routes_build, "get_features", lambda ids: {i: FEATURES for i in ids})
    client.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/"})
    html = build(client, csrf, genre_choice="rock").get_data(as_text=True)
    assert "Energy journey" in html and "Copy the list" in html and "Average energy 80%" in html


def test_recent_builds_card_on_home_page(logged_in):
    client, _sp, csrf = logged_in
    assert "שוב כמו מקודם" not in client.get("/").get_data(as_text=True)
    build(client, csrf, genre_choice="rock", mood="שמח", event="ריצה")
    build(client, csrf, mood="רגוע")
    build(client, csrf, genre_choice="rock", mood="שמח", event="ריצה")     # אותה בחירה: עוברת לראש, לא מוכפלת
    html = client.get("/").get_data(as_text=True)
    assert "שוב כמו מקודם" in html
    card = html[html.index('class="card for-you recent"'):html.index('<div class="menu">')]
    assert card.count("<form") == 2
    assert card.index(" · שמח · ריצה<") < card.index(">רגוע<")
    assert 'name="mood" value="שמח"' in card and 'name="event" value="ריצה"' in card and 'name="genre" value="rock"' in card


def test_recent_builds_keeps_three_and_survives_bad_session_data(logged_in):
    client, _sp, csrf = logged_in
    for mood in ("שמח", "עצוב", "רגוע", "רומנטי"):
        build(client, csrf, mood=mood)
    with client.session_transaction() as session:
        assert [r["mood"] for r in session["recent"]] == ["רומנטי", "רגוע", "עצוב"]
        session["recent"] = ["junk", {"mood": "<b>"}, {"genre": "<script>", "count": "x"}]
    html = client.get("/").get_data(as_text=True)
    assert "<script>" not in html.split('<div class="menu">')[0].split("for-you recent")[-1]
    assert client.get("/").status_code == 200


def test_recent_button_builds_a_playlist(logged_in):
    client, _sp, csrf = logged_in
    response = client.post("/build", data={"csrf": csrf, "genre": "rock", "mood": "שמח", "event": "",
                                           "language": "ביחד", "source": "search", "count": "8", "personal": "on"})
    assert response.status_code == 200 and "שירים בשבילך" in response.get_data(as_text=True)


def test_duplicate_positions_by_id_or_by_name_and_artist():
    def track(track_id, name, artist):
        return {"id": track_id, "name": name, "artists": [{"name": artist}]}
    tracks = [track("a", "Song", "X"), track("b", "Other", "X"), None, track("a", "Song", "X"),
              track("c", "song ", "x"), track("d", "Song", "Y"), track(None, "Other", "X")]
    assert routes_playlists.duplicate_positions(tracks) == {3, 4, 6}
    assert routes_playlists.duplicate_positions([]) == set()


def test_edit_page_marks_duplicates(logged_in):
    client, sp, _csrf = logged_in
    html = client.get(f"/playlist/{PLAYLIST_ID}").get_data(as_text=True)
    assert "dup-badge" not in html and "שירים כפולים" not in html
    sp.playlist_items = lambda *a, **k: {"items": [{"track": t} for t in sp.tracks[:2] + sp.tracks[:1]], "next": None}
    html = client.get(f"/playlist/{PLAYLIST_ID}").get_data(as_text=True)
    assert html.count("dup-badge") == 1 and "נמצאו 1 שירים כפולים" in html
    assert '<li data-position="2" class="dup">' in html and '<li data-position="0">' in html
