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
_SUMMARY_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'summarize_prompt.txt')

# PROMPT_VERSION = first 8 hex chars of the sha256 of the scoring-criteria
# section of audit_prompt.txt (everything before "# 輸出格式").  Only changes
# to the scoring rubric invalidate the cache; output-format tweaks (e.g.
# reasoning length cap) do not.
_SCORING_SECTION_END = '# 輸出格式'

_template_cache: dict = {}


def load_template() -> str:
    if 'text' not in _template_cache:
        with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            text = f.read()
        _template_cache['text'] = text
        # Hash only the scoring criteria (before output-format instructions)
        scoring = text[:text.index(_SCORING_SECTION_END)]
        _template_cache['version'] = hashlib.sha256(scoring.encode()).hexdigest()[:8]
    return _template_cache['text']


def get_prompt_version() -> str:
    """Return the 8-char sha256 prefix of the scoring criteria in audit_prompt.txt."""
    load_template()  # ensure cache is populated
    return _template_cache['version']


def load_qa_template() -> str:
    with open(_QA_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def build_review_payload(reviews: list) -> list:
    """Shapes reviews into {id, stars, text} for the audit prompt.
    Stars are included so the LLM can detect star-text contradictions."""
    return [
        {
            'id': i,
            'stars': r.get('stars', 5),
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


def load_summary_template() -> str:
    with open(_SUMMARY_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def build_summary_prompt(store_name: str, reviews: list) -> str:
    template = load_summary_template()
    payload = [
        {
            'id': str(r.get('id') or r.get('username') or f"r{i}"),
            'username': str(r.get('username') or 'Anonymous'),
            'stars': r.get('stars') or 5,
            'text': str(r.get('text') or '')
        }
        for i, r in enumerate(reviews)
    ]
    random_tag = f"review_data_{secrets.token_hex(4)}"
    return (
        template
        .replace('<review_data>', f'<{random_tag}>')
        .replace('</review_data>', f'</{random_tag}>')
        .replace('{store_name}', store_name or '待審查店家')
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
    review_tag = f"review_data_{secrets.token_hex(4)}"
    question_tag = f"user_question_{secrets.token_hex(4)}"
    return (
        template
        .replace('<review_data>', f'<{review_tag}>')
        .replace('</review_data>', f'</{review_tag}>')
        .replace('<user_question>', f'<{question_tag}>')
        .replace('</user_question>', f'</{question_tag}>')
        .replace('{store_name}', store_name or '待審查店家')
        .replace('{reviews_json}', json.dumps(payload, ensure_ascii=False, indent=2))
        .replace('{user_question}', question)
    )
