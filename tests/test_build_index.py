"""בניית האינדקס מראש: ניסיונות חוזרים מול הגבלה של ספוטיפיי, ודילוג על מונחים טריים."""
import build_index
import index_store
import pytest
from spotipy.exceptions import SpotifyException

from conftest import make_track


def limited(seconds=None):
    text = f"429 Too Many Requests, Retry will occur after: {seconds}" if seconds is not None else "429"
    return SpotifyException(429, -1, text)


def test_all_terms_are_sorted_and_unique():
    terms = build_index.all_terms()
    assert terms == sorted(set(terms)) and len(terms) > 10


def test_retry_waits_the_time_spotify_asks_for(monkeypatch):
    waits, answers = [], [limited(7), limited(), "ok"]

    def search(sp, term, language, count):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(build_index.engine, "search_term", search)
    monkeypatch.setattr(build_index.time, "sleep", waits.append)
    assert build_index.search_with_retry(None, "pop") == "ok"
    assert waits == [7, 60]  # מההודעה, ואחרי זה ברירת מחדל של 30 כפול מספר הניסיון


def test_long_wait_stops_immediately_and_other_errors_propagate(monkeypatch):
    waits = []
    monkeypatch.setattr(build_index.time, "sleep", waits.append)

    def too_long(sp, term, language, count):
        raise limited(build_index.MAX_WAIT_SECONDS + 1)
    monkeypatch.setattr(build_index.engine, "search_term", too_long)
    with pytest.raises(RuntimeError):
        build_index.search_with_retry(None, "pop")
    assert waits == []

    def broken(sp, term, language, count):
        raise SpotifyException(500, -1, "boom")
    monkeypatch.setattr(build_index.engine, "search_term", broken)
    with pytest.raises(SpotifyException):
        build_index.search_with_retry(None, "pop")


def test_gives_up_after_all_retries(monkeypatch):
    attempts = []

    def always(sp, term, language, count):
        attempts.append(1)
        raise limited(1)
    monkeypatch.setattr(build_index.engine, "search_term", always)
    monkeypatch.setattr(build_index.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        build_index.search_with_retry(None, "pop")
    assert len(attempts) == build_index.RETRIES


def test_main_builds_stale_terms_only_and_stops_on_long_block(monkeypatch):
    searched = []
    monkeypatch.setattr(build_index, "load_dotenv", lambda: None)
    monkeypatch.setattr(build_index.spotipy, "Spotify", lambda **k: object())
    monkeypatch.setattr(build_index, "SpotifyClientCredentials", lambda *a, **k: None)
    monkeypatch.setattr(build_index, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(build_index, "all_terms", lambda: ["a", "b", "c"])
    monkeypatch.setattr(build_index, "get_features", lambda ids: {})
    monkeypatch.setattr(build_index.sys, "argv", ["build_index.py"])
    monkeypatch.setattr(index_store, "stale_terms", lambda terms: ["a", "c"])

    def search(sp, term):
        searched.append(term)
        if term == "c":
            raise RuntimeError("blocked")
        return [make_track(1)]
    saved = []
    monkeypatch.setattr(build_index, "search_with_retry", search)
    monkeypatch.setattr(index_store, "save_term", lambda term, tracks: saved.append(term))
    build_index.main()
    assert searched == ["a", "c"] and saved == ["a"]  # "b" טרי, ו-"c" עצר את הבנייה
