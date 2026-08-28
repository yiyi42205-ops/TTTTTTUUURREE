"""
Stage 2 LLM audit: batching + response parsing, split out from server.py so
it can be unit tested without spinning up Flask or hitting the real API.
"""

import json
import logging
import math
import re
import time
import random

from prompt_builder import build_prompt, build_qa_prompt, build_summary_prompt

logger = logging.getLogger("ScraperServer")

MODEL_NAME_GEMINI = 'gemini-2.5-flash-lite'
MODEL_NAME_DEEPSEEK = 'deepseek-chat'

# Default model name for OpenAI-compatible providers; callers override via
# the model_name parameter when the user specifies a custom model.
MODEL_NAME_OPENAI_COMPAT = 'gpt-3.5-turbo'

# LLM only outputs I/A/D scores now — these are the required fields.
_REQUIRED_FIELDS = {'id', 'reasoning', 'incentiveIntensity', 'sentimentAuthenticity', 'descriptionGranularity'}

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


def _validate_score_item(item: dict, max_id: int) -> bool:
    """Return True if item has all required fields with valid values."""
    if not isinstance(item, dict):
        return False
    if not _REQUIRED_FIELDS.issubset(item.keys()):
        return False
    # id must be an integer in [0, max_id]
    item_id = item.get('id')
    if not isinstance(item_id, int) or item_id < 0 or item_id > max_id:
        return False
    # I/A/D must be integers in [1, 5]
    for key in ('incentiveIntensity', 'sentimentAuthenticity', 'descriptionGranularity'):
        val = item.get(key)
        if not isinstance(val, int) or val < 1 or val > 5:
            return False
    # reasoning over 40 chars is a warning, not disqualifying
    reasoning = item.get('reasoning', '')
    if isinstance(reasoning, str) and len(reasoning) > 40:
        logger.warning(f"review id={item_id}: reasoning exceeds 40 chars ({len(reasoning)})")
    return True


def _call_llm_raw(provider: str, client, prompt: str, model_name: str | None = None) -> str:
    """Send prompt to LLM and return raw text response.

    *model_name* overrides the default model for openai_compatible / deepseek
    providers. Ignored for gemini (which uses MODEL_NAME_GEMINI).
    """
    if provider == 'gemini':
        response = client.models.generate_content(
            model=MODEL_NAME_GEMINI,
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'max_output_tokens': 8192,
                'http_options': {'timeout': 60_000},
            },
        )
        return getattr(response, 'text', None)
    elif provider in ('deepseek', 'openai_compatible'):
        effective_model = model_name or (MODEL_NAME_DEEPSEEK if provider == 'deepseek' else MODEL_NAME_OPENAI_COMPAT)
        response = client.chat.completions.create(
            model=effective_model,
            messages=[
                {"role": "system", "content": "你是一個數據分析助手。直接輸出 JSON 數組。"},
                {"role": "user", "content": prompt}
            ],
            response_format={'type': 'json_object'},
            max_tokens=8192,
            timeout=60.0,
        )
        return response.choices[0].message.content
    raise ValueError(f"Unknown LLM provider: {provider}")


def call_llm_batch(provider: str, client, store_name: str, batch: list,
                    max_retries: int = 2, model_name: str | None = None) -> list:
    """Sends one batch of reviews to the LLM and returns validated score dicts.

    Each returned dict has: id, reasoning, incentiveIntensity,
    sentimentAuthenticity, descriptionGranularity.
    Invalid items are dropped. If valid count < 90% of batch, the batch is
    split in half and retried once.
    """
    prompt = build_prompt(store_name, batch)
    if provider not in ('gemini', 'deepseek', 'openai_compatible'):
        raise ValueError(f"Unknown LLM provider: {provider}")

    n = len(batch)
    max_id = n - 1
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            raw_text = _call_llm_raw(provider, client, prompt, model_name=model_name)
            items = parse_llm_json(raw_text)

            # Validate and deduplicate
            seen_ids = set()
            valid = []
            for item in items:
                if _validate_score_item(item, max_id) and item['id'] not in seen_ids:
                    seen_ids.add(item['id'])
                    valid.append(item)
                else:
                    logger.warning(f"Dropped invalid LLM item: {item}")

            # If coverage is sufficient, return
            if len(valid) >= n * 0.9:
                return valid

            # Coverage too low — split in half and retry once
            if attempt == 0 and n > 1:
                logger.warning(
                    f"LLM returned {len(valid)}/{n} valid items, splitting batch in half and retrying"
                )
                mid = n // 2
                left = call_llm_batch(provider, client, store_name, batch[:mid], max_retries=0, model_name=model_name)
                right_items = call_llm_batch(provider, client, store_name, batch[mid:], max_retries=0, model_name=model_name)
                # Remap ids for the right half
                for item in right_items:
                    item['id'] = item['id'] + mid
                return left + right_items

            # Still not enough after retry — return what we have
            return valid

        except (ValueError, KeyError, TypeError) as e:
            raise
        except Exception as e:
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
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
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


def call_llm_qa(provider: str, client, store_name: str, reviews: list, question: str,
                max_retries: int = 2, model_name: str | None = None) -> dict:
    prompt = build_qa_prompt(store_name, reviews, question)

    if provider not in ('gemini', 'deepseek', 'openai_compatible'):
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
            else:  # deepseek / openai_compatible
                effective_model = model_name or (MODEL_NAME_DEEPSEEK if provider == 'deepseek' else MODEL_NAME_OPENAI_COMPAT)
                response = client.chat.completions.create(
                    model=effective_model,
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


def parse_summary_llm_json(raw_text: str) -> dict:
    """Parse LLM response for store summary into {warnings, recommendations}."""
    cleaned = _extract_json_block(_strip_markdown_fences(raw_text or ''))
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f'LLM 回傳內容非合法 JSON：{e}') from e

    if not isinstance(parsed, dict):
        raise ValueError('LLM 回傳的內容不是有效的總結 JSON 格式')

    warnings = parsed.get('warnings', [])
    if not isinstance(warnings, list):
        warnings = []
    recommendations = parsed.get('recommendations', [])
    if not isinstance(recommendations, list):
        recommendations = []

    return {'warnings': warnings, 'recommendations': recommendations}


def call_llm_summary(provider: str, client, store_name: str, reviews: list,
                     max_retries: int = 2, model_name: str | None = None) -> dict:
    """Call LLM with summarize_prompt.txt, return {warnings, recommendations}."""
    prompt = build_summary_prompt(store_name, reviews)

    if provider not in ('gemini', 'deepseek', 'openai_compatible'):
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
            else:  # deepseek / openai_compatible
                effective_model = model_name or (MODEL_NAME_DEEPSEEK if provider == 'deepseek' else MODEL_NAME_OPENAI_COMPAT)
                response = client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {"role": "system", "content": "你是一個餐廳評論分析師。直接輸出 JSON。"},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={'type': 'json_object'},
                    timeout=60.0,
                )
                raw_text = response.choices[0].message.content

            return parse_summary_llm_json(raw_text)

        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
            else:
                break

    raise last_exception
