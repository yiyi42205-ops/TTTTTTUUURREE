#!/usr/bin/env python3 -u
"""
Send the 200 sampled ambiguous reviews to Flash + Flash-Lite in parallel,
then auto-compare verdicts.

Cost: ~$0.03 total (200 reviews × 5 batches × 2 models, thinking OFF)

Usage:
  review_scraper/venv/bin/python scripts/compare_200_flash_vs_lite.py

Outputs:
  eval/compare_200_results.json  — raw per-review results from both models
  stdout — side-by-side comparison table + summary stats
"""
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from dotenv import load_dotenv
from google import genai

from prompt_builder import build_prompt
from llm_client import make_batches, parse_llm_json

load_dotenv(Path(__file__).resolve().parent.parent / '.env')
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    print('❌ GEMINI_API_KEY not set')
    sys.exit(1)

client = genai.Client(
    api_key=api_key,
    http_options={'retry_options': {'attempts': 1}},
)

MODELS = ['gemini-2.5-flash', 'gemini-2.5-flash-lite']
SAMPLE_PATH = Path(__file__).resolve().parent.parent / 'eval' / 'ambiguous_sample_200.json'
OUTPUT_PATH = Path(__file__).resolve().parent.parent / 'eval' / 'compare_200_results.json'

# ── Load sampled reviews ───────────────────────────────────────────────

if not SAMPLE_PATH.exists():
    print(f'❌ {SAMPLE_PATH} not found — run sample_ambiguous_200.py first')
    sys.exit(1)

with open(SAMPLE_PATH, 'r', encoding='utf-8') as f:
    sampled = json.load(f)

print(f'Loaded {len(sampled)} sampled reviews')

# ── Batch reviews ──────────────────────────────────────────────────────

# Group by store for prompt building (build_prompt needs store_name)
by_store = {}
for r in sampled:
    sid = r['place_id']
    by_store.setdefault(sid, []).append(r)

# Build batches: we can't mix stores in a single prompt (signals are store-relative),
# so we group by store, then merge small store groups into batches of ~40.
# Since we sampled max 3 per store from 191 stores, most stores have 1 review.
# Strategy: send each store's reviews as a mini-batch (prompt per store),
# then aggregate results. This is more accurate than mixing stores.
store_batches = []
for sid, reviews in by_store.items():
    store_name = reviews[0].get('store', sid[:40])
    store_batches.append((store_name, reviews))

print(f'{len(store_batches)} stores → merging into larger batches...')

# Merge small store batches together. Since reviews from different stores
# can't share signals, we build one prompt per store but send multiple
# stores in parallel via threading.
# Actually, for cost efficiency, let's just batch them as-is grouped by store.
# 191 stores × 2 models = 382 API calls — too many.
# Better: send all 200 reviews in 5 batches of 40, using a generic store name.
# The signals (similarity, hotTerm, etc.) are already pre-computed in the sample JSON,
# so the prompt doesn't need store-specific context.

batches = make_batches(sampled)
print(f'Split into {len(batches)} batches of sizes: {[len(b) for b in batches]}')


def call_model(model: str, batch_idx: int, batch: list) -> dict:
    """Send one batch to one model, return parsed results keyed by username."""
    prompt = build_prompt('待審查店家', batch)
    config = {
        'response_mime_type': 'application/json',
        'http_options': {'timeout': 120_000},
        'thinking_config': {'thinking_budget': 0},
    }
    try:
        response = client.models.generate_content(
            model=model, contents=prompt, config=config,
        )
        raw_text = getattr(response, 'text', None)
        parsed = parse_llm_json(raw_text)
        return {r['username']: r for r in parsed}
    except Exception as e:
        print(f'  ⚠️ {model} batch {batch_idx} failed: {e}')
        return {}


# ── Send to both models in parallel ───────────────────────────────────

results = {m: {} for m in MODELS}
total_calls = len(batches) * len(MODELS)
completed = 0
t0 = time.time()

