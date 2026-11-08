"""סינון לפי אווירה (ReccoBeats) וקטעי השמעה (Deezer ו-iTunes), בלי רשת."""
import requests

import engine
import previews
import themes
import vibes


def test_every_form_choice_has_vibe_and_theme():
    for mood in engine.GENRE_HINTS:
        assert mood in vibes.MOOD_PROFILES and mood in themes.CHOICE_THEMES, mood
    for event in engine.EVENT_HINTS:
        assert event in vibes.EVENT_PROFILES and event in themes.CHOICE_THEMES, event


def test_profile_conflict_event_sets_energy_mood_keeps_valence():
    profile = vibes.profile_for("עצוב", "חדר כושר")
    assert profile["valence"] == (None, 0.35)
    assert profile["energy"] == (0.68, None)


def test_profile_ranges_combine_and_manual_ranges_win():
    profile = vibes.profile_for("שמח", "בישול")
    assert profile["energy"] == (0.5, 0.8) and profile["valence"] == (0.6, None)
    assert vibes.profile_for("שמח", "", {"energy": (0.1, 0.2)})["energy"] == (0.1, 0.2)
    assert vibes.profile_for("", "") == {}


def test_distance_and_strength():
    profile = {"energy": (0.6, None), "valence": (None, 0.4)}
    assert vibes.distance({"energy": 0.7, "valence": 0.3}, profile) == 0
    assert round(vibes.distance({"energy": 0.5, "valence": 0.5}, profile), 2) == 0.2
    # תכונה שחסרה לא מוכיחה שהשיר מתאים: היא נספרת כחריגה מלאה
    assert vibes.distance({"energy": None}, profile) == 2
    assert vibes.strength({"energy": 0.9, "valence": 0.1}, profile) > vibes.strength({"energy": 0.7, "valence": 0.3}, profile)


class Reply:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_features_cached_and_unknown_songs_remembered(monkeypatch):
    asked = []

    def fake_get(url, params, timeout):
        ids = params["ids"].split(",")
        asked.append(ids)
        return Reply({"content": [{"href": "https://open.spotify.com/track/a", "energy": 0.8, "valence": 0.2}]})
    monkeypatch.setattr(vibes.requests, "get", fake_get)
    found = vibes.get_features(["a", "b"])
    assert found["a"]["energy"] == 0.8 and "b" not in found
    vibes.get_features(["a", "b"])
    assert asked == [["a", "b"]]  # "b" לא קיים ב-ReccoBeats, וזה נזכר


def test_features_failure_is_not_remembered(monkeypatch):
    calls = []

    def failing(url, params, timeout):
        calls.append(1)
        raise requests.ConnectionError("down")
    monkeypatch.setattr(vibes.requests, "get", failing)
    assert vibes.get_features(["x"]) == {}
    assert vibes.get_features(["x"]) == {}
    assert len(calls) == 2


def test_loose_names_ignore_extras():
    assert previews._loose("Song (Remastered 2011)") == "song"
    assert previews._loose("Song - Live at Wembley") == "song"
    assert previews._loose("Song feat. Someone") == "song"


def test_same_artist_rules():
    assert previews._same_artist("Omer Adam", previews._loose("omer adam"))
    assert previews._same_artist("עומר אדם", previews._loose("Omer Adam"))  # עברית מול אנגלית
    assert not previews._same_artist("Someone Else", previews._loose("Omer Adam"))


def test_preview_prefers_deezer_then_itunes(monkeypatch):
    def fake_get(url, params, timeout):
        if "deezer" in url:
            return Reply({"data": [{"title": "Other", "artist": {"name": "A"}, "preview": "https://d/1"}]})
        return Reply({"results": [{"trackName": "Hello (Live)", "artistName": "Adele", "previewUrl": "https://i/1"}]})
    monkeypatch.setattr(previews.requests, "get", fake_get)
    assert previews.preview_url("Adele", "Hello") == "https://i/1"


def test_preview_failure_not_remembered(monkeypatch):
    replies = iter([requests.ConnectionError("down")] * 3 + [
        Reply({"data": [{"title": "Hello", "artist": {"name": "Adele"}, "preview": "https://d/1"}]})])

    def fake_get(url, params, timeout):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(previews.requests, "get", fake_get)
    monkeypatch.setattr(previews, "_cache", {})
    assert previews.preview_url("Adele", "Hello") == ""
    assert previews.preview_url("Adele", "Hello") == "https://d/1"
