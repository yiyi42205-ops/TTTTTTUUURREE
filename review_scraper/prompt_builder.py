"""
Builds the Stage 2 LLM audit prompt from audit_prompt.txt, moved here from the
frontend so the Gemini API key never has to reach the browser.
"""

import json
import os
import secrets

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'audit_prompt.txt')


def load_template() -> str:
    with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def build_review_payload(reviews: list) -> list:
    """Shapes normalized reviews into the fields documented in audit_prompt.txt."""
    return [
        {
            'index': i,
            'username': r['username'],
            'text': r['text'],
            'stars': r['stars'],
            'daysElapsed': r.get('daysElapsed', 0),
            'isSpikePeriod': bool(r.get('isSpikePeriod', False)),
            'maxSimilarity': r.get('maxSimilarity', 0),
            'similarCount': r.get('similarCount', 0),
            'hotTermCount': r.get('hotTermCount', 0),
            'hotTermMaxRatio': r.get('hotTermMaxRatio', 0),
            'nearbyLongReviewCount': r.get('nearbyLongReviewCount', 0),
        }
        for i, r in enumerate(reviews)
    ]


def build_prompt(store_name: str, reviews: list) -> str:
    template = load_template()
    payload = build_review_payload(reviews)
    random_tag = f"review_data_{secrets.token_hex(4)}"

    return (
        template
        .replace('<review_data>', f'<{random_tag}>')
        .replace('</review_data>', f'</{random_tag}>')
        .replace('{store_name}', store_name or '待審查店家')
        .replace('{review_count}', str(len(payload)))
        .replace('{reviews_json}', json.dumps(payload, ensure_ascii=False, indent=2))
    )
