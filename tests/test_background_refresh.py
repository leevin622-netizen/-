"""העדכון ברקע: אינדקס השירים, עצירה בחסימה של ספוטיפיי, ומכסת הבקשות."""
import time

import pytest
from spotipy.exceptions import SpotifyException

import build_index
import build_playlists
import index_store
from conftest import FakeSpotify, make_track


def test_old_index_still_served_while_waiting_for_refresh(monkeypatch):
    index_store.save_term("pop", [make_track(1)])
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 8 * 24 * 3600)
    assert index_store.stale_terms(["pop"]) == ["pop"]
    assert len(index_store.load_term("pop")) == 1
    monkeypatch.setattr(time, "time", lambda: now + 70 * 24 * 3600)
    assert index_store.load_term("pop") == []


def test_term_without_songs_is_not_searched_again():
    index_store.save_term("dream pop", [])
    assert index_store.stale_terms(["dream pop", "pop"]) == ["pop"]


def test_refresh_index_builds_every_stale_term(monkeypatch):
    monkeypatch.setattr(build_index, "all_terms", lambda: ["pop", "rock"])
    monkeypatch.setattr(build_playlists, "get_features", lambda ids: {})
    build_playlists.refresh_index(FakeSpotify(), log=lambda text: None)
    assert index_store.stale_terms(["pop", "rock"]) == []
    assert index_store.load_term("rock")


def test_requests_stop_at_budget(monkeypatch):
    monkeypatch.setattr(build_playlists, "REQUESTS_PER_RUN", 3)
    gentle = build_playlists._GentleClient(FakeSpotify())
    for _ in range(3):
        gentle.search(q="x", type="track", limit=10, offset=0)
    with pytest.raises(build_playlists.RateLimited):
        gentle.search(q="x", type="track", limit=10, offset=0)


def test_long_block_is_remembered_and_nothing_is_sent():
    def blocked():
        raise SpotifyException(429, -1, "limited", headers={"Retry-After": "7200"})
    with pytest.raises(build_playlists.RateLimited):
        build_playlists.with_retry(blocked)
    assert build_playlists.blocked_until() > time.time() + 7000

    sp = FakeSpotify()
    assert build_playlists.run(sp, log=lambda text: None) is False
    assert sp.calls == []


def test_block_seconds_read_from_spotipy_log():
    import logging
    logging.getLogger("spotipy.util").warning("Retry will occur after: 16708 s")
    assert build_playlists._RetryAfterSpy.seconds == 16708


def test_background_refresh_off_in_tests():
    build_playlists.refresh_in_background()
    assert not build_playlists._state["running"]


def test_background_waits_while_users_are_on_the_site():
    build_playlists.note_user_activity()
    sp = FakeSpotify()
    with pytest.raises(build_playlists.RateLimited):
        build_playlists._GentleClient(sp).search(q="x", type="track", limit=10, offset=0)
    assert sp.calls == []


def test_background_resumes_after_users_leave(monkeypatch):
    build_playlists.note_user_activity()
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + build_playlists.USER_QUIET_SECONDS + 1)
    assert not build_playlists.users_active()


def test_visiting_a_page_pauses_background_but_static_files_do_not(client):
    client.get("/static/style.css")
    assert not build_playlists.users_active()
    client.get("/")
    assert build_playlists.users_active()


def test_shorter_block_does_not_shorten_known_block():
    build_playlists.remember_block(20000)
    long_until = build_playlists.blocked_until()
    build_playlists.remember_block(100)
    assert build_playlists.blocked_until() == long_until


def test_block_hit_by_a_user_stops_background_and_shows_notice(logged_in, monkeypatch):
    import logging

    import web
    client, sp, _csrf = logged_in

    def limited(*args, **kwargs):
        logging.getLogger("spotipy.util").warning("Retry will occur after: 80000 s")
        raise SpotifyException(429, -1, "Max Retries")
    monkeypatch.setattr(sp, "current_user_playlists", limited)
    client.get("/my-playlists")
    assert build_playlists.blocked_until() > time.time() + 79000
    assert web.limited_until() > time.time() + 79000
    assert "ספוטיפיי הגביל" in client.get("/build").get_data(as_text=True)
