"""קטלוג "פלייליסטים קיימים": סיווג ישראלי, בחירת הגדולים לכל אזור, וסדר התצוגה."""
import catalog


def item(pid, name, owner="someone", description=""):
    return {"id": pid, "name": name, "owner": owner, "description": description, "image": ""}


def test_allowed_name_only_hebrew_or_english():
    assert catalog.allowed_name("Top Hits 2026 🔥")
    assert catalog.allowed_name("להיטים ישראליים")
    assert not catalog.allowed_name("Éxitos")
    assert not catalog.allowed_name("Canciones de amor")
    assert not catalog.allowed_name("🔥🔥")


def test_is_israeli():
    assert catalog.is_israeli("להיטים", "someone")
    assert catalog.is_israeli("Top Hits", "דני")
    assert catalog.is_israeli("Chill", "x", "שירים רגועים")
    assert catalog.is_israeli("Israeli Party", "x")
    assert not catalog.is_israeli("Top Hits", "someone")


def test_select_top_per_region(monkeypatch):
    monkeypatch.setattr(catalog, "PER_REGION", 2)
    catalog.add_candidates([item("us1", "Pop A"), item("us2", "Pop B"), item("us3", "Pop C")], "US", "pop")
    catalog.add_candidates([item("il1", "פופ א"), item("il2", "פופ ב"), item("il3", "פופ ג")], "IL", "pop")
    for pid, followers in [("us1", 10), ("us2", 300), ("us3", 50), ("il1", 5), ("il2", 1), ("il3", 80)]:
        catalog.set_followers(pid, followers)
    catalog.select_top()
    loaded = catalog.load()
    assert [p["id"] for p in loaded] == ["us2", "il3", "us3", "il1"]
    markets = {p["id"]: p["markets"] for p in loaded}
    assert markets["il3"] == ["IL"] and markets["us2"] == ["US"]


def test_israeli_playlist_found_in_us_market_counts_as_israeli():
    catalog.add_candidates([item("x", "שירים שקטים")], "US", "chill")
    catalog.select_top()
    assert catalog.load()[0]["markets"] == ["IL"]


def test_candidates_keep_all_categories():
    catalog.add_candidates([item("x", "Gym Hits")], "US", "workout")
    catalog.add_candidates([item("x", "Gym Hits")], "US", "hits")
    catalog.select_top()
    assert catalog.load()[0]["categories"] == ["hits", "workout"]


def test_needs_refresh_until_complete():
    assert catalog.needs_refresh()
    catalog.mark_done(catalog.COMPLETE_KEY)
    assert not catalog.needs_refresh()


def test_followers_missing_first_israeli():
    catalog.add_candidates([item("us", "Pop")], "US", "pop")
    catalog.add_candidates([item("il", "פופ")], "IL", "pop")
    assert catalog.without_followers() == ["il", "us"]


def test_short_number():
    assert catalog.short_number(1_234_567) == "1.2M"
    assert catalog.short_number(2_000_000) == "2M"
    assert catalog.short_number(45_300) == "45K"
    assert catalog.short_number(999) == "999"
