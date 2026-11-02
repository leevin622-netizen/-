"""תיקונים: חזרה בטוחה, רענון מוגבל, התחברות בלי המתנה, מטמונים שחוסכים בקשות לספוטיפיי, וסמל לאתר."""
import json
import os
import time

import build_playlists
import lastfm
import library
import web
from conftest import PLAYLIST_ID


def test_local_path_only_inside_the_site():
    assert web.local_path("/build?x=1") == "/build?x=1"
    for bad in ("//evil.example", "/\\evil.example", "https://evil.example", "", None, "/a\nb"):
        assert web.local_path(bad) == "/"


def test_refresh_returns_only_to_this_site(logged_in):
    client, _sp, _csrf = logged_in
    outside = client.get("/refresh", headers={"Referer": "https://evil.example/x"})
    assert outside.headers["Location"] == "/"
    with client.session_transaction() as s:
        s.pop("refreshed_at", None)
    inside = client.get("/refresh", headers={"Referer": "http://localhost/stats?x=1"})
    assert inside.headers["Location"] == "/stats?x=1"


def test_refresh_at_most_every_ten_minutes(logged_in, monkeypatch):
    client, _sp, _csrf = logged_in
    cleared = []
    monkeypatch.setattr(library, "clear_cache", lambda uid: cleared.append(uid))
    client.get("/refresh")
    client.get("/refresh")
    assert cleared == ["tester"]


def test_user_client_never_waits_for_spotify():
    sp = web.user_client("token")
    assert sp.retries == 0 and sp.requests_timeout == 10


def test_login_images_from_recent_file_without_spotify(client, monkeypatch):
    web._write_login_file(["https://img/1", "https://img/2"])
    monkeypatch.setattr(web, "SpotifyClientCredentials", lambda **kw: (_ for _ in ()).throw(AssertionError("Spotify")))
    assert web.login_images() == ["https://img/1", "https://img/2"]


def test_login_images_skip_spotify_while_limited(client, monkeypatch):
    web._write_login_file(["https://img/old"])
    old = time.time() - web.LOGIN_SECONDS - 10
    os.utime(web._login_file(), (old, old))
    build_playlists.remember_block(5000)
    monkeypatch.setattr(web, "SpotifyClientCredentials", lambda **kw: (_ for _ in ()).throw(AssertionError("Spotify")))
    assert web.login_images() == ["https://img/old"]


class Reply:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_lastfm_tags_saved_to_file(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "k")
    replies = {"Rock Band": {"toptags": {"tag": [{"name": "rock"}]}}, "Nobody": {"error": lastfm.NOT_FOUND},
               "Busy": {"error": 29}}
    asked = []

    def fake_get(url, params, timeout):
        asked.append(params["artist"])
        return Reply(replies[params["artist"]])
    monkeypatch.setattr(lastfm.requests, "get", fake_get)
    assert lastfm.get_tags_for_artists(["Rock Band", "Nobody", "Busy"]) == [["rock"], [], []]
    with open(lastfm.TAGS_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"Rock Band": ["rock"], "Nobody": []}

    # אחרי הפעלה מחדש: מהקובץ. רק "Busy", שנכשל בפעם הקודמת, נשאל שוב
    monkeypatch.setattr(lastfm, "_tags_cache", None)
    asked.clear()
    lastfm.get_tags_for_artists(["Rock Band", "Nobody", "Busy"])
    assert asked == ["Busy"]


def test_my_playlists_cached_until_something_changes(logged_in, monkeypatch):
    client, sp, csrf = logged_in
    calls = []
    original = sp.current_user_playlists

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(sp, "current_user_playlists", counted)
    sp.playlist_change_details = lambda *a, **k: None
    client.get("/my-playlists")
    client.get("/my-playlists")
    assert len(calls) == 1
    client.post(f"/playlist/{PLAYLIST_ID}/rename", data={"csrf": csrf, "name": "New"})
    client.get("/my-playlists")
    assert len(calls) == 2
    client.post("/save", data={"csrf": csrf, "title": "T", "uri": ["spotify:track:1"]})
    client.get("/my-playlists")
    assert len(calls) == 3


