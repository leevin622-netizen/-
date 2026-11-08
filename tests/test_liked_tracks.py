"""פלייליסט משירים שאהבת: סינון לפי ז'אנר, החרגות, והתאמה לקצב ולאנרגיה."""
import engine
from conftest import make_track


def saved(*tracks):
    return [{"added_at": "2026-01-01T00:00:00Z", "track": t} for t in tracks]


def uris(results):
    return {r["uri"] for r in results}


def test_genre_keeps_only_matching_artists_and_respects_exclude():
    rock, pop = make_track(1), make_track(2)
    tags = {rock["artists"][0]["id"]: ["rock", "indie"], pop["artists"][0]["id"]: ["pop"]}
    found = engine.find_liked_tracks(saved(rock, pop), tags, "rock", "", "", "ביחד", 10)
    assert uris(found) == {rock["uri"]}
    assert engine.find_liked_tracks(saved(rock, pop), tags, "rock", "", "", "ביחד", 10, exclude={rock["uri"]}) == []


def test_skips_local_files_and_unavailable_tracks():
    good = make_track(1)
    local = dict(make_track(2), uri="spotify:local:x:y:z:1")
    found = engine.find_liked_tracks(saved(good, local), {}, "", "", "", "ביחד", 10)
    assert uris(found) == {good["uri"]}


def test_count_limits_results():
    tracks = [make_track(n) for n in range(1, 30)]
    assert len(engine.find_liked_tracks(saved(*tracks), {}, "", "", "", "ביחד", 5)) == 5


def test_vibe_filter_drops_unfitting_and_fills_up_when_too_few(monkeypatch):
    calm, near, loud, unknown = make_track(1), make_track(2), make_track(3), make_track(4)
    mood = next(iter(engine.GENRE_HINTS))
    profile = {"energy": (None, 0.4)}
    monkeypatch.setattr(engine, "profile_for", lambda mood, event, ranges=None: profile)
    monkeypatch.setattr(engine, "get_features", lambda ids: {
        calm["id"]: {"energy": 0.2}, near["id"]: {"energy": 0.42}, loud["id"]: {"energy": 0.9}})
    scored = [(1.0, calm), (1.0, loud)]
    assert [t for _, t in engine.filter_liked_by_vibe(scored, mood, "", None)] == [calm]
    # מבקשים יותר משיש שמתאים: משלימים רק משיר שקרוב מאוד לטווח. שיר הפוך או בלי נתונים לא נכנס, גם אם הרשימה קצרה
    found = engine.find_liked_tracks(saved(calm, near, loud, unknown), {}, "", mood, "", "ביחד", 4)
    assert uris(found) == {calm["uri"], near["uri"]}
    found = engine.find_liked_tracks(saved(calm, near, loud, unknown), {}, "", mood, "", "ביחד", 1)
    assert uris(found) == {calm["uri"]}


def test_vibe_filter_changes_nothing_without_data(monkeypatch):
    track = make_track(1)
    scored = [(1.0, track)]
    monkeypatch.setattr(engine, "profile_for", lambda *a, **k: {})
    assert engine.filter_liked_by_vibe(scored, "", "", None) == scored  # אין פרופיל
    monkeypatch.setattr(engine, "profile_for", lambda *a, **k: {"energy": (None, 0.4)})
    monkeypatch.setattr(engine, "get_features", lambda ids: {})
    assert engine.filter_liked_by_vibe(scored, "x", "", None) == scored  # השירות לא ענה
    assert engine.filter_liked_by_vibe([], "x", "", None) == []


def test_matches_needs_every_word():
    assert engine.matches("israeli pop", ["Israeli Rock", "pop"])
    assert not engine.matches("israeli pop", ["israeli rock"])
