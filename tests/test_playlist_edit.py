"""עריכת פלייליסטים: הסרה מהחשבון, פלייליסטים שלא שלנו, שיר שלא זמין, והתחברות."""
from conftest import PLAYLIST_ID

BASE = f"/playlist/{PLAYLIST_ID}"
ACTIONS = ("rename", "remove", "move", "unfollow")


def test_unfollow_removes_from_account_and_forgets_cache(logged_in):
    client, sp, csrf = logged_in
    sp.current_user_unfollow_playlist = lambda playlist_id: sp.calls.append(("unfollow", playlist_id))
    response = client.post(f"{BASE}/unfollow", data={"csrf": csrf})
    assert response.headers["Location"] == "/my-playlists"
    assert ("unfollow", PLAYLIST_ID) in sp.calls


def test_cannot_edit_a_playlist_not_created_by_the_app(logged_in):
    client, sp, csrf = logged_in
    original = sp.playlist
    sp.playlist = lambda playlist_id, **k: dict(original(playlist_id), owner={"id": "someone-else"},
                                                description="not ours")
    sp.current_user_unfollow_playlist = lambda playlist_id: sp.calls.append(("unfollow", playlist_id))
    assert client.get(BASE).status_code == 404
    data = {"csrf": csrf, "name": "x", "position": "1", "uri": "spotify:track:1", "direction": "up"}
    for action in ACTIONS:
        assert client.post(f"{BASE}/{action}", data=data).status_code == 404
    assert not [c for c in sp.calls if c[0] in ("reorder", "remove", "unfollow")]


def test_edit_routes_need_login(client):
    assert client.get(BASE).headers["Location"].endswith("/login")
    for action in ACTIONS:
        assert client.post(f"{BASE}/{action}").status_code in (302, 400, 403)


def test_blank_rename_changes_nothing(logged_in):
    client, sp, csrf = logged_in
    renamed = []
    sp.playlist_change_details = lambda playlist_id, name=None: renamed.append(name)
    response = client.post(f"{BASE}/rename", data={"csrf": csrf, "name": "   "})
    assert response.headers["Location"] == BASE and renamed == []
    client.post(f"{BASE}/rename", data={"csrf": csrf, "name": "  New  "})
    assert renamed == ["New"]


def test_unavailable_track_still_shows_a_row(logged_in):
    client, sp, _csrf = logged_in
    sp.playlist_items = lambda playlist_id, **k: {"items": [{"track": None}], "next": None} if not k.get("offset") \
        else {"items": [], "next": None}
    html = client.get(BASE).get_data(as_text=True)
    assert 'data-position="0"' in html and "noimg" in html
