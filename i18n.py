"""
שפת הממשק. עברית היא שפת המקור: כל טקסט בקוד כתוב בעברית ועטוף ב-_(), והתרגומים ב-translations.py.
טקסט בלי תרגום מוצג בעברית, כך ששום דבר לא נשבר כשמוסיפים טקסט חדש.
"""
from flask import has_request_context, session

from translations import TRANSLATIONS

# (קוד, שם בשפה עצמה, כיוון כתיבה)
LANGS = [
    ("he", "עברית", "rtl"),
    ("en", "English", "ltr"),
]
CODES = {code for code, _name, _dir in LANGS}
DIRECTION = {code: direction for code, _name, direction in LANGS}


def lang():
    if has_request_context():
        code = session.get("lang", "he")
        return code if code in CODES else "he"
    return "he"


def text_dir():
    return DIRECTION[lang()]


def _(text, **values):
    """הטקסט בשפה הנוכחית. values ממלאים מקומות כמו {a0} אחרי התרגום."""
    code = lang()
    if code != "he":
        text = TRANSLATIONS.get(text, {}).get(code) or text
    return text.format(**values) if values else text


# טקסטים בתוך קוד ה-JavaScript של העמודים. מתורגמים בהחלפה, כי הם בתוך מחרוזות JS קבועות
JS_TEXTS = ["סגירת הנגן", "נגן ספוטיפיי", "לא נמצא קטע לשיר הזה", "✅ הועתק", "בטל סימון של המוצגים", "סמן את כל המוצגים"]


def translate_js(code):
    if lang() == "he":
        return code
    for text in JS_TEXTS:
        code = code.replace(text, _(text))
    return code
