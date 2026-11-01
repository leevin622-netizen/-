"""
כל טקסט בממשק צריך תרגום לאנגלית. מפתח התרגום הוא הטקסט העברי המלא, ולכן שינוי של אות אחת
בטקסט שובר את התרגום בשקט. הבדיקה הזו תופסת את זה.
"""
import ast
import glob
import os

import catalog
import engine
import themes
from conftest import ROOT
from translations import TRANSLATIONS


def literal_texts():
    """כל המחרוזות שעטופות ב-_() בקוד, עם הקובץ והשורה."""
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                yield os.path.basename(path), node.lineno, node.args[0].value


def menu_labels():
    """שמות מהתפריטים ומהקטגוריות, שמתורגמים דרך משתנה ולא כמחרוזת בקוד."""
    yield from engine.GENRE_HINTS
    yield from engine.EVENT_HINTS
    yield from engine.EVENT_GROUPS
    yield from engine.LANGUAGES
    yield from (label for label, _term in engine.GENRE_CHOICES)
    yield from (label for _key, label, _terms in catalog.CATEGORIES)
    yield from (theme["label"] for theme in themes.THEMES.values())


def has_english(text):
    return bool(TRANSLATIONS.get(text, {}).get("en"))


def test_every_interface_text_has_english():
    missing = [f"{path}:{line} {text[:60]!r}" for path, line, text in literal_texts() if not has_english(text)]
    assert not missing, "\n".join(missing)


def test_every_menu_label_has_english():
    missing = [label for label in menu_labels() if not has_english(label)]
    assert not missing, missing


def test_translations_keep_placeholders():
    """תרגום שמאבד {a0} יציג סוגריים ריקים או ייפול."""
    broken = []
    for text, langs in TRANSLATIONS.items():
        english = langs.get("en") or ""
        for n in range(10):
            mark = "{a%d}" % n
            if mark in text and mark not in english:
                broken.append((text[:60], mark))
    assert not broken, broken
