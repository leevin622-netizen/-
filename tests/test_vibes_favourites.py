"""נתוני אווירה של שירים (ReccoBeats, עם מטמון) ובחירת אמנים אהובים."""
import favourites
import lastfm
import requests
import vibes


class Reply:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def fake_recco(monkeypatch, handler):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(params["ids"].split(","))
        return Reply(handler(params["ids"].split(",")))
    monkeypatch.setattr(vibes.requests, "get", get)
    return calls


def content(ids, known):
    return {"content": [{"href": f"https://open.spotify.com/track/{i}", "energy": 0.5, "valence": 0.7}
                        for i in ids if i in known]}


def test_features_are_fetched_once_and_unknown_tracks_remembered(monkeypatch):
    monkeypatch.setattr(vibes, "_cache", None)
    calls = fake_recco(monkeypatch, lambda ids: content(ids, {"a"}))
    first = vibes.get_features(["a", "b", "a", ""])
    assert list(first) == ["a"] and first["a"]["energy"] == 0.5
    vibes.get_features(["a", "b"])
    assert len(calls) == 1 and calls[0] == ["a", "b"]  # בלי כפילויות, וב לא נשאל שוב


def test_failed_service_is_not_cached(monkeypatch):
    monkeypatch.setattr(vibes, "_cache", None)

    def down(url, params=None, timeout=None):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(vibes.requests, "get", down)
    assert vibes.get_features(["a"]) == {}
    calls = fake_recco(monkeypatch, lambda ids: content(ids, {"a"}))
    assert "a" in vibes.get_features(["a"]) and len(calls) == 1


def test_features_split_into_batches_and_survive_a_restart(monkeypatch):
    monkeypatch.setattr(vibes, "_cache", None)
    ids = [f"id{n}" for n in range(vibes.BATCH + 1)]
    calls = fake_recco(monkeypatch, lambda batch: content(batch, set(ids)))
    assert len(vibes.get_features(ids)) == len(ids) and len(calls) == 2
    monkeypatch.setattr(vibes, "_cache", None)  # הפעלה מחדש: נקרא מהקובץ
    calls.clear()
    assert len(vibes.get_features(ids)) == len(ids) and calls == []


def test_describe():
    assert vibes.describe(None) == ""
    assert vibes.describe({"tempo": 120.4, "energy": 0.5, "valence": 0.25}) == "120 BPM · אנרגיה 50% · שמחה 25%"
    assert vibes.describe({"energy": 0.9}, energy_label="Energy") == "Energy 90%"


def test_needs_favourites_only_with_few_artists_and_songs(logged_in, monkeypatch):
    _client, sp, _csrf = logged_in
    sp.current_user_saved_tracks = lambda limit=20, offset=0, market=None: {"total": 5, "items": []}
    assert favourites.needs_favourites(sp, "tester") is True
    favourites.library.forget("tester", "saved_total")
    sp.current_user_saved_tracks = lambda limit=20, offset=0, market=None: {"total": favourites.FAVOURITE_SONGS}
    assert favourites.needs_favourites(sp, "tester") is False


def test_find_artist_prefers_exact_name(logged_in):
    _client, sp, _csrf = logged_in
    items = [None, {"id": "x" * 22, "name": "Adele Fans", "images": []},
             {"id": "y" * 22, "name": "ADELE", "images": [{"url": "big"}, {"url": "small"}]}]
    sp.search = lambda q, type="artist", limit=5, **k: {"artists": {"items": items}}
    assert favourites.find_artist(sp, "adele") == {"id": "y" * 22, "name": "ADELE", "image": "small"}
    items[:] = [None]
    assert favourites.find_artist(sp, "nobody") is None


def test_seed_artists_followed_first_then_saved_songs(logged_in):
    _client, sp, _csrf = logged_in
    seeds = favourites.seed_artists(sp, "tester")
    assert 0 < len(seeds) <= favourites.SEED_ARTISTS
    assert len({artist_id for artist_id, _name in seeds}) == len(seeds)


def test_similar_names_ranked_by_overlap_and_exclude_known(monkeypatch):
    similar = {"A": [{"name": "Zed", "match": 0.9}, {"name": "Ann", "match": 0.5}, {"name": "b", "match": 1}],
               "B": [{"name": "ann", "match": 0.6}]}
    monkeypatch.setattr(lastfm, "get_similar_artists", lambda name: similar[name])
    assert favourites.similar_names(["A", "B"]) == ["Ann", "Zed"]  # Ann: 1.1 מול Zed: 0.9; "b" כבר מוכר
