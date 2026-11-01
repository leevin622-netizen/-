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
