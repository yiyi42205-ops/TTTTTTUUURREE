"""
Normalizes a single raw review record into the shape used for prompting Gemini.

Accepts both the current Playwright scraper's field names (Username, Stars,
Time, Text, Images as a comma-joined string) and the field names of the Apify
"Google Maps Reviews Scraper" actor (text/textTranslated/stars/publishedAtDate/
reviewImageUrls), since the in-house Playwright scraper is a transitional
stopgap expected to be replaced by that Apify actor later.
"""

from typing import Optional


def _first(raw: dict, *keys, default=None):
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return default


def _clean_text(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text != '' else None


def _extract_images(images_raw) -> list:
    if images_raw is None:
        return []
    if isinstance(images_raw, list):
        return [img for img in images_raw if img]
    if isinstance(images_raw, str):
        return [img.strip() for img in images_raw.split(',') if img.strip()]
    return []


def normalize_review(raw: dict) -> dict:
    username = _first(raw, 'Username', 'username', 'name', 'reviewerName', default='Anonymous')

    stars = _first(raw, 'Stars', 'stars', 'rating', default=5)
    try:
        stars = int(stars)
    except (TypeError, ValueError):
        stars = 5

    time_value = _first(raw, 'Time', 'time', 'publishedAtDate', 'publishedAt', default='') or ''

    text = _clean_text(_first(raw, 'Text', 'text', default=None))
    text_translated = _clean_text(_first(raw, 'TextTranslated', 'textTranslated', default=None))

    # A translated-only review still has real content to audit — fall back to it
    # rather than treating the review as text-less just because the original
    # language field is empty.
    has_text = text is not None or text_translated is not None
    effective_text = text if text is not None else (text_translated or '')

    images = _extract_images(_first(raw, 'Images', 'images', 'reviewImageUrls', default=None))

    return {
        'username': username,
        'stars': stars,
        'time': time_value,
        'text': effective_text,
        'hasText': has_text,
        'images': images,
        'imageCount': len(images),
    }
