"""קריאת טופס הבנייה (טווחים, עשורים, בחירות) ותצוגות מקדימות בזיכרון."""
import routes_build
from web import app


def form(**data):
    return app.test_request_context("/build", method="POST", data=data)


def test_ranges_only_when_manual_and_valid():
    with form(energy_min="20", energy_max="80"):
        assert routes_build.read_ranges() is None  # בלי סימון כוונון ידני
    data = {"manual": "1", "energy_min": "20", "energy_max": "80",
            "danceability_min": "0", "danceability_max": "60",   # רק גבול עליון
            "valence_min": "50", "valence_max": "100"}          # רק גבול תחתון
    with form(**data):
        assert routes_build.read_ranges() == {
            "energy": (0.2, 0.8), "danceability": (None, 0.6), "valence": (0.5, None)}


def test_ranges_skip_open_inverted_and_garbage_values():
    data = {"manual": "1", "energy_min": "0", "energy_max": "100",   # פתוח לגמרי
            "danceability_min": "70", "danceability_max": "30",     # הפוך
            "valence_min": "abc", "valence_max": "50"}              # לא מספר
    with form(**data):
        assert routes_build.read_ranges() is None
    with form(manual="1", energy_min="-50", energy_max="500"):  # חורג מהטווח: נחתך ל-0..100, כלומר פתוח
        assert routes_build.read_ranges() is None


def test_years_from_decades():
    with form():
        assert routes_build.read_years() is None
    with form(decade_from="1990", decade_to="2000"):
        assert routes_build.read_years() == (1990, 2009)
    with form(decade_from="2000", decade_to="1990"):  # הפוך: מתהפך
        assert routes_build.read_years() == (1990, 2009)
    with form(decade_from="1980"):  # עשור אחד פותח את הטווח
        low, high = routes_build.read_years()
        assert low == 1980 and high >= 2020
    with form(decade_from="1993", decade_to="x"):  # לא עשור מהתפריט
        assert routes_build.read_years() is None


def test_criteria_accept_only_menu_values_and_clamp_count():
    with form(genre="  pop  ", mood="לא קיים", event="לא קיים", language="klingon", count="9999"):
        criteria = routes_build.read_criteria()
    assert criteria["genre"] == "pop" and criteria["mood"] == "" and criteria["event"] == ""
    assert criteria["language"] == "ביחד" and criteria["count"] == routes_build.MAX_TRACKS
    with form(count="1"):
        assert routes_build.read_criteria()["count"] == 5
    with form(count="many"):
        assert routes_build.read_criteria()["count"] == 20
    with form(genre_choice="x" * 200):
        assert len(routes_build.read_criteria()["genre"]) == 60


def test_israeli_genre_defaults_to_hebrew_unless_language_chosen():
    with form(genre="israeli-pop"):
        assert routes_build.read_criteria()["language"] == "עברית"
    with form(genre="mizrahi"):
        assert routes_build.read_criteria()["language"] == "עברית"
    other = next(lang for lang in routes_build.LANGUAGES if lang not in ("ביחד", "עברית"))
    with form(genre="mizrahi", language=other):
        assert routes_build.read_criteria()["language"] == other
    with form(genre="mizrahi", source="liked"):
        assert routes_build.read_criteria()["source"] == "liked"


def test_previews_expire_are_capped_and_forgotten_per_user(monkeypatch):
    routes_build._previews.clear()
    track = {"uri": "spotify:track:1"}
    old = routes_build.remember_preview("u1", {}, [track])
    routes_build._previews[old]["at"] -= routes_build.PREVIEW_SECONDS + 1
    fresh = routes_build.remember_preview("u2", {}, [track])
    assert old not in routes_build._previews and fresh in routes_build._previews
    monkeypatch.setattr(routes_build, "PREVIEW_LIMIT", 3)
    for _ in range(5):
        routes_build.remember_preview("u1", {}, [track])
    assert len(routes_build._previews) == 3
    routes_build.forget_previews("u1")
    assert all(p["uid"] != "u1" for p in routes_build._previews.values())
