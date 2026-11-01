"""
מהירות כל פיצ'ר, בלי ספוטיפיי (ספוטיפיי מזויף ומהיר). כך בודקים רק את הקוד שלנו:
אם דף נהיה איטי או כבד מהתקציב, הבדיקה נכשלת ואומרת כמה. התקציבים נדיבים, כדי שמחשב איטי לא ייכשל סתם.
"""
import time

import pytest

import catalog
from conftest import PLAYLIST_ID

# (שיטה, כתובת, אלפיות שנייה, קילובייט)
BUDGETS = [
    ("GET", "/", 200, 60),
    ("GET", "/build", 200, 60),
    ("GET", "/saved-tracks", 500, 400),
    ("GET", "/my-artists", 500, 300),
    ("GET", "/stats", 500, 300),
    ("GET", "/my-playlists", 300, 100),
    ("GET", "/playlist/" + PLAYLIST_ID, 300, 100),
    ("POST", "/build", 500, 150),
    ("GET", "/existing-playlists", 300, 80),
    ("GET", "/existing-playlists/cards?offset=60&market=IL", 200, 60),
]


def fill_catalog(size=1000):
    half = size // 2
    catalog.add_candidates(
        [{"id": f"us{n:020d}", "name": f"Top Hits {n}", "owner": "o", "image": "https://img/x"} for n in range(half)],
        "US", "hits",
    )
    catalog.add_candidates(
        [{"id": f"il{n:020d}", "name": f"להיטים {n}", "owner": "o", "image": "https://img/x"} for n in range(half)],
        "IL", "hits",
    )
    catalog.select_top()


@pytest.mark.parametrize("method,path,max_ms,max_kb", BUDGETS)
def test_page_speed_and_size(logged_in, method, path, max_ms, max_kb):
    client, _sp, csrf = logged_in
    if path.startswith("/existing-playlists"):
        fill_catalog()
    form = {"csrf": csrf, "source": "search", "genre_choice": "pop", "language": "ביחד", "count": "50"}

    def call():
        return client.post(path, data=form) if method == "POST" else client.get(path)

    call()  # פעם ראשונה ממלאת מטמונים, כמו אצל משתמש אמיתי
    started = time.perf_counter()
    response = call()
    elapsed_ms = (time.perf_counter() - started) * 1000
    size_kb = len(response.data) / 1024
    assert response.status_code == 200
    assert elapsed_ms < max_ms, f"{method} {path}: {elapsed_ms:.0f}ms (תקציב {max_ms})"
    assert size_kb < max_kb, f"{method} {path}: {size_kb:.0f}KB (תקציב {max_kb})"
