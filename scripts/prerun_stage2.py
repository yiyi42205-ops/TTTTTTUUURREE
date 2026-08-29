#!/usr/bin/env python3 -u
# -*- coding: utf-8 -*-
"""
Pre-run Stage 2 (Gemini semantic audit) for all stores in scrape_cache.

Reads every store from scrape_cache, runs Stage 1 to identify ambiguous
reviews, sends them through Stage 2 LLM analysis, and caches I/A/D scores
in the stage2_scores table. Subsequent user queries will hit cache instead
of the LLM.

Usage:
  # Dry run — show what would be processed, with cost estimate
  python scripts/prerun_stage2.py --dry-run

  # Full run
  python scripts/prerun_stage2.py

  # Force re-process everything (ignore existing stage2_scores cache)
  python scripts/prerun_stage2.py --force

  # Process at most 10 stores (for testing)
  python scripts/prerun_stage2.py --limit 10

  # Test Gemini API health with a 20-review batch
  python scripts/prerun_stage2.py --test
"""
import argparse
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Add review_scraper/ to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from dotenv import load_dotenv
from google import genai

from cache_store import (
    iter_all_scrape_cache, get_cached_scores, set_cached_scores,
    get_cached_metadata,
)
from rule_engine import run_stage1_audit
from llm_client import make_batches, call_llm_batch, MODEL_NAME_GEMINI
from prompt_builder import get_prompt_version

# Cost constant (Gemini 2.5 Flash Lite: $0.075/1M input + $0.30/1M output tokens)
# ~6200 input + ~3200 output tokens per 40-review batch → ~$0.0014/batch → ~$0.00004/review
COST_PER_REVIEW_USD = 0.00004