def test_favicon_in_page_and_unknown_paths_do_not_pause_background(client):
    assert '<link rel="icon" href="data:image/svg+xml' in client.get("/").get_data(as_text=True)
    build_playlists._state["user_at"] = 0.0
    assert client.get("/favicon.ico").status_code == 404
    assert not build_playlists.users_active()


FETCH = {"X-Requested-With": "fetch"}


def test_playlist_edits_from_script_answer_json(logged_in):
    client, sp, csrf = logged_in
    base = f"/playlist/{PLAYLIST_ID}"
    html = client.get(base).get_data(as_text=True)
    assert 'id="pl-edit"' in html and 'id="pl-size"' in html
    moved = client.post(f"{base}/move", data={"csrf": csrf, "position": "1", "direction": "up"}, headers=FETCH)
    assert moved.get_json() == {"ok": True} and ("reorder", 1, 0) in sp.calls
    removed = client.post(f"{base}/remove", data={"csrf": csrf, "position": "2", "uri": "spotify:track:3"},
                          headers=FETCH)
    assert removed.get_json() == {"ok": True} and ("remove", "spotify:track:3", 2) in sp.calls


def test_invalid_playlist_edit_from_script_fails_without_calling_spotify(logged_in):
    client, sp, csrf = logged_in
    base = f"/playlist/{PLAYLIST_ID}"
    response = client.post(f"{base}/move", data={"csrf": csrf, "position": "0", "direction": "up"}, headers=FETCH)
    assert response.status_code == 400 and response.get_json() == {"ok": False}
    response = client.post(f"{base}/remove", data={"csrf": csrf, "position": "9", "uri": "spotify:track:1"},
                           headers=FETCH)
    assert response.status_code == 400
    assert not [c for c in sp.calls if c[0] in ("reorder", "remove")]


def test_playlist_edit_without_script_still_redirects(logged_in):
    client, _sp, csrf = logged_in
    response = client.post(f"/playlist/{PLAYLIST_ID}/move", data={"csrf": csrf, "position": "1", "direction": "down"})
    assert response.status_code == 302 and response.headers["Location"] == f"/playlist/{PLAYLIST_ID}"


def test_missing_page_is_styled_and_translated(logged_in):
    client, _sp, csrf = logged_in
    response = client.get("/no-such-page")
    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "הדף לא נמצא" in html and "/static/style.css" in html
    client.post("/lang", data={"csrf": csrf, "lang": "en"})
    assert "Page not found" in client.get("/no-such-page").get_data(as_text=True)


def test_wrong_method_goes_home(client):
    response = client.get("/save")
    assert response.status_code == 302 and response.headers["Location"] == "/"


def test_server_error_page(logged_in, monkeypatch):
    import app as app_module
    client, _sp, _csrf = logged_in
    monkeypatch.setitem(app_module.app.config, "PROPAGATE_EXCEPTIONS", False)
    monkeypatch.setitem(app_module.app.view_functions, "my_stats", lambda: 1 / 0)
    response = client.get("/stats")
    assert response.status_code == 500
    assert "משהו השתבש" in response.get_data(as_text=True)


