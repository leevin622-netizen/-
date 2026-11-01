"""מנוע בניית הפלייליסטים: סינון שפה ושנים, מונחי חיפוש, ובחירת השירים."""
import engine
import index_store
from conftest import FakeSpotify, make_track


def test_language_filter_keeps_only_hebrew_and_english():
    hebrew = make_track(1, name="שיר אהבה")
    english = make_track(2, name="Love Song")
    spanish = make_track(3, name="Corazón")
    spanish_words = make_track(4, name="Amor de la vida")
    assert engine.passes_language(hebrew, "עברית")
    assert not engine.passes_language(english, "עברית")
    assert engine.passes_language(english, "אנגלית")
    assert not engine.passes_language(hebrew, "אנגלית")
    for track in (hebrew, english):
        assert engine.passes_language(track, "ביחד")
    for track in (spanish, spanish_words):
        assert not engine.passes_language(track, "ביחד")


def test_english_song_by_hebrew_artist_is_not_english():
    assert not engine.passes_language(make_track(1, name="Tel Aviv", artist="עומר אדם"), "אנגלית")


def test_years_filter():
    assert engine.album_year(make_track(1, year=1995)) == 1995
    assert engine.passes_years(make_track(1, year=1995), (1990, 1999))
    assert not engine.passes_years(make_track(1, year=2005), (1990, 1999))
    assert engine.passes_years(make_track(1, year=2005), None)
    no_date = make_track(1)
    no_date["album"]["release_date"] = ""
    assert not engine.passes_years(no_date, (1990, 1999))


def test_build_terms_without_duplicates():
    terms = engine.build_terms("pop", "שמח", "ניקיון הבית", "ביחד")
    assert terms[0] == "pop"
    assert len(terms) == len(set(terms))
    assert engine.build_terms("", "", "", "עברית")[0] == "israeli"
    assert engine.build_terms("", "", "", "ביחד") == ["pop"]


def test_separate_artists_avoids_back_to_back():
    tracks = [engine.to_result(make_track(n, artist="A" if n < 4 else "B")) for n in range(1, 7)]
    for track, n in zip(tracks, range(1, 7)):
        track["artists"] = [("a" if n < 4 else "b", "x")]
    ordered = engine.separate_artists(tracks)
    firsts = [t["artists"][0][0] for t in ordered]
    assert all(a != b for a, b in zip(firsts, firsts[1:]))


def test_find_tracks_reaches_count_without_duplicates():
    sp = FakeSpotify()
    tracks = engine.find_tracks(sp, "pop", "", "", "ביחד", 30)
    assert len(tracks) == 30
    assert len({t["uri"] for t in tracks}) == 30


def test_find_tracks_respects_language():
    sp = FakeSpotify()
    tracks = engine.find_tracks(sp, "", "שמח", "", "עברית", 10)
    assert tracks
    assert all(engine.is_hebrew(t["name"] + t["artist"]) for t in tracks)


def test_find_tracks_excludes_known_songs():
    sp = FakeSpotify()
    first = engine.find_tracks(sp, "pop", "", "", "אנגלית", 10)
    more = engine.find_tracks(sp, "pop", "", "", "אנגלית", 10, exclude={t["uri"] for t in first})
    assert not {t["uri"] for t in first} & {t["uri"] for t in more}


def test_find_tracks_uses_local_index_before_spotify():
    index_store.save_term("pop", [make_track(n) for n in range(1, 60)])
    sp = FakeSpotify()
    tracks = engine.find_tracks(sp, "pop", "", "", "ביחד", 20)
    assert len(tracks) == 20
    assert not [c for c in sp.calls if c[0] == "search"]


def test_spotify_failure_does_not_crash_build():
    class Broken(FakeSpotify):
        def search(self, *args, **kwargs):
            raise engine.SpotifyException(429, -1, "limited")
    assert engine.find_tracks(Broken(), "pop", "", "", "ביחד", 10) == []
