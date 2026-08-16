#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批次審計腳本 (Issue #16)

讀取 scrape_cache 中所有已爬取的評論，跑 Stage 1 規則引擎審計，
結果寫入 audit_cache。之後使用者查詢時可直接 cache hit。

用法:
  # 試跑（不實際寫入）
  python review_scraper/batch_audit.py --dry-run

  # 完整批次審計
  python review_scraper/batch_audit.py

  # 強制重跑（忽略已有的審計 cache）
  python review_scraper/batch_audit.py --force
"""
import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cache_store import iter_all_scrape_cache, get_pending_audit_entries, set_cached_audit
from rule_engine import run_stage1_audit


def main():
    parser = argparse.ArgumentParser(
        description='批次跑 Stage 1 審計，結果寫入 audit_cache')
    parser.add_argument('--dry-run', action='store_true',
                        help='只統計，不實際審計')
    parser.add_argument('--force', action='store_true',
                        help='忽略已有的審計 cache，全部重跑')
    parser.add_argument('--verbose', action='store_true',
                        help='顯示詳細錯誤 traceback')
    args = parser.parse_args()

    if args.force:
        # --force: re-audit everything
        to_audit = list(iter_all_scrape_cache())
        total = len(to_audit)
        skipped = 0
    else:
        # Normal mode: only audit entries without existing audit cache (SQL-level filtering)
        to_audit = list(get_pending_audit_entries())
        # Count total for reporting
        total_entries = sum(1 for _ in iter_all_scrape_cache())
        skipped = total_entries - len(to_audit)
        total = total_entries

    print(f'📋 scrape_cache 共 {total} 筆')
    print(f'🎯 需要審計: {len(to_audit)} 筆（跳過 {skipped} 筆已有 cache）')

    if args.dry_run:
        print('\n(dry-run 模式，不實際審計)')
        return

    success = 0
    failed = 0
    start = time.time()

    for i, (place_id, reviews) in enumerate(to_audit, 1):
        try:
            result = run_stage1_audit(reviews)
            set_cached_audit(place_id, result)
            washed = sum(1 for r in result['auditedReviews'] if r['audit']['isWashed'])
            audit_total = len(result['auditedReviews'])
            if i % 100 == 0 or i == len(to_audit):
                print(f'  [{i}/{len(to_audit)}] {place_id[:60]}... → {washed}/{audit_total} washed')
            success += 1
        except Exception as e:
            print(f'  ❌ [{i}/{len(to_audit)}] {place_id[:60]}... → {e}')
            if args.verbose:
                traceback.print_exc()
            failed += 1

    elapsed = time.time() - start
    print(f'\n{"=" * 60}')
    print(f'批次審計完成 ({elapsed:.1f}s)')
    print(f'{"=" * 60}')
    print(f'  成功: {success}')
    print(f'  失敗: {failed}')
    print(f'  跳過: {skipped}')
    print(f'  總計: {total}')


if __name__ == '__main__':
    main()
