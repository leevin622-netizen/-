"""
הגדרות משותפות לבדיקות. כל בדיקה רצה:
- בלי רשת: כל בקשה (ספוטיפיי, ReccoBeats, Last.fm) נכשלת, כדי שבדיקה לא תשלח בקשות אמיתיות ולא תגרום לחסימה.
- עם תיקיית cache זמנית משלה, כדי לא לגעת בקטלוג, באינדקס ובנתוני המשתמשים האמיתיים.
- בלי העדכון ברקע (PLAYLISTOR_NO_REFRESH).
"""
import os
import sys

import pytest
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PLAYLISTOR_NO_REFRESH"] = "1"
os.environ.setdefault("FLASK_SECRET", "test-secret")
os.environ.setdefault("SPOTIFY_CLIENT_ID", "test-id")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "test-secret")
os.environ.setdefault("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/callback")

import app as app_module  # noqa: E402
import routes_build  # noqa: E402
import routes_home  # noqa: E402
import web  # noqa: E402
import build_playlists  # noqa: E402
import catalog  # noqa: E402
import engine  # noqa: E402
import index_store  # noqa: E402
import lastfm  # noqa: E402
import library  # noqa: E402
import ratelimit  # noqa: E402
import vibes  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise requests.ConnectionError("אין רשת בבדיקות")
    monkeypatch.setattr(requests.Session, "request", blocked)


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "DB_FILE", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setattr(index_store, "DB_FILE", str(tmp_path / "index.sqlite"))
    monkeypatch.setattr(library, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(vibes, "CACHE_FILE", str(tmp_path / "features.json"))
    monkeypatch.setattr(lastfm, "TAGS_FILE", str(tmp_path / "lastfm_tags.json"))
    monkeypatch.setattr(lastfm, "_tags_cache", None)
    monkeypatch.setattr(build_playlists, "BLOCK_FILE", str(tmp_path / "spotify_block.json"))
    monkeypatch.setattr(build_playlists, "PAUSE_SECONDS", 0)
    # מטמונים בזיכרון שנשארים בין בדיקות
    monkeypatch.setattr(library, "_cache", {})
    monkeypatch.setattr(vibes, "_cache", None)
    monkeypatch.setattr(web, "_login_cache", {"until": 0.0, "images": []})
    monkeypatch.setattr(routes_build, "_previews", {})
    ratelimit._hits.clear()
    build_playlists._sent["count"] = 0
    build_playlists._state["user_at"] = 0.0
    monkeypatch.setattr(web, "_limit", {"until": 0.0})
    # בלי נתוני אווירה (ReccoBeats): הסינון לפי אווירה פשוט לא משנה כלום
    monkeypatch.setattr(engine, "get_features", lambda ids: {})
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", "") and module.__file__.startswith(ROOT) and hasattr(module, "get_features"):
            monkeypatch.setattr(module, "get_features", lambda ids: {})


PLAYLIST_ID = "myplaylist" + "0" * 12


def make_track(n, name=None, artist=None, year=2020):
    return {
        "id": f"track{n:018d}"[-22:], "name": name or f"Song {n}", "uri": f"spotify:track:{n}",
        "duration_ms": 180000,
        "artists": [{"id": f"artist{n % 7}", "name": artist or f"Artist {n % 7}"}],
        "album": {"id": f"album{n}", "release_date": str(year), "images": [{"url": f"https://img/{n}"}]},
    }


class FakeSpotify:
    """לקוח ספוטיפיי מזויף: חיפוש מחזיר שירים באנגלית ובעברית, וכל פעולה נרשמת ב-calls."""

    def __init__(self, tracks=None):
        self.tracks = tracks if tracks is not None else (
            [make_track(i) for i in range(1, 121)]
            + [make_track(i, name=f"שיר {i}", artist=f"זמר {i % 5}") for i in range(200, 260)]
        )
        self.calls = []

    def search(self, q, type="track", limit=10, offset=0, market=None):
        self.calls.append(("search", q, offset))
        if type == "playlist":
            return {"playlists": {"items": []}}
        if type == "artist":
            return {"artists": {"items": [dict(self.artist(1), name=q.strip('"'))]}}
        return {"tracks": {"items": self.tracks[offset:offset + limit]}}

    def current_user(self):
        return {"id": "tester", "display_name": "Tester"}

    me = current_user

    def artist(self, n):
        return {"id": f"artist{n}", "name": f"Artist {n}", "genres": ["pop", "dance pop"] if n % 2 else ["rock"],
                "images": [{"url": f"https://img/a{n}"}], "popularity": 50}

    def current_user_top_artists(self, limit=20, offset=0, time_range="medium_term"):
        return {"items": [self.artist(n) for n in range(7)], "next": None}

    def current_user_top_tracks(self, limit=20, offset=0, time_range="medium_term"):
        return {"items": self.tracks[:20], "next": None}

    def current_user_followed_artists(self, limit=20, after=None):
        return {"artists": {"items": [self.artist(n) for n in range(3)], "next": None, "cursors": {}}}

    def current_user_saved_tracks(self, limit=20, offset=0, market=None):
        page = self.tracks[offset:offset + limit]
        more = offset + limit < len(self.tracks)
        return {"items": [{"added_at": "2026-01-01T00:00:00Z", "track": t} for t in page],
                "next": "more" if more else None, "total": len(self.tracks)}

    def current_user_saved_tracks_contains(self, tracks):
        return [False] * len(tracks)

    def current_user_playlists(self, limit=50, offset=0):
        playlist = {"id": PLAYLIST_ID, "name": "My Mix", "images": [], "owner": {"id": "tester"},
                    "description": engine.PLAYLIST_DESCRIPTION, "items": {"total": 3}}
        return {"items": [playlist] if offset == 0 else [], "next": None}

    def playlist(self, playlist_id, fields=None, market=None):
        return {"id": playlist_id, "name": "My Mix", "owner": {"id": "tester"}, "images": [],
                "description": engine.PLAYLIST_DESCRIPTION, "items": {"total": 3}, "followers": {"total": 5}}

    def playlist_items(self, playlist_id, limit=100, offset=0, fields=None, market=None, additional_types=None):
        return {"items": [{"track": t} for t in self.tracks[:3]] if offset == 0 else [], "next": None}

    def current_user_follow_playlist(self, playlist_id):
        self.calls.append(("follow", playlist_id))

    def current_user_playlist_create(self, name, public=False, description=""):
        self.calls.append(("create", name))
        return {"id": "newplaylist", "external_urls": {"spotify": "https://open.spotify.com/playlist/new"}}

    def playlist_add_items(self, playlist_id, items):
        self.calls.append(("add", playlist_id, len(items)))


@pytest.fixture
def fake_sp():
    return FakeSpotify()


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def logged_in(client, fake_sp, monkeypatch):
    """לקוח מחובר, עם ספוטיפיי מזויף. מחזיר (client, fake_sp, csrf)."""
    monkeypatch.setattr(web, "get_spotify_client", lambda: fake_sp)
    monkeypatch.setattr(routes_home, "wants_favourites", lambda sp: False)
    monkeypatch.setattr(web, "auto_vibe", lambda: {"theme": "default", "images": []})
    with client.session_transaction() as s:
        s["token_info"] = {"access_token": "x"}
        s["scope"] = web.SCOPE
        s["user_id"] = "tester"
        s["csrf"] = "test-csrf"
        s["lang"] = "he"
    return client, fake_sp, "test-csrf"
