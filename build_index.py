"""
בונה אינדקס מראש לכל הקטגוריות: אירועים, מצבי רוח וז'אנרים.
מריצים במחשב שלך, מתוך תיקיית הפרויקט:
    .\\venv\\Scripts\\python build_index.py            (הכול)
    .\\venv\\Scripts\\python build_index.py ריצה        (מונח אחד, לבדיקה)
אפשר לעצור באמצע ולהתחיל שוב: מונחים שכבר נשמרו טריים לא נבנים מחדש.
"""
import os
import re
import sys
import time

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

import engine
import index_store
from vibes import get_features

# עד 100 שירים לכל מונח: מספיק לבחירה, בלי לשלוח אלפי בקשות לספוטיפיי
TRACKS_PER_TERM = 100
PAUSE_SECONDS = 1
RETRIES = 5
# המתנה ארוכה מזו לא שווה לחכות לה בסקריפט. עוצרים, ואפשר להמשיך אחר כך
MAX_WAIT_SECONDS = 600


def all_terms():
    """כל מונחי החיפוש שהאפליקציה משתמשת בהם."""
    terms = set()
    for event_terms in engine.EVENT_HINTS.values():
        terms.update(event_terms)
    for mood_terms in engine.GENRE_HINTS.values():
        terms.update(mood_terms)
    terms.update(term for _, term in engine.HEBREW_GENRES + engine.WORLD_GENRES)
    return sorted(terms)


def search_with_retry(sp, term):
    """ספוטיפיי מגביל בקשות. מחכים קצת ומנסים שוב. אם ההמתנה ארוכה, עוצרים מיד."""
    for attempt in range(1, RETRIES + 1):
        try:
            return engine.search_term(sp, term, "ביחד", TRACKS_PER_TERM)
        except SpotifyException as error:
            if error.http_status != 429:
                raise
            # ספוטיפיי כותב בהודעה כמה שניות לחכות
            match = re.search(r"after: (\d+)", str(error))
            wait = int(match.group(1)) if match else 30 * attempt
            if wait > MAX_WAIT_SECONDS:
                raise RuntimeError(
                    f"ספוטיפיי הגביל את הבקשות ל-{wait // 60} דקות. הבנייה נעצרה. "
                    "הפעילו את אותה פקודה שוב אחרי ההמתנה, והיא תמשיך ממקום העצירה"
                ) from error
            print(f"   ספוטיפיי ביקש להמתין, ממתינים {wait} שניות")
            time.sleep(wait)
    raise RuntimeError("ספוטיפיי ממשיך להגביל. נסו שוב מאוחר יותר, הבנייה תמשיך מאותו מקום")


def main():
    load_dotenv()
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            os.getenv("SPOTIFY_CLIENT_ID"), os.getenv("SPOTIFY_CLIENT_SECRET"),
            cache_handler=MemoryCacheHandler(),
        ),
        retries=0, requests_timeout=10,
    )
    only = sys.argv[1:]
    terms = [t for t in all_terms() if not only or t in only]
    print(f"{len(terms)} מונחים לבנייה")

    for number, term in enumerate(terms, 1):
        label = f"[{number}/{len(terms)}] {term}"
        # מונח שנבחר בשם נבנה מחדש, גם אם כבר יש לו אינדקס (למשל אחרי הוספת מילים נרדפות)
        if index_store.load_term(term) and term not in only:
            print(f"{label}: כבר באינדקס, מדלגים")
            continue
        started = time.time()
        try:
            tracks = search_with_retry(sp, term)
        except RuntimeError as error:
            print(f"\n{error}")
            break
        # מושכים גם את מאפייני הקצב, כדי שהסינון לפי אווירה יהיה מהיר
        get_features([t["id"] for t in tracks if t.get("id")])
        index_store.save_term(term, tracks)
        print(f"{label}: {len(tracks)} שירים ב-{time.time() - started:.0f} שניות")
        time.sleep(PAUSE_SECONDS)

    print("סיימנו.", index_store.stats())


if __name__ == "__main__":
    main()
