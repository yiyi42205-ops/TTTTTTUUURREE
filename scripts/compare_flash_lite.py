#!/usr/bin/env python3 -u
"""
Compare Gemini 2.5 Flash vs Flash-Lite on the same reviews using the SAME prompt.
Sends identical reviews to both models and prints a side-by-side comparison.

Cost: ~$0.02 (20 reviews × 2 models)

Usage:
  python scripts/compare_flash_lite.py
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from dotenv import load_dotenv
from google import genai

from cache_store import iter_all_scrape_cache, get_cached_stage2, get_cached_metadata
from rule_engine import run_stage1_audit
from prompt_builder import build_prompt
from llm_client import parse_llm_json

load_dotenv(Path(__file__).resolve().parent.parent / '.env')
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    print('❌ GEMINI_API_KEY not set')
    sys.exit(1)

client = genai.Client(
    api_key=api_key,
    http_options={'retry_options': {'attempts': 1}},
)

now = datetime.now()

# Find a store with cached Stage 2 results (to reuse the same reviews)
print('Finding a store with cached Stage 2 results...')
target_place_id = None
target_reviews = None
target_cached = None
target_store_name = None

for place_id, reviews in iter_all_scrape_cache():
    cached = get_cached_stage2(place_id)
    if len(cached) >= 5:
        target_place_id = place_id
        target_reviews = reviews
        target_cached = cached
        meta = get_cached_metadata(place_id)
        target_store_name = (meta or {}).get('title', place_id[:40])
        break

if not target_place_id:
    print('❌ No store found with cached Stage 2 results')
    sys.exit(1)

print(f'Store: {target_store_name}')

# Run Stage 1 to get signals
stage1 = run_stage1_audit(target_reviews)
audited = stage1['auditedReviews']
signals = stage1['signals']
spike_months_set = set(signals.get('spikeMonths', []))
similarity = signals.get('similarity', [])
hot_term = signals.get('hotTerm', [])
nearby_long = signals.get('nearbyLongReviewCounts', [])

# Build enriched reviews
to_send = []
for idx, r in enumerate(audited):
    username = r.get('username', '')
    if username not in target_cached:
        continue

    month = (r.get('time') or '')[:7]
    days_elapsed = 0
    if r.get('time'):
        try:
            rd = datetime.fromisoformat(r['time'][:10])
            days_elapsed = max(0, (now - rd).days)
        except (ValueError, TypeError):
            pass

    sim = similarity[idx] if idx < len(similarity) else {}
    ht = hot_term[idx] if idx < len(hot_term) else {}
    nlr = nearby_long[idx] if idx < len(nearby_long) else 0

    to_send.append({
        'username': username,
        'text': r.get('text', '') or '',
        'stars': r.get('stars', 5),
        'images': r.get('images', []),
        'daysElapsed': days_elapsed,
        'isSpikePeriod': month in spike_months_set,
        'maxSimilarity': sim.get('maxSimilarity', 0),
        'similarCount': sim.get('similarCount', 0),
        'hotTermCount': ht.get('hotTermCount', 0),
        'hotTermMaxRatio': ht.get('hotTermMaxRatio', 0),
        'nearbyLongReviewCount': nlr,
    })

if not to_send:
    print('❌ No reviews to compare')
    sys.exit(1)

to_send = to_send[:20]
prompt = build_prompt(target_store_name, to_send)

config = {
    'response_mime_type': 'application/json',
    'http_options': {'timeout': 60_000},
    'thinking_config': {'thinking_budget': 0},
}

# Call both models with the SAME prompt
models = ['gemini-2.5-flash', 'gemini-2.5-flash-lite']
results = {}
for model in models:
    print(f'Sending {len(to_send)} reviews to {model}...')
    try:
        response = client.models.generate_content(
            model=model, contents=prompt, config=config,
        )
        raw_text = getattr(response, 'text', None)
        parsed = parse_llm_json(raw_text)
        results[model] = {r['username']: r for r in parsed}
    except Exception as e:
        print(f'  ⚠️ {model} failed: {e}')
        results[model] = {}

if not results.get('gemini-2.5-flash') and not results.get('gemini-2.5-flash-lite'):
    print('❌ Both models failed')
    sys.exit(1)

flash = results['gemini-2.5-flash']
lite = results['gemini-2.5-flash-lite']

# Compare
print(f'\n{"="*90}')
print(f'{"Username":<20} {"Flash (new prompt)":^35} {"Flash-Lite (new prompt)":^35}')
print(f'{"":20} {"I  A  D  wash  issue":^35} {"I  A  D  wash  issue":^35}')
print(f'{"="*90}')

agree = disagree = 0
iad_diffs = []

for review in to_send:
    username = review['username']
    f = flash.get(username, {})
    l = lite.get(username, {})
    if not f or not l:
        continue

    f_i = f.get('incentiveIntensity', '?')
    f_a = f.get('sentimentAuthenticity', '?')
    f_d = f.get('descriptionGranularity', '?')
    f_w = f.get('isWashed', '?')
    f_t = f.get('issueType', '?')

    l_i = l.get('incentiveIntensity', '?')
    l_a = l.get('sentimentAuthenticity', '?')
    l_d = l.get('descriptionGranularity', '?')
    l_w = l.get('isWashed', '?')
    l_t = l.get('issueType', '?')

    match = '✅' if f_w == l_w else '❌'
    if f_w == l_w:
        agree += 1
    else:
        disagree += 1

    if isinstance(f_i, (int, float)) and isinstance(l_i, (int, float)):
        iad_diffs.append((abs(f_i - l_i), abs(f_a - l_a), abs(f_d - l_d)))

    f_str = f'{f_i}  {f_a}  {f_d}  {str(f_w):5}  {f_t}'
    l_str = f'{l_i}  {l_a}  {l_d}  {str(l_w):5}  {l_t}'

    print(f'{match} {username[:18]:<18} {f_str:^35} {l_str:^35}')

total = agree + disagree
if total > 0:
    print(f'\n{"="*90}')
    print(f'isWashed agreement: {agree}/{total} ({agree/total*100:.0f}%)')

    if iad_diffs:
        avg_i = sum(d[0] for d in iad_diffs) / len(iad_diffs)
        avg_a = sum(d[1] for d in iad_diffs) / len(iad_diffs)
        avg_d = sum(d[2] for d in iad_diffs) / len(iad_diffs)
        print(f'Average IAD difference: I={avg_i:.1f}  A={avg_a:.1f}  D={avg_d:.1f}')
        print(f'(0 = perfect match, >1 = significant divergence)')
