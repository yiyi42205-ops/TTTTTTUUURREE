#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 Apify Google Maps Scraper 搜尋台大附近的餐飲店家，產出 stores.json。

只搜地點清單，不爬評論（maxReviews=0），Apify 用量極小。

用法:
  # 用 .env 裡的 APIFY_TOKEN
  python review_scraper/discover_stores.py

  # 自訂搜尋關鍵字
  python review_scraper/discover_stores.py --queries "台大附近餐廳" "公館飲料店" "大安區咖啡廳"

  # 合併到現有 stores.json（保留原本的店）
  python review_scraper/discover_stores.py --merge

  # 調整最少評論數門檻
  python review_scraper/discover_stores.py --min-reviews 20

產出格式與 stores.json 相容，可直接用於 batch_crawl.py。
"""
import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / '.env'
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _, _val = _line.partition('=')
                os.environ.setdefault(_key.strip(), _val.strip())

SCRIPT_DIR = Path(__file__).resolve().parent

# Default search queries — multiple angles to maximize coverage
DEFAULT_QUERIES = [
    '台大附近餐廳',
    '公館美食',
    '公館飲料店',
    '台大附近咖啡廳',
    '大安區小吃',
    '溫州街餐廳',
    '羅斯福路美食',
    '新生南路餐廳',
    '師大夜市美食',
    '景美美食',
]


def search_places_via_apify(token: str, query: str, max_places: int = 40) -> list:
    """Use Apify Google Maps Scraper to search for places (no reviews)."""
    try:
        from apify_client import ApifyClient
    except ImportError:
        print('❌ apify-client 未安裝，請執行: pip install apify-client')
        sys.exit(1)

    client = ApifyClient(token)
    run = client.actor('compass/Google-Maps-Reviews-Scraper').call(
        run_input={
            'searchStringsArray': [query],
            'maxReviews': 0,          # only search, don't scrape reviews
            'maxPlacesPerQuery': max_places,
            'language': 'zh-TW',
            'countryCode': 'tw',
        },
        timeout=timedelta(seconds=120),
    )

    if not run or run.status != 'SUCCEEDED':
        raise RuntimeError(f'Apify run failed: {run.status if run else "no response"}')

    dataset_id = run.default_dataset_id
    if not dataset_id:
        raise RuntimeError('No dataset ID returned')

    return list(client.dataset(dataset_id).iterate_items())


def main():
    parser = argparse.ArgumentParser(
        description='用 Apify 搜尋台大附近餐飲店家，產出 stores.json')
    parser.add_argument('--queries', nargs='+', default=DEFAULT_QUERIES,
                        help='搜尋關鍵字（可多個）')
    parser.add_argument('--max-per-query', type=int, default=40,
                        help='每個關鍵字最多回傳幾家 (預設 40)')
    parser.add_argument('-o', '--output', type=Path,
                        default=SCRIPT_DIR / 'stores.json',
                        help='輸出檔案路徑 (預設 review_scraper/stores.json)')
    parser.add_argument('--merge', action='store_true',
                        help='合併到現有 stores.json（不覆蓋已有的店）')
    parser.add_argument('--min-reviews', type=int, default=10,
                        help='最少評論數門檻 (預設 10)')
    args = parser.parse_args()

    token = os.environ.get('APIFY_TOKEN')
    if not token:
        print('❌ 請設定 APIFY_TOKEN 環境變數（或在 .env 裡設定）')
        sys.exit(1)

    seen_ids = set()
    all_places = []

    for i, query in enumerate(args.queries, 1):
        print(f'[{i}/{len(args.queries)}] 搜尋: {query}')

        try:
            results = search_places_via_apify(token, query, args.max_per_query)
        except Exception as e:
            print(f'  ❌ 失敗: {e}')
            continue

        new_count = 0
        for place in results:
            # Deduplicate by place ID or URL
            place_id = place.get('placeId', '')
            if place_id in seen_ids:
                continue
            seen_ids.add(place_id)

            review_count = place.get('reviewsCount') or place.get('totalScore') or 0
            if review_count < args.min_reviews:
                continue

            name = place.get('title') or place.get('name') or ''
            url = place.get('url') or place.get('googleMapsUri') or ''
            if not url:
                continue

            all_places.append({
                'name': name,
                'url': url,
                'address': place.get('address', ''),
                'rating': place.get('totalScore', 0),
                'review_count': review_count,
                'place_id': place_id,
            })
            new_count += 1

        print(f'  → {len(results)} 筆，新增 {new_count}（累計 {len(all_places)}）')

    # Sort by review count descending
    all_places.sort(key=lambda x: x['review_count'], reverse=True)

    print(f'\n{"=" * 60}')
    print(f'搜尋完成：共找到 {len(all_places)} 家店')
    print(f'{"=" * 60}')

    # Show top 20
    print(f'\n{"店名":<25} {"評論數":>6} {"評分":>4}  地址')
    print('-' * 80)
    for p in all_places[:20]:
        addr = p["address"][:30] if p["address"] else ''
        print(f'{p["name"]:<25} {p["review_count"]:>6} {p["rating"]:>4.1f}  {addr}')
    if len(all_places) > 20:
        print(f'... 還有 {len(all_places) - 20} 家')

    # Prepare output (stores.json format — only name + url)
    output_stores = [{'name': p['name'], 'url': p['url']} for p in all_places]

    # Merge with existing
    if args.merge and args.output.exists():
        existing = json.loads(args.output.read_text(encoding='utf-8'))
        existing_urls = {s['url'] for s in existing}
        new_stores = [s for s in output_stores if s['url'] not in existing_urls]
        output_stores = existing + new_stores
        print(f'\n合併模式：原有 {len(existing)} 家 + 新增 {len(new_stores)} 家 '
              f'= {len(output_stores)} 家')

    # Write
    args.output.write_text(
        json.dumps(output_stores, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print(f'\n📁 已寫入: {args.output} ({len(output_stores)} 家)')
    print(f'   可直接用於: python review_scraper/batch_crawl.py')


if __name__ == '__main__':
    main()
