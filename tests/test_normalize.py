from normalize import normalize_review


def test_text_is_none():
    result = normalize_review({"Username": "Alice", "Stars": 5, "Text": None})
    assert result["hasText"] is False
    assert result["text"] == ""


def test_text_is_empty_string():
    result = normalize_review({"Username": "Bob", "Stars": 5, "Text": "   "})
    assert result["hasText"] is False
    assert result["text"] == ""


def test_text_translated_fallback_when_text_is_none():
    result = normalize_review({
        "Username": "Carol",
        "Stars": 5,
        "Text": None,
        "TextTranslated": "Great ramen, friendly owner",
    })
    assert result["hasText"] is True
    assert result["text"] == "Great ramen, friendly owner"


def test_apify_style_lowercase_fields_supported():
    """normalize_review must accept the future Apify actor's field names
    (lowercase text/textTranslated/stars/name), not just the Playwright scraper's."""
    result = normalize_review({
        "name": "Dave",
        "stars": 4,
        "text": None,
        "textTranslated": "好吃",
    })
    assert result["username"] == "Dave"
    assert result["stars"] == 4
    assert result["hasText"] is True
    assert result["text"] == "好吃"


def test_image_count_from_comma_joined_string():
    result = normalize_review({
        "Username": "Eve", "Stars": 5, "Text": "推薦",
        "Images": "url1.jpg, url2.jpg, url3.jpg",
    })
    assert result["imageCount"] == 3


def test_image_count_from_list():
    result = normalize_review({
        "username": "Frank", "stars": 5, "text": "讚",
        "images": ["a.jpg", "b.jpg"],
    })
    assert result["imageCount"] == 2


def test_image_count_zero_when_missing():
    result = normalize_review({"Username": "Grace", "Stars": 5, "Text": "好吃"})
    assert result["imageCount"] == 0


def test_stars_defaults_to_5_when_invalid():
    result = normalize_review({"Username": "Hank", "Stars": "not-a-number", "Text": "讚"})
    assert result["stars"] == 5


def test_username_defaults_to_anonymous_when_missing():
    result = normalize_review({"Stars": 5, "Text": "讚"})
    assert result["username"] == "Anonymous"
