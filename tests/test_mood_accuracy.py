"""מצב רוח מדויק: עצוב לא מקבל שירים שמחים, גם כשחסרים שירים והרשימה יוצאת קצרה."""
import engine
from tests.conftest import FakeSpotify, make_track

SAD = {"valence": 0.2, "energy": 0.3, "danceability": 0.4, "speechiness": 0.04}
HAPPY = {"valence": 0.85, "energy": 0.85, "danceability": 0.8, "speechiness": 0.05}
NEAR_SAD = {"valence": 0.37, "energy": 0.3, "danceability": 0.4, "speechiness": 0.04}


def library(monkeypatch, sad=40, happy=80, near=0, unknown=0):
    """שירים 1..sad עצובים, אחריהם קרובים לעצוב, שמחים, ובסוף שירים בלי נתוני אווירה."""
    tracks, features, n = [], {}, 0
    for kind, amount in ((SAD, sad), (NEAR_SAD, near), (HAPPY, happy), (None, unknown)):
        for _ in range(amount):
            n += 1
            track = make_track(n)
            tracks.append(track)
            if kind:
                features[track["id"]] = kind
    monkeypatch.setattr(engine, "get_features", lambda ids: {i: features[i] for i in ids if i in features})
    return FakeSpotify(tracks), features


def mood_of(sp, results, features):
    ids = {t["id"] for t in sp.tracks if t["uri"] in {r["uri"] for r in results}}
    return [features.get(i) for i in ids]


def test_sad_playlist_has_no_happy_songs(monkeypatch):
    sp, features = library(monkeypatch)
    results = engine.find_tracks(sp, "", "עצוב", "", "אנגלית", 30)
    assert len(results) == 30
    assert all(f == SAD for f in mood_of(sp, results, features))


def test_short_list_is_better_than_wrong_songs(monkeypatch):
    # מבקשים 50 אבל יש רק 12 שירים עצובים: מקבלים 12, לא עוד 38 שירים שמחים או בלי נתונים
    sp, features = library(monkeypatch, sad=12, happy=80, unknown=30)
    results = engine.find_tracks(sp, "", "עצוב", "", "אנגלית", 50)
    assert len(results) == 12
    assert all(f == SAD for f in mood_of(sp, results, features))


def test_slightly_outside_range_may_fill_up_but_never_the_opposite(monkeypatch):
    sp, features = library(monkeypatch, sad=10, near=0, happy=80)
    assert all(f != HAPPY for f in mood_of(sp, engine.find_tracks(sp, "", "שבור לב", "", "אנגלית", 50), features))
    sp, features = library(monkeypatch, sad=10, near=0, happy=80)
    assert len(engine.find_tracks(sp, "", "שמח", "", "אנגלית", 30)) == 30


def test_event_conflict_keeps_the_mood_valence(monkeypatch):
    # עצוב במסיבה: האירוע קובע אנרגיה גבוהה, אבל השיר לא הופך לשמח
    dark_dance = {"valence": 0.2, "energy": 0.85, "danceability": 0.8, "speechiness": 0.05}
    sp, features = library(monkeypatch, sad=0, happy=40)
    for t in sp.tracks[:30]:
        features[t["id"]] = dark_dance
    for t in sp.tracks[30:]:
        features[t["id"]] = HAPPY
    results = engine.find_tracks(sp, "", "עצוב", "מסיבה", "אנגלית", 20)
    assert results and all(f == dark_dance for f in mood_of(sp, results, features))


def test_no_mood_still_fills_the_list(monkeypatch):
    sp, _features = library(monkeypatch, sad=10, happy=60, unknown=40)
    assert len(engine.find_tracks(sp, "pop", "", "", "אנגלית", 50)) == 50


def test_missing_audio_data_never_counts_as_fitting():
    import vibes
    assert vibes.distance({"valence": None, "energy": 0.3}, vibes.MOOD_PROFILES["עצוב"]) >= 1


def test_every_mood_range_matches_its_meaning():
    """שמח לא מקבל שיר עצוב וההפך, ורגוע לא מקבל שיר חזק."""
    import vibes
    profiles = vibes.MOOD_PROFILES
    happy_song = {"valence": 0.9, "energy": 0.8, "danceability": 0.7, "speechiness": 0.05}
    sad_song = {"valence": 0.1, "energy": 0.3, "danceability": 0.4, "speechiness": 0.04}
    loud_song = {"valence": 0.5, "energy": 0.95, "danceability": 0.6, "speechiness": 0.05}
    assert vibes.distance(happy_song, profiles["עצוב"]) > 0.3 and vibes.distance(happy_song, profiles["שבור לב"]) > 0.2
    assert vibes.distance(sad_song, profiles["שמח"]) > 0.3 and vibes.distance(sad_song, profiles["בא לרקוד"]) > 0
    assert vibes.distance(loud_song, profiles["רגוע"]) > 0.3 and vibes.distance(loud_song, profiles["חולמני"]) > 0.3
