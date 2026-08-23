"""
Stage 2 Gemini audit: batching + response parsing, split out from server.py so
it can be unit tested without spinning up Flask or hitting the real API.
"""

import json
import math
import re

from prompt_builder import build_prompt, build_summarize_prompt

MODEL_NAME = 'gemini-2.5-flash'

# Target ~40 reviews per batch (within the 30-50 range asked for); batches are
# split as evenly as possible so the last batch isn't a small remainder.
TARGET_BATCH_SIZE = 40
MAX_BATCH_SIZE = 50
MAX_CONCURRENT_BATCHES = 5


def make_batches(reviews: list, target_size: int = TARGET_BATCH_SIZE, max_size: int = MAX_BATCH_SIZE) -> list:
    total = len(reviews)
    if total == 0:
        return []

    # Sort by posting time (daysElapsed ascending) before splitting so that
    # temporally-close reviews land in the same batch — Gemini can only
    # cross-reference clustering/spike patterns among reviews it sees together
    # in one prompt, not across separate batches.
    sorted_reviews = sorted(reviews, key=lambda r: r.get('daysElapsed', 0))

    if total <= max_size:
        return [sorted_reviews]

    batch_count = math.ceil(total / target_size)
    base, remainder = divmod(total, batch_count)

    batches = []
    idx = 0
    for i in range(batch_count):
        size = base + (1 if i < remainder else 0)
        batches.append(sorted_reviews[idx:idx + size])
        idx += size
    return batches


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\n?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\n?```$', '', text, flags=re.IGNORECASE).strip()
    return text


def _extract_json_block(text: str) -> str:
    array_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', text)
    if array_match:
        return array_match.group(0)
    obj_match = re.search(r'\{[\s\S]*\}', text)
    if obj_match:
        return obj_match.group(0)
    return text


def parse_gemini_json(raw_text: str) -> list:
    """Parses Gemini's text response into a list of per-review audit dicts.
    Raises ValueError if the content isn't recoverable as a JSON list."""
    cleaned = _extract_json_block(_strip_markdown_fences(raw_text or ''))
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f'Gemini 回傳內容非合法 JSON：{e}') from e

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ('reviews', 'results'):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        for value in parsed.values():
            if isinstance(value, list):
                return value
    raise ValueError('Gemini 回傳的內容不是有效的評論審查 JSON 陣列')


def call_gemini_batch(client, store_name: str, batch: list) -> list:
    """Sends one batch of normalized reviews to Gemini and returns the parsed
    per-review audit results. Raises ValueError/RuntimeError on failure —
    caller decides how to handle a failed batch."""
    prompt = build_prompt(store_name, batch)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config={'response_mime_type': 'application/json'},
    )
    return parse_gemini_json(getattr(response, 'text', None))

def parse_gemini_summary_json(raw_text: str) -> dict:
    """Parses Gemini's text response into the summarize dict (warnings & recommendations).
    Raises ValueError if the content isn't recoverable as a JSON dict."""
    cleaned = _strip_markdown_fences(raw_text or '')
    
    # Summarize returns an object, not an array. We extract the outermost object.
    obj_match = re.search(r'\{[\s\S]*\}', cleaned)
    if obj_match:
        cleaned = obj_match.group(0)
        
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f'Gemini 回傳內容非合法 JSON：{e}') from e

    if isinstance(parsed, dict):
        if 'warnings' not in parsed:
            parsed['warnings'] = []
        if 'recommendations' not in parsed:
            parsed['recommendations'] = []
        return parsed

    raise ValueError('Gemini 回傳的內容不是有效的總結 JSON 物件')

def call_gemini_summarize(client, store_name: str, reviews: list) -> dict:
    """Filters genuine reviews and sends them to Gemini for single-mode summarization."""
    # 1. Strict filter for genuine reviews WITH text
    genuine_reviews = [
        r for r in reviews 
        if r.get('isWashed') is False and str(r.get('text', '')).strip() != ''
    ]
    
    # 2. Sort by text length (descending) and truncate to top 150 to save tokens and prioritize rich content
    genuine_reviews.sort(key=lambda x: len(str(x.get('text', ''))), reverse=True)
    genuine_reviews = genuine_reviews[:150]
    
    if not genuine_reviews:
        return {'warnings': [], 'recommendations': []}

    # 3. Anonymize IDs (map long Google IDs to R1, R2...) to save tokens and prevent hallucination
    id_map = {}
    summarize_material = []
    
    for i, r in enumerate(genuine_reviews):
        short_id = f"R{i+1}"
        id_map[short_id] = r.get('id')
        summarize_material.append({
            'id': short_id,
            'username': r.get('username'),
            'stars': r.get('stars'),
            'text': r.get('text')
        })

    prompt_text = build_summarize_prompt(
        store_name=store_name,
        reviews_json=json.dumps(summarize_material, ensure_ascii=False)
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt_text,
        config={'response_mime_type': 'application/json'},
    )
    
    # 4. Parse JSON and map back IDs, filtering out hallucinations
    parsed_json = parse_gemini_summary_json(getattr(response, 'text', None))
    
    def map_back(item):
        valid_ids = []
        for short_id in item.get('sourceReviewIds', []):
            real_id = id_map.get(short_id)
            if real_id:
                valid_ids.append(real_id)
        item['sourceReviewIds'] = valid_ids
        return item
        
    parsed_warnings = []
    for w in parsed_json.get('warnings', []):
        w_mapped = map_back(w)
        if w_mapped['sourceReviewIds']:
            parsed_warnings.append(w_mapped)
            
    parsed_recommendations = []
    for r in parsed_json.get('recommendations', []):
        r_mapped = map_back(r)
        if r_mapped['sourceReviewIds']:
            parsed_recommendations.append(r_mapped)
            
    parsed_json['warnings'] = parsed_warnings
    parsed_json['recommendations'] = parsed_recommendations
    
    return parsed_json
