"""Last.fm (תגיות, אמנים דומים, השמעות) והגבלת קצב לפי כתובת."""
import lastfm
import ratelimit
import requests


class Reply:
    def __init__(self, data):
        self.data = data

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


def fake_get(monkeypatch, *replies):
    calls = []
    queue = list(replies)

    def get(url, params=None, timeout=None):
        calls.append(params)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, requests.RequestException):
            raise reply
        return Reply(reply)
    monkeypatch.setattr(lastfm.requests, "get", get)
    return calls


def test_tags_without_key_or_on_network_failure(monkeypatch):
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    assert lastfm.get_artist_tags("Adele") == []
    monkeypatch.setenv("LASTFM_API_KEY", "k")
    fake_get(monkeypatch, requests.ConnectionError("down"))
    assert lastfm.get_artist_tags("Adele") == []
    fake_get(monkeypatch, ValueError("bad json"))
    assert lastfm.get_artist_tags("Adele") == []


def test_tags_are_cached_and_saved(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "k")
    calls = fake_get(monkeypatch, {"toptags": {"tag": [{"name": "pop"}, {"name": "soul"}, {"name": "x"}]}})
    assert lastfm.get_tags_for_artists(["Adele", "Adele"]) in ([["pop", "soul", "x"]] * 2,)
    assert lastfm.get_artist_tags("Adele", limit=1) == ["pop", "soul", "x"]  # מהמטמון
    assert len(calls) <= 2
    assert "Adele" in open(lastfm.TAGS_FILE, encoding="utf-8").read()


def test_unknown_artist_is_remembered_but_other_errors_are_not(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "k")
    calls = fake_get(monkeypatch, {"error": lastfm.NOT_FOUND})
    assert lastfm.get_artist_tags("Nobody") == [] and lastfm.get_artist_tags("Nobody") == []
    assert len(calls) == 1
    calls = fake_get(monkeypatch, {"error": 29})
    lastfm.get_artist_tags("Limited")
    lastfm.get_artist_tags("Limited")
    assert len(calls) == 2


def test_similar_artists(monkeypatch):
    monkeypatch.setattr(lastfm, "_similar_cache", {})
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    assert lastfm.get_similar_artists("Adele") == []
    monkeypatch.setenv("LASTFM_API_KEY", "k")
    fake_get(monkeypatch, {"error": 6})
    assert lastfm.get_similar_artists("Adele") == []
    fake_get(monkeypatch, requests.Timeout("slow"))
    assert lastfm.get_similar_artists("Adele") == []
    calls = fake_get(monkeypatch, {"similarartists": {"artist": [{"name": "Amy", "match": "0.5"}, {"match": "1"}]}})
    assert lastfm.get_similar_artists("Adele") == [{"name": "Amy", "match": 0.5}]
    lastfm.get_similar_artists("Adele")
    assert len(calls) == 1


def test_user_playcounts(monkeypatch):
    monkeypatch.delenv("LASTFM_USER", raising=False)
    assert lastfm.get_user_playcounts() == (None, None)
    monkeypatch.setenv("LASTFM_USER", "me")
    monkeypatch.setenv("LASTFM_API_KEY", "k")
    track = {"artist": {"name": "Adele"}, "name": "Hello", "playcount": "7"}
    artist = {"name": "Adele", "playcount": "9"}
    calls = fake_get(
        monkeypatch,
        {"tracks": {"track": [track], "@attr": {"totalPages": "2"}}},
        {"tracks": {"track": [track], "@attr": {"totalPages": "2"}}},
        {"artists": {"artist": [artist], "@attr": {"totalPages": "1"}}},
    )
    tracks, artists = lastfm.get_user_playcounts()
    assert tracks == {("adele", "hello"): 7} and artists == {"adele": 9}
    assert [c["page"] for c in calls] == [1, 2, 1]
    fake_get(monkeypatch, requests.ConnectionError("down"))
    assert lastfm.get_user_playcounts() == ({}, {})


def test_client_ip_trusts_header_only_from_local_proxy():
    assert ratelimit.client_ip("127.0.0.1", "1.1.1.1, 2.2.2.2") == "2.2.2.2"
    assert ratelimit.client_ip("127.0.0.1", " , ") == "127.0.0.1"
    assert ratelimit.client_ip("9.9.9.9", "2.2.2.2") == "9.9.9.9"
    assert ratelimit.client_ip(None, None) == "unknown"
    assert len(ratelimit.client_ip("::1", "x" * 200)) == 64


def test_allow_limits_per_bucket_and_does_not_extend_block(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    ratelimit.reset()
    assert ratelimit.allow("a", "ip", 2, 10) and ratelimit.allow("a", "ip", 2, 10)
    assert not ratelimit.allow("a", "ip", 2, 10)
    assert ratelimit.allow("b", "ip", 2, 10)  # דלי אחר
    now[0] += 11  # הדחויה לא נספרה, והחלון נפתח
    assert ratelimit.allow("a", "ip", 2, 10)


def test_allow_clears_when_too_many_keys(monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 2)
    for i in range(4):
        ratelimit.allow("a", f"ip{i}", 1, 60)
    assert len(ratelimit._hits) <= 3
    assert ratelimit.allow("a", "ip0", 1, 60)