print(f'\nSending {total_calls} API calls ({len(batches)} batches × {len(MODELS)} models)...')

with ThreadPoolExecutor(max_workers=4) as pool:
    futures = {}
    for model in MODELS:
        for i, batch in enumerate(batches):
            fut = pool.submit(call_model, model, i, batch)
            futures[fut] = (model, i)

    for fut in as_completed(futures):
        model, batch_idx = futures[fut]
        batch_results = fut.result()
        results[model].update(batch_results)
        completed += 1
        print(f'  [{completed}/{total_calls}] {model} batch {batch_idx}: {len(batch_results)} reviews parsed')

elapsed = time.time() - t0
print(f'\nAll calls completed in {elapsed:.1f}s')

for m in MODELS:
    print(f'  {m}: {len(results[m])} reviews returned')

# ── Compare ────────────────────────────────────────────────────────────

flash = results[MODELS[0]]
lite = results[MODELS[1]]

# Header
print(f'\n{"="*100}')
print(f'{"Username":<20} {"Flash":^40} {"Flash-Lite":^40}')
print(f'{"":20} {"I  A  D  wash  issue  basis":^40} {"I  A  D  wash  issue  basis":^40}')
print(f'{"="*100}')

agree = 0
disagree = 0
flash_only_washed = 0
lite_only_washed = 0
iad_diffs = []
issue_type_agree = 0
issue_type_disagree = 0
basis_agree = 0

# Track verdict distribution
flash_washed_count = 0
lite_washed_count = 0
flash_issue_dist = Counter()
lite_issue_dist = Counter()

for review in sampled:
    username = review['username']
    f = flash.get(username)
    l = lite.get(username)
    if not f or not l:
        continue

    f_i = f.get('incentiveIntensity', '?')
    f_a = f.get('sentimentAuthenticity', '?')
    f_d = f.get('descriptionGranularity', '?')
    f_w = f.get('isWashed', '?')
    f_t = f.get('issueType', '-') or '-'
    f_b = f.get('verdictBasis', '?')

    l_i = l.get('incentiveIntensity', '?')
    l_a = l.get('sentimentAuthenticity', '?')
    l_d = l.get('descriptionGranularity', '?')
    l_w = l.get('isWashed', '?')
    l_t = l.get('issueType', '-') or '-'
    l_b = l.get('verdictBasis', '?')

    # isWashed agreement
    if f_w == l_w:
        agree += 1
        mark = '✅'
    else:
        disagree += 1
        mark = '❌'
        if f_w is True and l_w is not True:
            flash_only_washed += 1
        elif l_w is True and f_w is not True:
            lite_only_washed += 1

    # issueType agreement
    if f_t == l_t:
        issue_type_agree += 1
    else:
        issue_type_disagree += 1

    # verdictBasis agreement
    if f_b == l_b:
        basis_agree += 1

    # IAD diff
    if isinstance(f_i, (int, float)) and isinstance(l_i, (int, float)):
        iad_diffs.append((abs(f_i - l_i), abs(f_a - l_a), abs(f_d - l_d)))

    # Distribution
    if f_w is True:
        flash_washed_count += 1
        flash_issue_dist[f_t] += 1
    if l_w is True:
        lite_washed_count += 1
        lite_issue_dist[l_t] += 1

    f_str = f'{f_i}  {f_a}  {f_d}  {str(f_w):5}  {f_t:11}  {f_b}'
    l_str = f'{l_i}  {l_a}  {l_d}  {str(l_w):5}  {l_t:11}  {l_b}'

    text_preview = review['text'][:25].replace('\n', ' ')
    print(f'{mark} {username[:18]:<18} {f_str:^40} {l_str:^40}  {text_preview}')

total = agree + disagree

# ── Summary stats ──────────────────────────────────────────────────────

print(f'\n{"="*100}')
print(f'SUMMARY ({total} reviews compared)')
print(f'{"="*100}')

