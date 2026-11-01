"""פלייליסטים קיימים בחלקים של 60, דחיסת העמודים, ואסימון טפסים שמשתנה בכל עמוד."""
import gzip

import app as app_module
import catalog


def fill(us=100, il=100):
    catalog.add_candidates(
        [{"id": f"us{n:020d}", "name": f"Top Hits {n}", "owner": "o", "image": ""} for n in range(us)], "US", "hits")
    catalog.add_candidates(
        [{"id": f"il{n:020d}", "name": f"להיטים {n}", "owner": "o", "image": ""} for n in range(il)], "IL", "israeli")
    catalog.select_top()


def test_page_sends_only_first_cards(logged_in):
    client, _sp, _csrf = logged_in
    fill()
    html = client.get("/existing-playlists").get_data(as_text=True)
    assert html.count('class="pl-card"') == app_module.CATALOG_PAGE
    assert 'data-total="200"' in html and 'data-shown="60"' in html


def test_more_cards_continue_from_offset(logged_in):
    client, _sp, _csrf = logged_in
    fill()
    data = client.get("/existing-playlists/cards?offset=180").get_json()
    assert data["total"] == 200 and data["next"] == 200
    assert data["html"].count('class="pl-card"') == 20
    assert '<span class="rank">181</span>' in data["html"]


def test_filters_on_server(logged_in):
    client, _sp, _csrf = logged_in
    fill()
    assert client.get("/existing-playlists/cards?market=IL").get_json()["total"] == 100
    assert client.get("/existing-playlists/cards?cat=hits").get_json()["total"] == 100
    assert client.get("/existing-playlists/cards?market=IL&cat=hits").get_json()["total"] == 0
    found = client.get("/existing-playlists/cards?q=HITS 1").get_json()
    assert found["total"] == 11 and "Top Hits 15" in found["html"]
    # ערכים לא מוכרים לא מסננים, ו-offset לא תקין מתחיל מההתחלה
    assert client.get("/existing-playlists/cards?cat=nope&market=XX&offset=abc").get_json()["total"] == 200


def test_more_cards_need_login(client):
    assert client.get("/existing-playlists/cards").status_code == 401


def test_pages_are_compressed(logged_in):
    client, _sp, _csrf = logged_in
    fill()
    plain = client.get("/existing-playlists")
    packed = client.get("/existing-playlists", headers={"Accept-Encoding": "gzip, br"})
    assert packed.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in packed.headers["Vary"]
    assert len(packed.data) < len(plain.data) / 3
    assert gzip.decompress(packed.data).count(b'class="pl-card"') == 60


def test_small_responses_not_compressed(logged_in):
    client, _sp, _csrf = logged_in
    response = client.get("/existing-playlists/cards?q=nothing", headers={"Accept-Encoding": "gzip"})
    assert "Content-Encoding" not in response.headers


def page_token(client):
    html = client.get("/build").get_data(as_text=True)
    return html.split('name="csrf" value="')[1].split('"')[0]


def test_form_token_changes_every_page_and_still_works(logged_in):
    client, _sp, _csrf = logged_in
    first, second = page_token(client), page_token(client)
    assert first != second
    for token in (first, second):
        response = client.post("/lang", data={"csrf": token, "lang": "en"})
        assert response.status_code == 302


def test_tampered_token_rejected(logged_in):
    client, _sp, _csrf = logged_in
    token = page_token(client)
    tampered = token[:-2] + ("00" if token[-2:] != "00" else "11")
    assert client.post("/lang", data={"csrf": tampered, "lang": "en"}).status_code == 400
    assert client.post("/lang", data={"csrf": "abc", "lang": "en"}).status_code == 400
