"""דף הבית, אמנים ושירים אהובים, והתחברות."""
import routes_home
import web

ARTIST = "a" * 22
TRACK = "t" * 22


def test_favourites_search_and_recommendations(logged_in):
    client, _sp, _csrf = logged_in
    found = client.get("/favourites?q=Adele").get_data(as_text=True)
    # האמן המזויף כבר מועקב, ולכן מסומן "✓ עוקב" בלי כפתור
    assert "Adele" in found and "✓ עוקב" in found
    assert client.get("/favourites").status_code == 200


def test_follow_artist_and_save_track(logged_in):
    client, sp, csrf = logged_in
    response = client.post("/favourites/artist", data={"csrf": csrf, "id": ARTIST, "q": "Adele"})
    assert response.headers["Location"] == "/favourites?q=Adele"
    client.post("/favourites/track", data={"csrf": csrf, "id": TRACK})
    assert ("follow_artist", ARTIST) in sp.calls and ("save_track", TRACK) in sp.calls


def test_favourites_ignore_invalid_ids(logged_in):
    client, sp, csrf = logged_in
    client.post("/favourites/artist", data={"csrf": csrf, "id": "bad id"})
    client.post("/favourites/track", data={"csrf": csrf, "id": "x"})
    assert not [c for c in sp.calls if c[0] in ("follow_artist", "save_track")]


def test_old_permissions_need_new_login(logged_in):
    client, _sp, _csrf = logged_in
    with client.session_transaction() as s:
        s["scope"] = "old"
    assert client.get("/favourites").headers["Location"].endswith("/login")
    html = client.get("/").get_data(as_text=True)
    assert 'href="/login"' in html


def test_callback_rejects_wrong_state_and_failed_login(client, monkeypatch):
    with client.session_transaction() as s:
        s["oauth_state"] = "good"
    assert client.get("/callback?code=c&state=evil").status_code == 400

    class Failing:
        def get_access_token(self, code, check_cache=False):
            raise routes_home.SpotifyOauthError("denied")
    monkeypatch.setattr(routes_home, "make_auth", lambda: Failing())
    with client.session_transaction() as s:
        s["oauth_state"] = "good"
    assert client.get("/callback?code=c&state=good").status_code == 400
    with client.session_transaction() as s:
        assert "token_info" not in s


def test_login_redirects_to_spotify_with_state(client):
    response = client.get("/login")
    assert response.status_code == 302 and "accounts.spotify.com" in response.headers["Location"]
    with client.session_transaction() as s:
        assert s["oauth_state"] in response.headers["Location"]


def test_logout_clears_session(logged_in):
    client, _sp, _csrf = logged_in
    client.get("/logout")
    with client.session_transaction() as s:
        assert "token_info" not in s
    assert web.SCOPE  # המודול עדיין נטען