if total > 0:
    print(f'\n📊 isWashed agreement: {agree}/{total} ({agree/total*100:.1f}%)')
    print(f'   Flash says washed, Lite says clean: {flash_only_washed}')
    print(f'   Lite says washed, Flash says clean: {lite_only_washed}')

    print(f'\n📊 issueType agreement: {issue_type_agree}/{total} ({issue_type_agree/total*100:.1f}%)')
    print(f'   verdictBasis agreement: {basis_agree}/{total} ({basis_agree/total*100:.1f}%)')

    print(f'\n📊 Washed verdict rate:')
    print(f'   Flash:      {flash_washed_count}/{total} ({flash_washed_count/total*100:.1f}%)')
    print(f'   Flash-Lite: {lite_washed_count}/{total} ({lite_washed_count/total*100:.1f}%)')

    if flash_issue_dist:
        print(f'\n📊 Flash issueType distribution (washed only):')
        for k, v in flash_issue_dist.most_common():
            print(f'   {k}: {v}')

    if lite_issue_dist:
        print(f'\n📊 Flash-Lite issueType distribution (washed only):')
        for k, v in lite_issue_dist.most_common():
            print(f'   {k}: {v}')

    if iad_diffs:
        avg_i = sum(d[0] for d in iad_diffs) / len(iad_diffs)
        avg_a = sum(d[1] for d in iad_diffs) / len(iad_diffs)
        avg_d = sum(d[2] for d in iad_diffs) / len(iad_diffs)
        max_i = max(d[0] for d in iad_diffs)
        max_a = max(d[1] for d in iad_diffs)
        max_d = max(d[2] for d in iad_diffs)
        print(f'\n📊 IAD score difference (Flash vs Lite):')
        print(f'   Average: I={avg_i:.2f}  A={avg_a:.2f}  D={avg_d:.2f}')
        print(f'   Max:     I={max_i}  A={max_a}  D={max_d}')
        print(f'   (0 = identical, >1 = significant divergence)')

# ── Length-stratified breakdown ────────────────────────────────────────

print(f'\n📊 By review length:')
for label, lo, hi in [('short (<20)', 0, 20), ('medium (20-80)', 20, 81), ('long (>80)', 81, 99999)]:
    subset = [r for r in sampled if lo <= len(r['text']) < hi]
    sub_agree = sub_total = 0
    sub_f_washed = sub_l_washed = 0
    for r in subset:
        u = r['username']
        f_val = flash.get(u, {}).get('isWashed')
        l_val = lite.get(u, {}).get('isWashed')
        if f_val is None or l_val is None:
            continue
        sub_total += 1
        if f_val == l_val:
            sub_agree += 1
        if f_val is True:
            sub_f_washed += 1
        if l_val is True:
            sub_l_washed += 1
    if sub_total > 0:
        print(f'   {label:16} agree={sub_agree}/{sub_total} ({sub_agree/sub_total*100:.0f}%)  '
              f'Flash washed={sub_f_washed}/{sub_total} ({sub_f_washed/sub_total*100:.0f}%)  '
              f'Lite washed={sub_l_washed}/{sub_total} ({sub_l_washed/sub_total*100:.0f}%)')

# ── Save raw results ──────────────────────────────────────────────────

output = {
    'sample_size': len(sampled),
    'compared': total,
    'agreement': agree,
    'agreement_pct': round(agree / total * 100, 1) if total else 0,
    'flash_washed': flash_washed_count,
    'lite_washed': lite_washed_count,
    'per_review': [],
}

for r in sampled:
    u = r['username']
    output['per_review'].append({
        'username': u,
        'store': r['store'],
        'text': r['text'],
        'text_length': len(r['text']),
        'flash': flash.get(u, {}),
        'lite': lite.get(u, {}),
    })

with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f'\nSaved: {OUTPUT_PATH}')
