"""כל דפי האתר: נטענים, מגינים על טפסים, ובונים ושומרים פלייליסט (מול ספוטיפיי מזויף)."""
import pytest

import catalog
from conftest import PLAYLIST_ID

PAGES = ["/", "/build", "/saved-tracks", "/my-artists", "/stats", "/existing-playlists", "/my-playlists",
         "/playlist/" + PLAYLIST_ID, "/favourites"]


def build_form(csrf, **values):
    form = {"csrf": csrf, "source": "search", "genre_choice": "pop", "mood": "", "event": "",
            "language": "ביחד", "count": "20"}
    form.update(values)
    return form


def test_home_logged_out_shows_login(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/login"' in response.get_data(as_text=True)


@pytest.mark.parametrize("path", PAGES[1:])
def test_pages_need_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


@pytest.mark.parametrize("path", PAGES)
def test_every_page_loads(logged_in, path):
    client, _sp, _csrf = logged_in
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]


@pytest.mark.parametrize("path", ["/build", "/save", "/lang", "/delete-data", "/existing-playlists/follow", "/existing-playlists/unfollow"])
def test_post_without_csrf_is_rejected(logged_in, path):
    client, _sp, _csrf = logged_in
    assert client.post(path, data={"csrf": "wrong"}).status_code == 400


def test_build_needs_genre_mood_or_event(logged_in):
    client, _sp, csrf = logged_in
    response = client.post("/build", data=build_form(csrf, genre_choice=""))
    assert response.status_code == 400


def test_build_shows_requested_number_of_songs(logged_in):
    client, _sp, csrf = logged_in
    html = client.post("/build", data=build_form(csrf, count="25")).get_data(as_text=True)
    assert html.count('name="uri"') == 25
    assert 'class="list numbered' in html


def test_build_more_adds_new_songs(logged_in):
    client, _sp, csrf = logged_in
    html = client.post("/build", data=build_form(csrf, count="10")).get_data(as_text=True)
    token = html.split('name="preview" value="')[1].split('"')[0]
    uris = [part.split('"')[0] for part in html.split('name="uri" value="')[1:]]
    more = client.post("/build/more", data={"csrf": csrf, "preview": token, "uri": uris, "title": "x"})
    more_uris = [part.split('"')[0] for part in more.get_data(as_text=True).split('name="uri" value="')[1:]]
    assert len(more_uris) == 20 and len(set(more_uris)) == 20
    assert more_uris[:10] == uris


def test_save_creates_playlist_with_chosen_songs(logged_in):
    client, sp, csrf = logged_in
    uris = [f"spotify:track:{n}" for n in range(1, 8)]
    response = client.post("/save", data={"csrf": csrf, "title": "Test", "uri": uris + ["javascript:alert(1)"]})
    assert response.status_code == 200
    assert ("create", "Test") in sp.calls
    assert ("add", "newplaylist", 7) in sp.calls


def test_existing_playlists_with_catalog(logged_in):
    client, sp, csrf = logged_in
    catalog.add_candidates([{"id": "p" * 22, "name": "Top Hits", "owner": "o", "image": ""}], "US", "hits")
    catalog.add_candidates([{"id": "q" * 22, "name": "להיטים", "owner": "o", "image": ""}], "IL", "hits")
    catalog.select_top()
    html = client.get("/existing-playlists").get_data(as_text=True)
    assert "Top Hits" in html and "להיטים" in html
    assert 'data-group="cat"' in html and 'data-value="IL"' in html

    assert client.post("/existing-playlists/follow", data={"csrf": csrf, "id": "bad id"}).status_code == 400
    response = client.post("/existing-playlists/follow", data={"csrf": csrf, "id": "p" * 22})
    assert response.get_json() == {"ok": True}
    assert ("follow", "p" * 22) in sp.calls


def test_language_switch_to_english(logged_in):
    client, _sp, csrf = logged_in
    client.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/build"})
    html = client.get("/build").get_data(as_text=True)
    assert 'dir="ltr"' in html
    assert "צור פלייליסט" not in html


def test_language_switch_ignores_unknown_and_external_redirect(logged_in):
    client, _sp, csrf = logged_in
    response = client.post("/lang", data={"csrf": csrf, "lang": "fr", "back": "//evil.example"})
    assert response.headers["Location"] == "/"
    assert 'dir="rtl"' in client.get("/build").get_data(as_text=True)


def test_build_form_shows_only_genre_mood_and_button(logged_in):
    client, _sp, _csrf = logged_in
    html = client.get("/build").get_data(as_text=True)
    visible, folded = html.split('<details class="more-options">')
    folded = folded.split("</details>")[0]
    for name in ("genre_choice", "mood"):
        assert f'name="{name}"' in visible
    assert 'type="submit"' in html.split("</details>")[1]
    for name in ("event", "source", "language", "decade_from", "decade_to", "count", "personal"):
        assert f'name="{name}"' in folded and f'name="{name}"' not in visible


def test_build_with_event_only(logged_in):
    client, _sp, csrf = logged_in
    response = client.post("/build", data=build_form(csrf, genre_choice="", event="ריצה", count="10"))
    assert response.status_code == 200
    assert response.get_data(as_text=True).count('name="uri"') == 10


def test_build_with_defaults_from_folded_options(logged_in):
    """מי שלא פותח את "אפשרויות נוספות" שולח רק ז'אנר ומצב רוח, ומקבל את ברירות המחדל."""
    client, _sp, csrf = logged_in
    form = {"csrf": csrf, "genre_choice": "pop", "mood": "", "event": "", "source": "search",
            "language": "ביחד", "count": "20", "personal": "on", "decade_from": "", "decade_to": ""}
    assert client.post("/build", data=form).get_data(as_text=True).count('name="uri"') == 20
