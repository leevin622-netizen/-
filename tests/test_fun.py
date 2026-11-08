"""אפקטי הכיף: אימוג'ים צפים ברקע, וקונפטי בלחיצה."""
import themes
from scripts import FUN_JS


def test_every_theme_has_floating_emojis():
    for theme in themes.THEMES:
        html = themes.emoji_html(theme)
        assert html.count('class="emoji-float"') == 8
        assert 'aria-hidden="true"' in html


def test_background_has_emoji_layer_with_and_without_images():
    assert "emoji-layer" in themes.background_html([], "rock")
    assert "emoji-layer" in themes.background_html(["https://img/1"], "pop")


def test_pages_include_confetti_script(client):
    html = client.get("/").get_data(as_text=True)
    assert FUN_JS in html and "emoji-layer" in html


def test_confetti_respects_reduced_motion():
    assert "prefers-reduced-motion: reduce" in FUN_JS
