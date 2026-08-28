#!/usr/bin/env python3 -u
# -*- coding: utf-8 -*-
"""
Pre-run AI store summaries for all stores in scrape_cache.

Runs Stage 1 to filter real reviews, then calls the LLM with
summarize_prompt.txt to generate warnings + recommendations.
Results are cached in summary_cache.

Usage:
  python scripts/prerun_summary.py --dry-run
  python scripts/prerun_summary.py
  python scripts/prerun_summary.py --force
  python scripts/prerun_summary.py --limit 10
  python scripts/prerun_summary.py --min-reviews 10
"""
import argparse
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from dotenv import load_dotenv
from google import genai

from cache_store import (
    iter_all_scrape_cache, get_cached_summary, set_cached_summary,
    get_cached_metadata,
)
from rule_engine import run_stage1_audit
from llm_client import call_llm_summary, MODEL_NAME_GEMINI

# Cost estimate: ~7000 input + ~500 output tokens per store
COST_PER_STORE_USD = (7000 * 0.075 + 500 * 0.30) / 1_000_000  # ~$0.000675


def main():
    parser = argparse.ArgumentParser(
        description='Pre-run AI store summaries for all cached stores')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be processed without calling LLM')
    parser.add_argument('--force', action='store_true',
                        help='Re-process all stores (ignore existing summary_cache)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Process at most N stores (0 = all)')
    parser.add_argument('--min-reviews', type=int, default=10,
                        help='Skip stores with fewer than N reviews (default: 10)')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='Seconds to wait between stores (default: 1.0)')
    parser.add_argument('--verbose', action='store_true',
                        help='Show detailed error tracebacks')
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key and not args.dry_run:
        print('❌ GEMINI_API_KEY not set in .env')
        sys.exit(1)

    client = genai.Client(api_key=api_key) if api_key else None

    print('Loading scrape_cache...')
    all_stores = list(iter_all_scrape_cache())
    if args.limit:
        all_stores = all_stores[:args.limit]

    print(f'📋 scrape_cache: {len(all_stores)} stores (min_reviews={args.min_reviews})')

    to_process = 0
    skipped_few = 0
    skipped_cached = 0
    success = 0
    failed = 0
    consecutive_failures = 0
    start = time.time()

    for i, (place_id, reviews) in enumerate(all_stores, 1):
        if len(reviews) < args.min_reviews:
            skipped_few += 1
            continue

        if not args.force:
            cached = get_cached_summary(place_id)
            if cached:
                skipped_cached += 1
                continue

        to_process += 1

        # Run Stage 1 to filter real reviews
        stage1 = run_stage1_audit(reviews)
        real_reviews = [
            r for r in stage1['auditedReviews']
            if not r.get('audit', {}).get('isWashed')
            and (r.get('text') or '').strip()
        ]
        # Sort by text length, cap at 150
        real_reviews.sort(key=lambda x: len(x.get('text', '')), reverse=True)
        real_reviews = real_reviews[:150]

        if not real_reviews:
            skipped_few += 1
            to_process -= 1
            continue

        if args.dry_run:
            if i % 200 == 0 or i <= 3 or i == len(all_stores):
                print(f'  [{i}/{len(all_stores)}] {place_id[:40]}... {len(real_reviews)} real reviews')
            continue

        meta = get_cached_metadata(place_id)
        store_name = (meta or {}).get('title', place_id[:40])

        try:
            result = call_llm_summary('gemini', client, store_name, real_reviews,
                                       max_retries=1)
            set_cached_summary(place_id, result)
            success += 1
            consecutive_failures = 0

            if i % 50 == 0 or i == len(all_stores):
                elapsed = time.time() - start
                cost = success * COST_PER_STORE_USD
                print(f'  [{i}/{len(all_stores)}] success={success} cost~${cost:.2f} ({elapsed:.0f}s)')

        except Exception as e:
            print(f'  ❌ [{i}/{len(all_stores)}] {place_id[:40]}... {e}')
            if args.verbose:
                traceback.print_exc()
            failed += 1
            consecutive_failures += 1
            if consecutive_failures >= 3:
                print(f'\n🛑 連續 {consecutive_failures} 家失敗，停止執行')
                break

        time.sleep(args.delay)

    elapsed = time.time() - start
    est_cost = (success or to_process) * COST_PER_STORE_USD

    print(f'\n{"=" * 60}')
    if args.dry_run:
        print('DRY RUN 完成')
    else:
        print(f'AI 總結預跑完成 ({elapsed:.1f}s)')
    print(f'{"=" * 60}')
    print(f'  店家總數:      {len(all_stores)}')
    print(f'  跳過(評論不足): {skipped_few}')
    print(f'  跳過(已快取):  {skipped_cached}')
    print(f'  需處理:        {to_process}')
    print(f'  成功:          {success}')
    print(f'  失敗:          {failed}')
    print(f'  預估成本:      ${est_cost:.2f} USD (~{est_cost * 32:.0f} TWD)')


if __name__ == '__main__':
    main()
