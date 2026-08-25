#!/usr/bin/env python3 -u
# -*- coding: utf-8 -*-
"""
Pre-run Stage 2 (Gemini semantic audit) for all stores in scrape_cache.

Reads every store from scrape_cache, runs Stage 1 to identify ambiguous
reviews, sends them through Stage 2 LLM analysis, and caches results in
stage2_cache. Subsequent user queries will hit cache instead of the LLM.

Usage:
  # Dry run — show what would be processed, with cost estimate
  python scripts/prerun_stage2.py --dry-run

  # Full run
  python scripts/prerun_stage2.py

  # Force re-process everything (ignore existing stage2_cache)
  python scripts/prerun_stage2.py --force

  # Process at most 10 stores (for testing)
  python scripts/prerun_stage2.py --limit 10
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
    iter_all_scrape_cache, get_cached_stage2, set_cached_stage2_batch,
    _review_hash, get_cached_metadata,
)
from rule_engine import run_stage1_audit
from llm_client import make_batches, call_llm_batch

# Disable thinking tokens to save cost — Stage 2 is structured JSON extraction,
# not deep reasoning. Thinking tokens cost $3.50/1M vs output $0.60/1M.
NO_THINKING = {'thinking_config': {'thinking_budget': 0}}

# Cost constant (Gemini 2.5 Flash: $0.15/1M input + $0.60/1M output tokens)
# ~6200 input + ~3200 output tokens per 40-review batch → ~$0.003/batch → ~$0.0001/review
COST_PER_REVIEW_USD = 0.0001


def enrich_review(review, idx, signals, now):
    """Add signal context fields to a review dict, mirroring Results.tsx logic."""
    spike_months_set = set(signals.get('spikeMonths', []))
    similarity = signals.get('similarity', [])
    hot_term = signals.get('hotTerm', [])
    nearby_long = signals.get('nearbyLongReviewCounts', [])

    month = (review.get('time') or '')[:7]
    is_spike = month in spike_months_set

    days_elapsed = 0
    if review.get('time'):
        try:
            rd = datetime.fromisoformat(review['time'][:10])
            days_elapsed = max(0, (now - rd).days)
        except (ValueError, TypeError):
            pass

    sim = similarity[idx] if idx < len(similarity) else {}
    ht = hot_term[idx] if idx < len(hot_term) else {}
    nlr = nearby_long[idx] if idx < len(nearby_long) else 0

    return {
        'username': review.get('username', ''),
        'text': review.get('text', '') or '',
        'stars': review.get('stars', 5),
        'images': review.get('images', []),
        'daysElapsed': days_elapsed,
        'isSpikePeriod': is_spike,
        'maxSimilarity': sim.get('maxSimilarity', 0),
        'similarCount': sim.get('similarCount', 0),
        'hotTermCount': ht.get('hotTermCount', 0),
        'hotTermMaxRatio': ht.get('hotTermMaxRatio', 0),
        'nearbyLongReviewCount': nlr,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Pre-run Stage 2 Gemini audit for all cached stores')
    parser.add_argument('--test', action='store_true',
                        help='Send 1 review to Gemini to check API health, then exit')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed without calling LLM')
    parser.add_argument('--force', action='store_true',
                        help='Re-process all reviews (ignore existing stage2_cache)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Process at most N stores (0 = all)')
    parser.add_argument('--batch-size', type=int, default=20,
                        help='Reviews per LLM batch (default: 20, live server uses 40)')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='Seconds to wait between stores (default: 1.0)')
    parser.add_argument('--verbose', action='store_true',
                        help='Show detailed error tracebacks')
    args = parser.parse_args()

    # Load env and init Gemini client
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key and not args.dry_run:
        print('❌ GEMINI_API_KEY not set in .env')
        sys.exit(1)

    # attempts=1 = no SDK-level retries. Prevents burning money on 503/504.
    client = genai.Client(
        api_key=api_key,
        http_options={'retry_options': {'attempts': 1}},
    ) if api_key else None

    # --test: send a realistic 20-review batch to check if Gemini can handle it.
    # A 1-review test is meaningless — 504s only happen with full-size prompts.
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
            result = call_llm_batch('gemini', client, 'API測試店家', test_reviews, max_retries=0, gemini_config=NO_THINKING)
            print(f'✅ Gemini API 正常！{batch_size} 則 batch 成功回傳 {len(result)} 筆結果')
            sys.exit(0)
        except Exception as e:
            print(f'❌ Gemini API 失敗: {e}')
            print(f'   Gemini 目前無法處理 {batch_size} 則的 batch，請稍後再試')
            sys.exit(1)

    # Collect all stores
    print('Loading scrape_cache...')
    all_stores = list(iter_all_scrape_cache())
    if args.limit:
        all_stores = all_stores[:args.limit]

    print(f'📋 scrape_cache: {len(all_stores)} stores')

    total_ambiguous = 0
    total_to_send = 0
    total_cached = 0
    success = 0
    failed = 0
    skipped = 0
    consecutive_failures = 0
    start = time.time()
    now = datetime.now()

    for i, (place_id, reviews) in enumerate(all_stores, 1):
        try:
            # Run Stage 1 to get signals + identify ambiguous reviews
            stage1 = run_stage1_audit(reviews)
            audited = stage1['auditedReviews']
            signals = stage1['signals']

            # Find ambiguous 5-star reviews (issueType is None)
            ambiguous_indices = []
            for idx, r in enumerate(audited):
                stars = int(r.get('stars', 0) or 0)
                if stars == 5 and r.get('audit', {}).get('issueType') is None:
                    ambiguous_indices.append(idx)

            total_ambiguous += len(ambiguous_indices)

            if not ambiguous_indices:
                skipped += 1
                continue

            # Check existing stage2_cache
            cached_s2 = {} if args.force else get_cached_stage2(place_id)

            # Build enriched payload, skipping cached reviews
            to_send = []
            cached_count = 0
            for idx in ambiguous_indices:
                r = audited[idx]
                username = r.get('username', '')
                text = r.get('text', '') or ''

                if not args.force and username in cached_s2:
                    if cached_s2[username].get('_review_hash') == _review_hash(text):
                        cached_count += 1
                        continue

                to_send.append(enrich_review(r, idx, signals, now))

            total_cached += cached_count
            total_to_send += len(to_send)

            if not to_send:
                skipped += 1
                if i % 200 == 0:
                    print(f'  [{i}/{len(all_stores)}] {place_id[:40]}... all cached ({cached_count})')
                continue

            if args.dry_run:
                if i % 200 == 0 or i <= 3 or i == len(all_stores):
                    print(f'  [{i}/{len(all_stores)}] {place_id[:40]}... {len(to_send)} to send, {cached_count} cached')
                success += 1
                continue

            # Get store name from metadata if available
            meta = get_cached_metadata(place_id)
            store_name = (meta or {}).get('title', place_id[:40])

            # Send to Gemini in batches — NO retries (max_retries=0) to avoid
            # burning money on 503/504 errors. Failed batches are skipped.
            # Each successful batch is saved to cache IMMEDIATELY so Ctrl+C
            # doesn't lose completed work.
            batches = make_batches(to_send, target_size=args.batch_size, max_size=args.batch_size + 10)
            text_by_username = {r['username']: r.get('text', '') for r in to_send}
            batch_failures = 0
            batch_saved = 0
            for bi, batch in enumerate(batches):
                try:
                    batch_results = call_llm_batch('gemini', client, store_name, batch, max_retries=0, gemini_config=NO_THINKING)
                    # Save immediately
                    cache_entries = [
                        {**r, '_original_text': text_by_username.get(r.get('username', ''), '')}
                        for r in batch_results
                    ]
                    set_cached_stage2_batch(place_id, cache_entries)
                    batch_saved += len(batch_results)
                except Exception as e:
                    print(f'  ⚠️  Batch {bi+1}/{len(batches)} failed for {place_id[:40]}: {e}')
                    batch_failures += 1
                    if args.verbose:
                        traceback.print_exc()
                if bi < len(batches) - 1:
                    time.sleep(args.delay)

            # If ALL batches failed, count as store failure for fail-fast
            if batch_failures == len(batches):
                failed += 1
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

            success += 1
            consecutive_failures = 0

            # Pause between stores to respect rate limits
            time.sleep(args.delay)

        except Exception as e:
            print(f'  ❌ [{i}/{len(all_stores)}] {place_id[:40]}... {e}')
            if args.verbose:
                traceback.print_exc()
            failed += 1
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print(f'\n🛑 連續 {consecutive_failures} 家失敗，停止執行（Gemini 可能不穩定）')
                break

    elapsed = time.time() - start
    est_cost = total_to_send * COST_PER_REVIEW_USD

    print(f'\n{"=" * 60}')
    if args.dry_run:
        print('DRY RUN 完成')
    else:
        print(f'Stage 2 預跑完成 ({elapsed:.1f}s)')
    print(f'{"=" * 60}')
    print(f'  店家總數:    {len(all_stores)}')
    print(f'  有 ambiguous: {success + failed} (跳過 {skipped} 家無 ambiguous)')
    print(f'  ambiguous 總數: {total_ambiguous}')
    print(f'  已快取:      {total_cached}')
    print(f'  需送 LLM:    {total_to_send}')
    print(f'  成功:        {success}')
    print(f'  失敗:        {failed}')
    print(f'  預估成本:    ${est_cost:.2f} USD (~{est_cost * 32:.0f} TWD)')


if __name__ == '__main__':
    main()
