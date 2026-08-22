"""
Stage 2 LLM audit: batching + response parsing, split out from server.py so
it can be unit tested without spinning up Flask or hitting the real API.
"""

import json
import math
import re
import time
import random

from prompt_builder import build_prompt, build_qa_prompt

MODEL_NAME_GEMINI = 'gemini-2.5-flash'
MODEL_NAME_DEEPSEEK = 'deepseek-chat'

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


def parse_llm_json(raw_text: str) -> list:
    """Parses LLM's text response into a list of per-review audit dicts.
    Raises ValueError if the content isn't recoverable as a JSON list."""
    cleaned = _extract_json_block(_strip_markdown_fences(raw_text or ''))
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f'LLM 回傳內容非合法 JSON：{e}') from e

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ('reviews', 'results'):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        for value in parsed.values():
            if isinstance(value, list):
                return value
    raise ValueError('LLM 回傳的內容不是有效的評論審查 JSON 陣列')


def call_llm_batch(provider: str, client, store_name: str, batch: list, max_retries: int = 2) -> list:
    """Sends one batch of normalized reviews to the LLM and returns the parsed
    per-review audit results. Automatically retries on transient errors/JSON decode failures.
    Raises ValueError/RuntimeError on failure after exhausting retries."""
    prompt = build_prompt(store_name, batch)
    if provider not in ('gemini', 'deepseek'):
        raise ValueError(f"Unknown LLM provider: {provider}")
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            if provider == 'gemini':
                response = client.models.generate_content(
                    model=MODEL_NAME_GEMINI,
                    contents=prompt,
                    config={
                        'response_mime_type': 'application/json',
                        'http_options': {'timeout': 60_000},  # 60s per batch, well under gunicorn's 120s
                    },
                )
                raw_text = getattr(response, 'text', None)
            elif provider == 'deepseek':
                response = client.chat.completions.create(
                    model=MODEL_NAME_DEEPSEEK,
                    messages=[
                        {"role": "system", "content": "你是一個數據分析助手。你必須輸出包含 'results' 陣列的 JSON 物件。"},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={'type': 'json_object'},
                    timeout=60.0
                )
                raw_text = response.choices[0].message.content
                
            return parse_llm_json(raw_text)
            
        except (ValueError, KeyError, TypeError) as e:
            raise  # Do not retry parsing, validation, or prompt errors
        except Exception as e:
            # 只重試網路或暫時性錯誤 (Timeout, Connection, 5xx RateLimit)
            err_name = type(e).__name__
            transient_errors = (
                'ConnectionError', 'TimeoutError', 'Timeout',
                'APIError', 'APIConnectionError', 'APITimeoutError',
                'RateLimitError', 'InternalServerError', 'ServiceUnavailableError',
                'HTTPError', 'HTTPStatusError', 'RequestException',
            )
            if err_name not in transient_errors:
                raise
                
            last_exception = e
            if attempt < max_retries:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))  # Exponential backoff (1s, 2s) + jitter
            else:
                break
                
    raise last_exception


def parse_qa_llm_json(raw_text: str) -> dict:
    cleaned = _extract_json_block(_strip_markdown_fences(raw_text or ''))
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f'LLM 回傳內容非合法 JSON：{e}') from e

    if not isinstance(parsed, dict) or 'answer' not in parsed:
        raise ValueError('LLM 回傳的內容不是有效的 QA JSON 格式')
        
    # Schema normalization to prevent frontend crashes
    parsed['items'] = parsed.get('items', [])
    if not isinstance(parsed['items'], list):
        parsed['items'] = []
    parsed['sufficient'] = bool(parsed.get('sufficient', True))
    
    return parsed


def call_llm_qa(provider: str, client, store_name: str, reviews: list, question: str, max_retries: int = 2) -> dict:
    prompt = build_qa_prompt(store_name, reviews, question)
    
    if provider not in ('gemini', 'deepseek'):
        raise ValueError(f"Unknown LLM provider: {provider}")

    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            if provider == 'gemini':
                response = client.models.generate_content(
                    model=MODEL_NAME_GEMINI,
                    contents=prompt,
                    config={'response_mime_type': 'application/json'},
                )
                raw_text = getattr(response, 'text', None)
            elif provider == 'deepseek':
                response = client.chat.completions.create(
                    model=MODEL_NAME_DEEPSEEK,
                    messages=[
                        {"role": "system", "content": "You are a data analysis assistant. You must output a JSON object."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={'type': 'json_object'},
                    timeout=60.0
                )
                raw_text = response.choices[0].message.content
                
            return parse_qa_llm_json(raw_text)
            
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
            else:
                break
                
    raise last_exception
