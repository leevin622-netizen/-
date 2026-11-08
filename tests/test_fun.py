"""אפקטי הכיף: אימוג'ים צפים ברקע, וקונפטי בלחיצה."""
import themes
from scripts import FUN_JS


def test_every_theme_has_floating_emojis():
    for theme in themes.THEMES:
        html = themes.emoji_html(theme)
        assert html.count('class="emoji-float"') == 8
        assert 'aria-hidden="true"' in html


def test_background_has_emoji_layer_with_and_without_images():
    assert "emoji-layer" in themes.background_html([], "rock")
    assert "emoji-layer" in themes.background_html(["https://img/1"], "pop")


def test_pages_include_confetti_script(client):
    html = client.get("/").get_data(as_text=True)
    assert FUN_JS in html and "emoji-layer" in html


def test_confetti_respects_reduced_motion():
    assert "prefers-reduced-motion: reduce" in FUN_JS


def test_bar_chart_marks_the_row_with_the_most_not_the_first():
    from routes_library import bar_chart
    # עשורים מסודרים לפי זמן: ה-70 הוא הראשון אבל 2010 הוא המוביל
    html = bar_chart([("70s", 4), ("90s", 6), ("2010s", 12), ("2020s", 3)])
    assert html.count("bar-row top") == 1
    assert html.index("bar-row top") < html.index("2010s") < html.index("2020s")
    assert html.index("70s") < html.index("bar-row top")


def test_bar_chart_ties_and_equal_rows():
    from routes_library import bar_chart
    assert bar_chart([("a", 5), ("b", 5), ("c", 2)]).count("bar-row top") == 2
    assert bar_chart([("a", 3), ("b", 3)]).count("bar-row top") == 0
    assert bar_chart([("a", 3)]).count("bar-row top") == 1


def test_saved_tracks_script_marks_top_three_ranks():
    from scripts import SAVED_JS
    assert 't[8] >= 1 && t[8] <= 3' in SAVED_JS and '"hot hot"' in SAVED_JS


def test_my_artists_marks_top_three_with_medal_classes(logged_in):
    client, _sp, _csrf = logged_in
    html = client.get("/my-artists").get_data(as_text=True)
    assert 'class="hot hot1"' in html and 'class="hot hot3"' in html and 'class="hot hot4"' not in html


def test_top_three_catalog_cards_are_marked(logged_in):
    from tests.test_lighter_pages import fill
    client, _sp, _csrf = logged_in
    fill()
    html = client.get("/existing-playlists").get_data(as_text=True)
    assert html.count("pl-card hot hot") == 3 and 'pl-card hot hot1"' in html and 'pl-card hot hot4' not in html


def test_biggest_of_my_playlists_is_marked(logged_in, monkeypatch):
    import routes_playlists
    client, _sp, _csrf = logged_in
    small = {"id": "a" * 22, "name": "Small", "images": [], "items": {"total": 2}}
    big = {"id": "b" * 22, "name": "Big", "images": [], "items": {"total": 40}}
    monkeypatch.setattr(routes_playlists, "cached_app_playlists", lambda sp: [small, big])
    html = client.get("/my-playlists").get_data(as_text=True)
    assert html.count('class="hot hot1"') == 1 and html.index("Small") < html.index('class="hot hot1"') < html.index("Big")
    monkeypatch.setattr(routes_playlists, "cached_app_playlists", lambda sp: [big])
    assert "hot hot1" not in client.get("/my-playlists").get_data(as_text=True)


def test_first_recommendation_is_marked_but_search_results_are_not(logged_in):
    client, _sp, _csrf = logged_in
    html = client.get("/favourites").get_data(as_text=True)
    assert 'class="hot hot-rec"' in html
    assert 'class="hot hot-rec"' not in client.get("/favourites?q=abc").get_data(as_text=True)
