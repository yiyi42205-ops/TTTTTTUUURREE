#!/usr/bin/env python3 -u
"""
Randomly sample 200 ambiguous 5-star reviews from scrape_cache,
stratified by review length (short/medium/long), from diverse stores.

Outputs:
  eval/ambiguous_sample_200.json  — sampled reviews with store context
  eval/ambiguous_sample_200_gpt_prompt.txt — ready-to-paste GPT prompt

Usage:
  review_scraper/venv/bin/python scripts/sample_ambiguous_200.py
"""
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from cache_store import iter_all_scrape_cache, get_cached_metadata
from rule_engine import run_stage1_audit

SEED = 42
SAMPLE_SIZE = 200
random.seed(SEED)
now = datetime.now()

# ── Phase 1: collect all ambiguous 5-star reviews ──────────────────────

print('Scanning scrape_cache for ambiguous 5-star reviews...')
# Buckets by text length: short (<20 chars), medium (20-80), long (>80)
buckets = {'short': [], 'medium': [], 'long': []}
store_count = 0
total_ambiguous = 0

for place_id, reviews in iter_all_scrape_cache():
    store_count += 1
    if store_count % 200 == 0:
        print(f'  {store_count} stores scanned, {total_ambiguous} ambiguous so far...')

    if not reviews or len(reviews) < 3:
        continue

    stage1 = run_stage1_audit(reviews)
    audited = stage1['auditedReviews']
    signals = stage1['signals']
    spike_months_set = set(signals.get('spikeMonths', []))
    similarity = signals.get('similarity', [])
    hot_term = signals.get('hotTerm', [])
    nearby_long = signals.get('nearbyLongReviewCounts', [])

    meta = get_cached_metadata(place_id)
    store_name = (meta or {}).get('title', place_id[:40])

    for idx, r in enumerate(audited):
        audit = r.get('audit', {})
        stars = r.get('stars', 0)
        text = r.get('text', '') or ''

        # Only ambiguous 5-star reviews (issueType is None)
        if stars != 5 or audit.get('issueType') is not None:
            continue

        total_ambiguous += 1

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

        entry = {
            'place_id': place_id,
            'store': store_name,
            'username': r.get('username', ''),
            'text': text,
            'stars': stars,
            'time': r.get('time', ''),
            'daysElapsed': days_elapsed,
            'isSpikePeriod': month in spike_months_set,
            'maxSimilarity': sim.get('maxSimilarity', 0),
            'similarCount': sim.get('similarCount', 0),
            'hotTermCount': ht.get('hotTermCount', 0),
            'hotTermMaxRatio': ht.get('hotTermMaxRatio', 0),
            'nearbyLongReviewCount': nlr,
        }

        text_len = len(text)
        if text_len < 20:
            buckets['short'].append(entry)
        elif text_len <= 80:
            buckets['medium'].append(entry)
        else:
            buckets['long'].append(entry)

print(f'\nDone: {store_count} stores, {total_ambiguous} ambiguous 5-star reviews')
for k, v in buckets.items():
    print(f'  {k}: {len(v)}')

# ── Phase 2: stratified sampling ───────────────────────────────────────

# Aim for roughly equal buckets, but adjust if one is too small
target_per_bucket = SAMPLE_SIZE // 3  # ~67 each
sampled = []

for bucket_name in ['short', 'medium', 'long']:
    pool = buckets[bucket_name]
    random.shuffle(pool)

    # Diversify stores: pick at most 3 reviews per store
    by_store = {}
    for entry in pool:
        sid = entry['place_id']
        by_store.setdefault(sid, []).append(entry)

    picked = []
    for sid, entries in by_store.items():
        picked.extend(entries[:3])

    random.shuffle(picked)
    n = min(target_per_bucket, len(picked))
    sampled.extend(picked[:n])

# If we didn't reach 200 (unlikely), fill from largest bucket
if len(sampled) < SAMPLE_SIZE:
    all_remaining = []
    sampled_ids = {(s['place_id'], s['username']) for s in sampled}
    for bucket_name in ['long', 'medium', 'short']:
        for entry in buckets[bucket_name]:
            key = (entry['place_id'], entry['username'])
            if key not in sampled_ids:
                all_remaining.append(entry)
    random.shuffle(all_remaining)
    sampled.extend(all_remaining[:SAMPLE_SIZE - len(sampled)])

