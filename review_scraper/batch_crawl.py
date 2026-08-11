#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 Playwright 批次預爬腳本 (Issue #15)

用免費的本地 Playwright 預爬台大附近店家評論，寫入 SQLite cache，
之後使用者即時查詢直接 cache hit，不燒 Apify 額度。

用法:
  # 試跑（不實際爬）
  python review_scraper/batch_crawl.py --dry-run

  # 爬前 3 家測試
  python review_scraper/batch_crawl.py --limit 3

  # 完整批次
  python review_scraper/batch_crawl.py

  # 中斷後續爬
  python review_scraper/batch_crawl.py --resume

  # 強制重爬（忽略 cache TTL）
  python review_scraper/batch_crawl.py --force-recrawl
"""
import argparse
import json
import os
import random
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Ensure review_scraper/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scraper import scrape_google_maps_reviews
from normalize import normalize_review
from cache_store import get_cached_reviews, set_cached_reviews

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STORES_FILE = SCRIPT_DIR / 'stores.json'
DEFAULT_CHECKPOINT_FILE = SCRIPT_DIR / 'batch_crawl_checkpoint.json'

# Circuit breaker defaults
CIRCUIT_BREAKER_THRESHOLD = 5       # consecutive failures before cooldown
CIRCUIT_BREAKER_COOLDOWN = 300      # 5 minutes
CIRCUIT_BREAKER_MAX_COOLDOWNS = 3   # abort after this many cooldowns


# ─── URL resolution ──────────────────────────────────────────

def resolve_short_url(url: str) -> str:
    """Follow redirects for maps.app.goo.gl and share.google short URLs."""
    parsed = urlparse(url)
    if parsed.hostname not in ('maps.app.goo.gl', 'share.google'):
        return url
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36"},
            method="HEAD",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            final_url = response.geturl()
            if final_url != url:
                print(f'  🔗 {parsed.hostname} → {final_url[:80]}...')
            return final_url
    except Exception as e:
        print(f'  ⚠️  無法解析短網址 {url}: {e}')
        return url


# ─── Checkpoint ───────────────────────────────────────────────

def load_checkpoint(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {'completed': {}}


def save_checkpoint(path: Path, checkpoint: dict):
    """Atomic write: write to temp file then replace."""
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, suffix='.tmp', prefix='checkpoint_')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── Store list ───────────────────────────────────────────────

def load_stores(path: Path) -> list:
    data = json.loads(path.read_text(encoding='utf-8'))
    stores = []
    for i, entry in enumerate(data):
        url = entry.get('url')
        if not url:
            print(f'⚠️  stores[{i}] 缺少 url，跳過')
            continue
        stores.append({
            'name': entry.get('name', f'store_{i}'),
            'url': url.strip(),
        })
    return stores


# ─── CSV output (optional) ────────────────────────────────────

def write_csv(reviews: list, store_name: str, out_dir: Path):
    """Write normalized reviews to CSV for eval compatibility."""
    import csv
    path = out_dir / f'{store_name}.csv'
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ['Username', 'Stars', 'Time', 'RawTime', 'Text', 'Images']
    rows = []
    for r in reviews:
        rows.append({
            'Username': r.get('username', ''),
            'Stars': r.get('stars', 5),
            'Time': r.get('time', ''),
            'RawTime': r.get('time', ''),
            'Text': r.get('text', ''),
            'Images': r.get('imageCount', 0),
        })
    rows.sort(key=lambda x: x['Time'], reverse=True)

    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ─── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='本地 Playwright 批次預爬 Google Maps 評論 → SQLite cache')
    parser.add_argument('--stores', type=Path, default=DEFAULT_STORES_FILE,
                        help=f'店家清單 JSON (預設 {DEFAULT_STORES_FILE.name})')
    parser.add_argument('--max-reviews', type=int, default=200,
                        help='每家店最多爬幾則 (預設 200)')
    parser.add_argument('--delay-min', type=float, default=15,
                        help='店與店之間最短間隔秒數 (預設 15)')
    parser.add_argument('--delay-max', type=float, default=45,
                        help='店與店之間最長間隔秒數 (預設 45)')
    parser.add_argument('--max-retries', type=int, default=3,
                        help='每家店失敗重試次數 (預設 3)')
    parser.add_argument('--resume', action='store_true',
                        help='從 checkpoint 續爬（跳過已成功的）')
    parser.add_argument('--fresh', action='store_true',
                        help='忽略 checkpoint 從頭開始')
    parser.add_argument('--force-recrawl', action='store_true',
                        help='忽略 cache TTL 強制重爬')
    parser.add_argument('--dry-run', action='store_true',
                        help='只列出要爬的店，不實際爬')
    parser.add_argument('--csv-out', type=Path, default=None,
                        help='同時輸出 CSV 到指定目錄')
    parser.add_argument('--checkpoint', type=Path,
                        default=DEFAULT_CHECKPOINT_FILE,
                        help='checkpoint 檔案路徑')
    parser.add_argument('--limit', type=int, default=None,
                        help='只處理前 N 家（測試用）')
    args = parser.parse_args()

    # Load stores
    if not args.stores.exists():
        print(f'❌ 找不到店家清單: {args.stores}')
        sys.exit(1)
    stores = load_stores(args.stores)
    if args.limit:
        stores = stores[:args.limit]

    # Load checkpoint
    if args.fresh:
        checkpoint = {'completed': {}}
    else:
        checkpoint = load_checkpoint(args.checkpoint)

    print(f'📋 共 {len(stores)} 家店，每家最多 {args.max_reviews} 則')
    print(f'⏱️  間隔 {args.delay_min}-{args.delay_max}s，重試 {args.max_retries} 次')
    if args.resume:
        done = sum(1 for v in checkpoint['completed'].values() if v['status'] == 'ok')
        print(f'🔄 續爬模式：已完成 {done} 家')
    print()

    # Determine which stores to scrape
    to_scrape = []
    for store in stores:
        url = store['url']
        name = store['name']
        cp = checkpoint['completed'].get(url)

        if args.resume and cp and cp['status'] == 'ok':
            print(f'  ⏭️  {name} — checkpoint 已完成，跳過')
            continue

        if not args.force_recrawl:
            resolved = resolve_short_url(url)
            cached = get_cached_reviews(resolved)
            if cached is not None:
                print(f'  ⏭️  {name} — cache 仍新鮮 ({len(cached)} 則)，跳過')
                continue

        to_scrape.append(store)

    print(f'\n🎯 需要爬取: {len(to_scrape)} 家\n')

    if args.dry_run:
        for i, s in enumerate(to_scrape, 1):
            print(f'  {i}. {s["name"]} — {s["url"]}')
        print('\n(dry-run 模式，不實際爬取)')
        return

    # Scrape loop
    success = 0
    failed = 0
    skipped = len(stores) - len(to_scrape)
    consecutive_failures = 0
    cooldown_count = 0

    for i, store in enumerate(to_scrape, 1):
        url = store['url']
        name = store['name']
        print(f'[{i}/{len(to_scrape)}] {name}')

        # Resolve short URL
        resolved_url = resolve_short_url(url)

        # Retry loop with exponential backoff
        scraped = False
        last_error = None
        for attempt in range(args.max_retries):
            try:
                df = scrape_google_maps_reviews(resolved_url, max_reviews=args.max_reviews)
                raw_reviews = df.to_dict(orient='records')
                reviews = [normalize_review(r) for r in raw_reviews]

                # Write to cache (use resolved URL as key for consistency with server.py)
                set_cached_reviews(resolved_url, reviews, source='playwright_batch')

                # Optional CSV output
                if args.csv_out:
                    write_csv(reviews, name, args.csv_out)

                # Update checkpoint
                checkpoint['completed'][url] = {
                    'status': 'ok',
                    'review_count': len(reviews),
                    'resolved_url': resolved_url,
                    'scraped_at': datetime.now().isoformat(),
                }
                save_checkpoint(args.checkpoint, checkpoint)

                print(f'  ✅ {len(reviews)} 則評論已寫入 cache')
                success += 1
                consecutive_failures = 0
                scraped = True
                break

            except Exception as e:
                last_error = str(e)
                if attempt < args.max_retries - 1:
                    wait = 30 * (2 ** attempt) + random.uniform(0, 5)
                    print(f'  ⚠️  第 {attempt + 1} 次失敗: {last_error}')
                    print(f'      {wait:.0f}s 後重試...')
                    time.sleep(wait)

        if not scraped:
            print(f'  ❌ 全部 {args.max_retries} 次重試失敗: {last_error}')
            checkpoint['completed'][url] = {
                'status': 'failed',
                'error': last_error,
                'scraped_at': datetime.now().isoformat(),
            }
            save_checkpoint(args.checkpoint, checkpoint)
            failed += 1
            consecutive_failures += 1

            # Circuit breaker
            if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                cooldown_count += 1
                if cooldown_count >= CIRCUIT_BREAKER_MAX_COOLDOWNS:
                    print(f'\n🛑 連續 {consecutive_failures} 家失敗，'
                          f'已達熔斷上限 ({CIRCUIT_BREAKER_MAX_COOLDOWNS} 次)，終止執行。')
                    print('   可能被 Google 限速，建議稍後用 --resume 續爬。')
                    break
                print(f'\n⚡ 連續 {consecutive_failures} 家失敗，'
                      f'冷卻 {CIRCUIT_BREAKER_COOLDOWN}s...')
                time.sleep(CIRCUIT_BREAKER_COOLDOWN)
                consecutive_failures = 0

        # Delay before next store
        if i < len(to_scrape):
            delay = random.uniform(args.delay_min, args.delay_max)
            print(f'  💤 等待 {delay:.0f}s...')
            time.sleep(delay)

    # Summary
    print('\n' + '=' * 60)
    print('批次預爬完成')
    print('=' * 60)
    print(f'  成功: {success}')
    print(f'  失敗: {failed}')
    print(f'  跳過: {skipped}')
    print(f'  總計: {len(stores)}')
    if failed > 0:
        print(f'\n  用 --resume 可重試失敗的店家')
    print(f'  checkpoint: {args.checkpoint}')


if __name__ == '__main__':
    main()
