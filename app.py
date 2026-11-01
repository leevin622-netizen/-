"""
פלייליסטור: אפליקציית Flask שבונה פלייליסטים בספוטיפיי.
הקובץ הזה רק מחבר את החלקים: הבסיס (web.py) והדפים לפי אזורים (routes_*.py).
השרת מריץ את app:app (ראו start_server.vbs).
"""
import os

import build_playlists
import routes_build  # noqa: F401  (רישום הדפים)
import routes_catalog  # noqa: F401
import routes_home  # noqa: F401
import routes_library  # noqa: F401
import routes_playlists  # noqa: F401
from web import app

# בהפעלה מתחיל העדכון ברקע של אינדקס השירים ושל קטלוג הפלייליסטים (ראה build_playlists.py)
build_playlists.refresh_in_background()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_DEBUG") == "1")