sampled = sampled[:SAMPLE_SIZE]
random.shuffle(sampled)

print(f'\nSampled {len(sampled)} reviews:')
lens = {'short': 0, 'medium': 0, 'long': 0}
stores_in_sample = set()
for s in sampled:
    stores_in_sample.add(s['place_id'])
    tl = len(s['text'])
    if tl < 20:
        lens['short'] += 1
    elif tl <= 80:
        lens['medium'] += 1
    else:
        lens['long'] += 1
print(f'  short: {lens["short"]}, medium: {lens["medium"]}, long: {lens["long"]}')
print(f'  from {len(stores_in_sample)} unique stores')

# ── Phase 3: save outputs ─────────────────────────────────────────────

eval_dir = Path(__file__).resolve().parent.parent / 'eval'
eval_dir.mkdir(exist_ok=True)

# JSON output
json_path = eval_dir / 'ambiguous_sample_200.json'
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(sampled, f, ensure_ascii=False, indent=2)
print(f'\nSaved: {json_path}')

# GPT prompt output — one prompt per batch of ~40 reviews (same as Gemini batching)
BATCH_SIZE = 40
prompt_path = eval_dir / 'ambiguous_sample_200_gpt_prompt.txt'
with open(prompt_path, 'w', encoding='utf-8') as f:
    for batch_idx in range(0, len(sampled), BATCH_SIZE):
        batch = sampled[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1
        total_batches = (len(sampled) + BATCH_SIZE - 1) // BATCH_SIZE

        f.write(f'{"="*80}\n')
        f.write(f'BATCH {batch_num}/{total_batches} ({len(batch)} reviews)\n')
        f.write(f'{"="*80}\n\n')

        # Build a simplified prompt for GPT
        reviews_for_prompt = []
        for i, s in enumerate(batch):
            reviews_for_prompt.append({
                'index': i,
                'username': s['username'],
                'text': s['text'],
                'stars': s['stars'],
                'store': s['store'],
                'daysElapsed': s['daysElapsed'],
                'isSpikePeriod': s['isSpikePeriod'],
                'maxSimilarity': s['maxSimilarity'],
                'similarCount': s['similarCount'],
                'hotTermCount': s['hotTermCount'],
                'hotTermMaxRatio': s['hotTermMaxRatio'],
                'nearbyLongReviewCount': s['nearbyLongReviewCount'],
            })

        f.write("""你是 Google Maps 餐廳評論的洗評審計專家。台灣的餐廳常用「打卡送小菜」「五星好評送飲料」等方式，\
徵求非體驗導向的灌水評論來拉高評分。

請逐一分析以下評論，對每則評論回傳：
{
  "username": "...",
  "isWashed": true/false,
  "issueType": "incentive" | "template" | "discrepancy" | null,
  "verdictBasis": "content" | "structural",
  "incentiveIntensity": 1-5,
  "sentimentAuthenticity": 1-5,
  "descriptionGranularity": 1-5,
  "reason": "一句話說明判斷依據"
}

判斷標準：
- incentive：評論提及打卡/送/優惠/活動/免費等利益交換
- template：內容空洞/套用模板/與其他評論高度相似
- discrepancy：描述與星級不符
- null（clean）：具體描述消費體驗，情感自然

信號欄位說明：
- isSpikePeriod: 該月評論量異常暴增
- maxSimilarity/similarCount: 與同店其他評論的文字相似度
- hotTermCount/hotTermMaxRatio: 同店多人使用的相同詞彙
- nearbyLongReviewCount: 時間相近的長篇評論數量

請直接回傳 JSON array，不要加 markdown 格式。

""")
        f.write(json.dumps(reviews_for_prompt, ensure_ascii=False, indent=2))
        f.write('\n\n')

print(f'Saved: {prompt_path}')
print('\nDone! Next steps:')
print('  1. Send to Flash-Lite: scripts/compare_flash_lite.py (adapt to use sampled data)')
print('  2. Paste GPT prompt batches into ChatGPT')
print('  3. Compare results across three models')