def main():
    parser = argparse.ArgumentParser(
        description='Pre-run Stage 2 Gemini audit for all cached stores')
    parser.add_argument('--test', action='store_true',
                        help='Send 1 batch to Gemini to check API health, then exit')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed without calling LLM')
    parser.add_argument('--force', action='store_true',
                        help='Re-process all reviews (ignore existing stage2_scores)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Process at most N stores (0 = all)')
    parser.add_argument('--min-reviews', type=int, default=10,
                        help='Skip stores with fewer than N reviews (default: 10)')
    parser.add_argument('--batch-size', type=int, default=20,
                        help='Reviews per LLM batch (default: 20)')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='Seconds to wait between batches (default: 1.0)')
    parser.add_argument('--verbose', action='store_true',
                        help='Show detailed error tracebacks')
    args = parser.parse_args()

    # Load env and init Gemini client
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key and not args.dry_run:
        print('❌ GEMINI_API_KEY not set in .env')
        sys.exit(1)

    client = genai.Client(api_key=api_key) if api_key else None
    model_name = MODEL_NAME_GEMINI
    prompt_version = get_prompt_version()

    # --test: send a realistic batch to check if Gemini can handle it.
    if args.test:
        batch_size = args.batch_size
        print(f'🔍 Testing Gemini API with {batch_size}-review batch...')
        test_reviews = [
            {
                'username': f'user_{i}', 'stars': 5, 'images': [],
                'text': f'第{i}次來，餐點品質穩定，服務態度也很好，環境乾淨整潔，會再回訪。',
                'daysElapsed': i * 10, 'isSpikePeriod': False,
                'maxSimilarity': 0, 'similarCount': 0,
                'hotTermCount': 0, 'hotTermMaxRatio': 0, 'nearbyLongReviewCount': 0,
            }
            for i in range(batch_size)
        ]
        try:
            result = call_llm_batch('gemini', client, 'API測試店家', test_reviews, max_retries=0)
            print(f'✅ Gemini API 正常！{batch_size} 則 batch 成功回傳 {len(result)} 筆結果')
            sys.exit(0)
        except Exception as e:
            print(f'❌ Gemini API 失敗: {e}')
            sys.exit(1)

    # Collect all stores
    print('Loading scrape_cache...')
    all_stores_raw = list(iter_all_scrape_cache())
    all_stores = [(pid, revs) for pid, revs in all_stores_raw
                   if len(revs) >= args.min_reviews]
    skipped_few = len(all_stores_raw) - len(all_stores)
    if args.limit:
        all_stores = all_stores[:args.limit]

    print(f'📋 scrape_cache: {len(all_stores)} stores (skipped {skipped_few} with < {args.min_reviews} reviews)')
    print(f'📝 model: {model_name}, prompt_version: {prompt_version}')

    total_ambiguous = 0
    total_to_send = 0
    total_cached = 0
    stores_with_ambiguous = 0
    stores_processed = 0
    stores_failed = 0
    stores_skipped = 0
    consecutive_failures = 0
    start = time.time()
    now = datetime.now()

    for i, (place_id, reviews) in enumerate(all_stores, 1):
        try:
            # Run Stage 1 to identify ambiguous reviews
            stage1 = run_stage1_audit(reviews)
            audited = stage1['auditedReviews']
            signals = stage1['signals']

            # Find ambiguous 5-star reviews (issueType is None → sent to Stage 2)
            ambiguous = []
            for idx, r in enumerate(audited):
                stars = int(r.get('stars', 0) or 0)
                if stars == 5 and r.get('audit', {}).get('issueType') is None:
                    ambiguous.append((idx, r))

            total_ambiguous += len(ambiguous)

            if not ambiguous:
                stores_skipped += 1
                continue

            stores_with_ambiguous += 1

            # Build review_ids and check cache
            review_ids = [f"{place_id}:{r.get('username', '')}" for _, r in ambiguous]

            if args.force:
                cached = {}
            else:
                cached = get_cached_scores(review_ids, model_name, prompt_version)

            # Filter out already-cached reviews
            to_send_items = []
            for (idx, r), rid in zip(ambiguous, review_ids):
                if rid in cached:
                    total_cached += 1
                    continue
                # Enrich with signal context (mirrors server.py's /api/audit payload)
                spike_months_set = set(signals.get('spikeMonths', []))
                month = (r.get('time') or '')[:7]
                days_elapsed = 0
                if r.get('time'):
                    try:
                        rd = datetime.fromisoformat(r['time'][:10])
                        days_elapsed = max(0, (now - rd).days)
                    except (ValueError, TypeError):
                        pass

                to_send_items.append({
                    'username': r.get('username', ''),
                    'text': r.get('text', '') or '',
                    'stars': r.get('stars', 5),
                    'daysElapsed': days_elapsed,
                    'isSpikePeriod': month in spike_months_set,
                    '_review_id': rid,
                })

            total_to_send += len(to_send_items)

            if not to_send_items:
                stores_skipped += 1
                if i % 200 == 0:
                    print(f'  [{i}/{len(all_stores)}] {place_id[:40]}... all cached')
                continue

            if args.dry_run:
                if i % 200 == 0 or i <= 3 or i == len(all_stores):
                    print(f'  [{i}/{len(all_stores)}] {place_id[:40]}... {len(to_send_items)} to send')
                stores_processed += 1
                continue

            # Get store name
            meta = get_cached_metadata(place_id)
            store_name = (meta or {}).get('title', place_id[:40])

            # Send to Gemini in batches, save each batch immediately
            batches = make_batches(to_send_items, target_size=args.batch_size,
                                   max_size=args.batch_size + 10)
            batch_failures = 0
            batch_saved = 0

            for bi, batch in enumerate(batches):
                try:
                    batch_results = call_llm_batch('gemini', client, store_name, batch,
                                                    max_retries=0)
                    # Map LLM results back to review_ids and save to stage2_scores
                    to_cache = []
                    for item in batch_results:
                        local_id = item['id']
                        if local_id < len(batch):
                            review_id = batch[local_id].get('_review_id', '')
                            to_cache.append({
                                'review_id': review_id,
                                'I': item['incentiveIntensity'],
                                'A': item['sentimentAuthenticity'],
                                'D': item['descriptionGranularity'],
                                'reasoning': item.get('reasoning', ''),
                            })
                    if to_cache:
                        set_cached_scores(to_cache, model_name, prompt_version)
                        batch_saved += len(to_cache)
                except Exception as e:
                    print(f'  ⚠️  Batch {bi+1}/{len(batches)} failed for {place_id[:40]}: {e}')
                    batch_failures += 1
                    if args.verbose:
                        traceback.print_exc()

                if bi < len(batches) - 1:
                    time.sleep(args.delay)

            # If ALL batches failed, count as store failure for fail-fast
            if batch_failures == len(batches):
                stores_failed += 1
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    print(f'\n🛑 連續 {consecutive_failures} 家全部 batch 失敗，停止執行')
                    break
                continue

            if i % 50 == 0 or i == len(all_stores):
                elapsed = time.time() - start
                cost_so_far = total_to_send * COST_PER_REVIEW_USD
                print(f'  [{i}/{len(all_stores)}] sent={total_to_send} cached={total_cached} '
                      f'cost~${cost_so_far:.2f} ({elapsed:.0f}s)')

            stores_processed += 1
            consecutive_failures = 0
            time.sleep(args.delay)

        except Exception as e:
            print(f'  ❌ [{i}/{len(all_stores)}] {place_id[:40]}... {e}')
            if args.verbose:
                traceback.print_exc()
            stores_failed += 1
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print(f'\n🛑 連續 {consecutive_failures} 家失敗，停止執行（Gemini 可能不穩定）')
                break

    elapsed = time.time() - start
    est_cost = total_to_send * COST_PER_REVIEW_USD
    stores_iterated = stores_with_ambiguous + stores_skipped + stores_failed
    aborted = stores_iterated < len(all_stores)

    print(f'\n{"=" * 60}')
    if args.dry_run:
        print('DRY RUN 完成')
    elif aborted:
        print(f'Stage 2 預跑中斷 ({elapsed:.1f}s)')
    else:
        print(f'Stage 2 預跑完成 ({elapsed:.1f}s)')
    print(f'{"=" * 60}')
    print(f'  店家總數:      {len(all_stores)}')
    print(f'  已遍歷:        {stores_iterated}/{len(all_stores)}')
    if aborted:
        print(f'  ⚠️  未遍歷:     {len(all_stores) - stores_iterated}')
    print(f'  有 ambiguous:  {stores_with_ambiguous}')
    print(f'  跳過(無 ambiguous): {stores_skipped}')
    print(f'  ambiguous 總數: {total_ambiguous} (僅已遍歷的店家)')
    print(f'  已快取:        {total_cached}')
    print(f'  需送 LLM:      {total_to_send}')
    print(f'  成功:          {stores_processed}')
    print(f'  失敗:          {stores_failed}')
    print(f'  預估成本:      ${est_cost:.2f} USD (~{est_cost * 32:.0f} TWD)')


if __name__ == '__main__':
    main()
