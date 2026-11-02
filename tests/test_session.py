"""שפה ועיצוב שנבחרו, וחידוש ההרשאה מול ספוטיפיי."""
import requests
import routes_home
import spotipy
import themes
import web
from spotipy.oauth2 import SpotifyOauthError


def test_language_choice_is_saved_and_unknown_falls_back(client):
    with client.session_transaction() as s:
        s["csrf"] = "c"
    response = client.post("/lang", data={"csrf": "c", "lang": "en", "back": "/build"})
    assert response.headers["Location"] == "/build"
    with client.session_transaction() as s:
        assert s["lang"] == "en"
    response = client.post("/lang", data={"csrf": "c", "lang": "klingon", "back": "//evil.example"})
    assert response.headers["Location"] == "/"
    with client.session_transaction() as s:
        assert s["lang"] == "he"


def test_vibe_choice_is_saved_and_cleared(logged_in):
    client, _sp, csrf = logged_in
    theme = next(iter(themes.THEMES))
    client.post("/vibe", data={"csrf": csrf, "vibe": theme, "back": "/"})
    with client.session_transaction() as s:
        assert s["vibe_choice"] == theme
    client.post("/vibe", data={"csrf": csrf, "vibe": "no-such-theme", "back": "/"})
    with client.session_transaction() as s:
        assert "vibe_choice" not in s


def test_chosen_vibe_overrides_auto_only_when_logged_in(client, monkeypatch):
    theme = next(iter(themes.THEMES))
    monkeypatch.setattr(web, "auto_vibe", lambda: {"theme": "default", "images": ["a"],
                                                   "by_theme": {theme: ["b"]}})
    with web.app.test_request_context("/"):
        web.session["vibe_choice"] = theme
        assert web.current_vibe()["theme"] == "default"  # לא מחובר
        web.session["token_info"] = {"access_token": "x"}
        assert web.current_vibe() == {"theme": theme, "images": ["b"]}


def test_wants_favourites_is_false_when_spotify_fails(monkeypatch):
    monkeypatch.setattr(routes_home, "user_id", lambda sp: "u")
    for error in (spotipy.SpotifyException(429, -1, "limited"), requests.ConnectionError("down")):
        def failing(sp, uid, error=error):
            raise error
        monkeypatch.setattr(routes_home.favourites, "needs_favourites", failing)
        assert routes_home.wants_favourites(object()) is False


class Auth:
    def __init__(self, expired, fail=False):
        self.expired, self.fail = expired, fail

    def is_token_expired(self, token_info):
        return self.expired

    def refresh_access_token(self, refresh_token):
        if self.fail:
            raise SpotifyOauthError("revoked")
        return {"access_token": "fresh", "refresh_token": refresh_token}


def test_expired_token_is_refreshed_and_revoked_one_logs_out(monkeypatch):
    monkeypatch.setattr(web, "user_client", lambda token: ("client", token))
    old = {"access_token": "old", "refresh_token": "r"}
    with web.app.test_request_context("/"):
        assert web.get_spotify_client() is None  # בלי התחברות
        web.session["token_info"] = old
        monkeypatch.setattr(web, "make_auth", lambda: Auth(expired=False))
        assert web.get_spotify_client() == ("client", "old")
        monkeypatch.setattr(web, "make_auth", lambda: Auth(expired=True))
        assert web.get_spotify_client() == ("client", "fresh")
        assert web.session["token_info"]["access_token"] == "fresh"
        monkeypatch.setattr(web, "make_auth", lambda: Auth(expired=True, fail=True))
        assert web.get_spotify_client() is None
        assert "token_info" not in web.session


def test_hebrew_prints_do_not_crash_with_a_windows_console_encoding():
    import subprocess
    import sys
    code = "import app; print('שלום')"
    env = {**__import__("os").environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252", "PLAYLISTOR_NO_REFRESH": "1"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, cwd=str(__import__("pathlib").Path(__file__).parent.parent))
    assert result.returncode == 0, result.stderr.decode(errors="replace")
