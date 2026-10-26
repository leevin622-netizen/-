"""
הגבלת קצב פשוטה לפי כתובת, בזיכרון. מי שמציף את האתר מקבל 429 עד שהחלון נפתח שוב.

האתר נגיש דרך ngrok, שמחבר את השרת מ-127.0.0.1. לכן הכתובת האמיתית של המבקר נמצאת בכותרת X-Forwarded-For.
ngrok מוסיף את הכתובת האמיתית בסוף הכותרת, אחרי מה שהמבקר שלח בעצמו, ולכן לוקחים את הערך האחרון.
מחוץ ל-127.0.0.1 לא סומכים על הכותרת בכלל.
"""
import threading
import time
from collections import defaultdict, deque

LOCAL_ADDRESSES = ("127.0.0.1", "::1")
# בלי הגבלה על מספר הכתובות בזיכרון. כשיש הרבה מדי, מנקים הכול, והגבלות מתחילות מחדש
MAX_KEYS = 10000

_hits = defaultdict(deque)
_lock = threading.Lock()


def client_ip(remote_addr, forwarded_for):
    """הכתובת שבה משתמשים להגבלה. מחוץ ל-ngrok, הכתובת המקומית של החיבור."""
    if remote_addr in LOCAL_ADDRESSES and forwarded_for:
        last = forwarded_for.split(",")[-1].strip()
        if last:
            return last[:64]
    return remote_addr or "unknown"


def allow(bucket, ip, limit, window):
    """
    True אם הבקשה מותרת. לכל כתובת יש עד limit בקשות בתוך window שניות, בנפרד לכל bucket.
    הבקשה שנדחתה לא נספרת, כדי שמי שנחסם לא יאריך את החסימה שלו בלחיצות נוספות.
    """
    now = time.time()
    with _lock:
        if len(_hits) > MAX_KEYS:
            _hits.clear()
        queue = _hits[(bucket, ip)]
        while queue and now - queue[0] > window:
            queue.popleft()
        if len(queue) >= limit:
            return False
        queue.append(now)
        return True


def reset():
    with _lock:
        _hits.clear()
