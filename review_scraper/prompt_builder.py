"""
Builds the Stage 2 LLM audit prompt from audit_prompt.txt, moved here from the
frontend so the Gemini API key never has to reach the browser.
"""

import hashlib
import json
import os
import secrets

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'audit_prompt.txt')
_QA_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'qa_prompt.txt')

# PROMPT_VERSION = first 8 hex chars of the prompt template's sha256.
# Stored alongside cached scores so stale results from an older prompt
# are never mixed with results from a newer one.
_template_cache: dict = {}


def load_template() -> str:
    if 'text' not in _template_cache:
        with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            text = f.read()
        _template_cache['text'] = text
        _template_cache['version'] = hashlib.sha256(text.encode()).hexdigest()[:8]
    return _template_cache['text']


def get_prompt_version() -> str:
    """Return the 8-char sha256 prefix of the current audit_prompt.txt."""
    load_template()  # ensure cache is populated
    return _template_cache['version']


def load_qa_template() -> str:
    with open(_QA_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def build_review_payload(reviews: list) -> list:
    """Shapes reviews into {id, text} as documented in the new audit_prompt.txt.
    No stars, daysElapsed, isSpikePeriod, or signals — LLM only scores I/A/D."""
    return [
        {
            'id': i,
            'text': r.get('text', '') or '',
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


def build_qa_prompt(store_name: str, reviews: list, question: str) -> str:
    template = load_qa_template()
    payload = [
        {
            'id': str(r.get('id') or f"r{i}"),
            'username': str(r.get('username') or 'Anonymous'),
            'stars': r.get('stars') or 5,
            'text': str(r.get('text') or '')
        }
        for i, r in enumerate(reviews)
    ]
    return (
        template
        .replace('{store_name}', store_name or '待審查店家')
        .replace('{reviews_json}', json.dumps(payload, ensure_ascii=False, indent=2))
        .replace('{user_question}', question)
    )