def test_preview_lookups_are_limited(logged_in, monkeypatch):
    import routes_library
    client, _sp, _csrf = logged_in
    monkeypatch.setattr(routes_library, "preview_url", lambda artist, title: "")
    codes = [client.get("/preview?artist=a&title=b").status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429


def test_login_is_remembered_for_30_days(client, monkeypatch):
    import routes_home
    with client.session_transaction() as s:
        s["oauth_state"] = "st"

    class Auth:
        def get_access_token(self, code, check_cache=False):
            return {"access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}

    class Client:
        def current_user(self):
            return {"id": "u1", "display_name": "U"}
    monkeypatch.setattr(routes_home, "make_auth", lambda: Auth())
    monkeypatch.setattr(routes_home, "user_client", lambda token: Client())
    response = client.get("/callback?code=c&state=st")
    assert response.status_code == 302
    cookie = response.headers["Set-Cookie"]
    assert "Expires=" in cookie and "HttpOnly" in cookie


def test_health_answers_without_spotify_and_does_not_pause_background(client, monkeypatch):
    monkeypatch.setattr(web, "get_spotify_client", lambda: (_ for _ in ()).throw(AssertionError("Spotify")))
    build_playlists._state["user_at"] = 0.0
    response = client.get("/health")
    assert response.status_code == 200 and response.data == b"ok"
    assert not build_playlists.users_active()


def test_security_policy_headers(client):
    response = client.get("/")
    csp = response.headers["Content-Security-Policy"]
    for part in ("default-src 'self'", "connect-src 'self'", "object-src 'none'", "frame-ancestors 'none'",
                 "frame-src https://open.spotify.com"):
        assert part in csp
    assert "camera=()" in response.headers["Permissions-Policy"]


def test_no_spotify_requests_while_blocked(monkeypatch):
    import requests
    import spotipy
    sent = []
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: sent.append(a) or (_ for _ in ()).throw(
        requests.ConnectionError("offline")))
    build_playlists.remember_block(3000)
    sp = web.user_client("token")
    try:
        sp.current_user()
        raise AssertionError("should fail")
    except spotipy.SpotifyException as error:
        assert error.http_status == 429 and 2900 < int(error.headers["Retry-After"]) <= 3060
    assert sent == []


def test_requests_go_through_when_not_blocked(monkeypatch):
    import requests
    sent = []

    def fake(*args, **kwargs):
        sent.append(1)
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests.Session, "request", fake)
    try:
        web.user_client("token").current_user()
    except requests.ConnectionError:
        pass
    assert sent == [1]


def test_app_playlists_recognized_in_any_language():
    import routes_playlists
    for description in ("נוצר ב-פלייליסטור", "Created with Playlistor", "Creada con Playlistor",
                        "Создано в Playlistor"):
        assert routes_playlists.made_here({"id": "x", "description": description})
    assert not routes_playlists.made_here({"id": "x", "description": "My own mix"})
    assert routes_playlists.made_here({"id": "x", "description": None}, {"x"})


def test_saved_playlist_listed_even_without_description(logged_in, monkeypatch):
    client, sp, csrf = logged_in
    client.post("/save", data={"csrf": csrf, "title": "T", "uri": ["spotify:track:1"]})
    assert library.created_playlists("tester") == {"newplaylist"}
    monkeypatch.setattr(sp, "current_user_playlists", lambda limit=50, offset=0: {"items": [
        {"id": "newplaylist", "name": "Saved Here", "images": [], "owner": {"id": "tester"}, "description": "",
         "items": {"total": 1}},
        {"id": "other", "name": "Not Mine", "images": [], "owner": {"id": "tester"}, "description": "",
         "items": {"total": 1}},
    ], "next": None})
    html = client.get("/my-playlists").get_data(as_text=True)
    assert "Saved Here" in html and "Not Mine" not in html


def test_delete_data_forgets_created_playlists(logged_in):
    client, _sp, csrf = logged_in
    library.remember_created("tester", "p1")
    client.post("/delete-data", data={"csrf": csrf})
    assert library.created_playlists("tester") == set()


def test_blocked_page_reloads_itself_when_block_ends(logged_in):
    client, _sp, _csrf = logged_in
    build_playlists.remember_block(1200)
    real = web.get_spotify_client
    web_client = web.user_client("token")
    try:
        web.get_spotify_client = lambda: web_client
        response = client.get("/my-playlists")
    finally:
        web.get_spotify_client = real
    html = response.get_data(as_text=True)
    assert response.status_code == 429
    assert "ייטען מחדש לבד" in html and "location.reload()" in html
