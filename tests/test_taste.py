"""התאמה אישית לפי הז'אנרים שהמשתמש הכי שומע."""
import pytest

import app as app_module
import catalog
import engine
import taste
from conftest import FakeSpotify

TASTE = {"theme": "default", "images": [], "genres": {"israeli pop": 50, "rock": 20, "latin": 5}, "artist_tags": {}}


@pytest.fixture
def with_taste(logged_in, monkeypatch):
    monkeypatch.setattr(app_module, "auto_vibe", lambda: TASTE)
    return logged_in


def test_genres_of_picks_most_specific():
    assert engine.genres_of(["israeli pop"]) == {"israeli pop"}
    assert engine.genres_of(["pop", "israeli rock"]) == {"pop", "israeli rock"}
    assert engine.genres_of(["polka"]) == set()


def test_genre_scores_sorted_by_weight():
    scores = taste.genre_scores([(10, ["rock"]), (30, ["israeli pop"]), (15, ["album rock", "mizrahi"])])
    assert list(scores) == ["israeli pop", "rock", "mizrahi"]
    assert scores["rock"] == 25
    assert taste.top_genres(scores, 2) == ["israeli pop", "rock"]


def test_favourite_category_skips_genres_without_category():
    assert taste.favourite_category({"latin": 99, "rock": 1}) == "rock"
    assert taste.favourite_category({"latin": 99}) == ""
    assert taste.favourite_category({}) == ""


def test_personal_artists_only_from_chosen_genre():
    sp = FakeSpotify()
    engine.find_personal_tracks(sp, "ביחד", 10, set(), genre="rock")
    searched = {q for kind, q, _offset in sp.calls if kind == "search"}
    rock = {f'artist:"{sp.artist(n)["name"]}"' for n in range(7) if n % 2 == 0}
    assert searched and searched <= rock


def test_personal_artists_tags_used_when_spotify_has_no_genres():
    sp = FakeSpotify()
    sp.artist = lambda n: {"id": f"artist{n}", "name": f"Artist {n}", "genres": [], "images": []}
    engine.find_personal_tracks(sp, "ביחד", 10, set(), genre="mizrahi", artist_tags={"artist3": ["mizrahi"]})
    assert {q for kind, q, _o in sp.calls if kind == "search"} == {'artist:"Artist 3"'}


def test_home_shows_for_you_buttons(with_taste):
    client, _sp, _csrf = with_taste
    html = client.get("/").get_data(as_text=True)
    assert 'class="card for-you"' in html
    assert 'name="genre_choice" value="israeli pop"' in html
    assert 'value="rock"' in html


def test_home_without_taste_has_no_for_you(logged_in):
    client, _sp, _csrf = logged_in
    assert "for-you" not in client.get("/").get_data(as_text=True)


def test_for_you_button_builds_playlist(with_taste):
    client, _sp, csrf = with_taste
    form = {"csrf": csrf, "source": "search", "language": "ביחד", "count": "30", "personal": "on",
            "genre_choice": "israeli pop"}
    html = client.post("/build", data=form).get_data(as_text=True)
    assert html.count('name="uri"') == 30


def test_build_form_preselects_top_genre(with_taste):
    client, _sp, _csrf = with_taste
    assert '<option value="israeli pop" selected>' in client.get("/build").get_data(as_text=True)


def test_existing_playlists_open_on_favourite_category(with_taste):
    client, _sp, _csrf = with_taste
    catalog.add_candidates([{"id": "p" * 22, "name": "להיטים", "owner": "o", "image": ""}], "IL", "israeli")
    catalog.add_candidates([{"id": "q" * 22, "name": "Rock", "owner": "o", "image": ""}], "US", "rock")
    catalog.select_top()
    html = client.get("/existing-playlists").get_data(as_text=True)
    assert 'data-group="cat" data-value="israeli" aria-pressed="true"' in html
    assert 'data-group="cat" data-value="" aria-pressed="false"' in html
