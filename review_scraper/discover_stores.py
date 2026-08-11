#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 Apify Google Maps Scraper 搜尋台大附近的餐飲店家，產出 stores.json。

只搜地點清單，不爬評論（maxReviews=0），Apify 用量極小。
輸出按區域分組，方便人工檢查和補漏。

用法:
  # 用 .env 裡的 APIFY_TOKEN
  review_scraper/venv/bin/python review_scraper/discover_stores.py

  # 合併到現有 stores.json（保留原本的店）
  review_scraper/venv/bin/python review_scraper/discover_stores.py --merge

  # 調整最少評論數門檻
  review_scraper/venv/bin/python review_scraper/discover_stores.py --min-reviews 20

產出格式與 stores.json 相容，可直接用於 batch_crawl.py。
"""
import argparse
import json
import os
import re
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

# ─── 區域定義 ─────────────────────────────────────────────────
# 每個區域有多個搜尋關鍵字，覆蓋不同類型的店
REGIONS = [
    {
        'name': '公館商圈',
        'queries': [
            '公館美食',
            '公館餐廳',
            '公館飲料店',
            '公館小吃',
            '公館咖啡',
        ],
    },
    {
        'name': '台大校園周邊',
        'queries': [
            '台大附近餐廳',
            '台大附近咖啡廳',
            '台大美食',
            '舟山路美食',
        ],
    },
    {
        'name': '溫州街/新生南路',
        'queries': [
            '溫州街餐廳',
            '溫州街咖啡',
            '新生南路餐廳',
            '新生南路美食',
        ],
    },
    {
        'name': '師大/龍泉街',
        'queries': [
            '師大夜市美食',
            '師大餐廳',
            '師大飲料',
            '龍泉街美食',
        ],
    },
    {
        'name': '景美/萬隆',
        'queries': [
            '景美美食',
            '景美餐廳',
            '萬隆美食',
            '景美夜市',
        ],
    },
    {
        'name': '大安/科技大樓',
        'queries': [
            '大安區小吃',
            '科技大樓站美食',
            '復興南路餐廳',
            '和平東路美食',
        ],
    },
    {
        'name': '古亭/中正',
        'queries': [
            '古亭美食',
            '古亭餐廳',
            '南昌路美食',
            '中正區小吃',
        ],
    },
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
            'maxReviews': 0,
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


def classify_region(address: str, regions: list) -> str:
    """Guess which region a store belongs to based on address keywords."""
    address = address or ''
    # Map address keywords to region names
    keyword_map = [
        ('公館', '公館商圈'),
        ('羅斯福路', '公館商圈'),
        ('汀州路', '公館商圈'),
        ('舟山路', '台大校園周邊'),
        ('基隆路.*大安', '台大校園周邊'),
        ('溫州街', '溫州街/新生南路'),
        ('新生南路', '溫州街/新生南路'),
        ('辛亥路', '溫州街/新生南路'),
        ('師大', '師大/龍泉街'),
        ('龍泉街', '師大/龍泉街'),
        ('泰順街', '師大/龍泉街'),
        ('景美', '景美/萬隆'),
        ('萬隆', '景美/萬隆'),
        ('景興路', '景美/萬隆'),
        ('大安區', '大安/科技大樓'),
        ('復興南路', '大安/科技大樓'),
        ('和平東路', '大安/科技大樓'),
        ('科技大樓', '大安/科技大樓'),
        ('古亭', '古亭/中正'),
        ('南昌路', '古亭/中正'),
        ('中正區', '古亭/中正'),
    ]
    for pattern, region in keyword_map:
        if re.search(pattern, address):
            return region
    return '其他'


def main():
    parser = argparse.ArgumentParser(
        description='用 Apify 搜尋台大附近餐飲店家，按區域分組產出 stores.json')
    parser.add_argument('--max-per-query', type=int, default=40,
                        help='每個關鍵字最多回傳幾家 (預設 40)')
    parser.add_argument('-o', '--output', type=Path,
                        default=SCRIPT_DIR / 'stores.json',
                        help='輸出檔案路徑 (預設 review_scraper/stores.json)')
    parser.add_argument('--merge', action='store_true',
                        help='合併到現有 stores.json（不覆蓋已有的店）')
    parser.add_argument('--min-reviews', type=int, default=10,
                        help='最少評論數門檻 (預設 10)')
    parser.add_argument('--regions', nargs='+', default=None,
                        help='只搜指定區域（例如 --regions 公館商圈 師大/龍泉街）')
    args = parser.parse_args()

    token = os.environ.get('APIFY_TOKEN')
    if not token:
        print('❌ 請設定 APIFY_TOKEN 環境變數（或在 .env 裡設定）')
        sys.exit(1)

    # Filter regions if specified
    regions = REGIONS
    if args.regions:
        regions = [r for r in REGIONS if r['name'] in args.regions]
        if not regions:
            print(f'❌ 找不到指定區域，可用的區域：')
            for r in REGIONS:
                print(f'   - {r["name"]}')
            sys.exit(1)

    seen_ids = set()
    all_places = []  # (place_dict, region_name)

    all_queries = [(q, r['name']) for r in regions for q in r['queries']]
    total = len(all_queries)

    for i, (query, region_name) in enumerate(all_queries, 1):
        print(f'[{i}/{total}] [{region_name}] {query}')

        try:
            results = search_places_via_apify(token, query, args.max_per_query)
        except Exception as e:
            print(f'  ❌ 失敗: {e}')
            continue

        new_count = 0
        for place in results:
            place_id = place.get('placeId', '')
            if place_id in seen_ids:
                continue
            seen_ids.add(place_id)

            review_count = place.get('reviewsCount') or 0
            if review_count < args.min_reviews:
                continue

            name = place.get('title') or place.get('name') or ''
            url = place.get('url') or ''
            address = place.get('address', '')
            if not url:
                continue

            # Classify region by address (may differ from search query region)
            actual_region = classify_region(address, regions)

            all_places.append({
                'name': name,
                'url': url,
                'address': address,
                'rating': place.get('totalScore', 0),
                'review_count': review_count,
                'place_id': place_id,
                'region': actual_region,
            })
            new_count += 1

        print(f'  → {len(results)} 筆，新增 {new_count}（累計 {len(all_places)}）')

    # ─── 按區域分組報告 ───
    region_groups = {}
    for p in all_places:
        region_groups.setdefault(p['region'], []).append(p)

    print(f'\n{"=" * 70}')
    print(f'搜尋完成：共找到 {len(all_places)} 家店')
    print(f'{"=" * 70}')

    for region_name in [r['name'] for r in REGIONS] + ['其他']:
        places = region_groups.get(region_name, [])
        if not places:
            continue
        places.sort(key=lambda x: x['review_count'], reverse=True)

        print(f'\n── {region_name} ({len(places)} 家) ──')
        print(f'  {"店名":<22} {"評論數":>5} {"評分":>4}  地址')
        print(f'  {"-" * 65}')
        for p in places:
            addr = p['address'][:28] if p['address'] else ''
            print(f'  {p["name"]:<22} {p["review_count"]:>5} {p["rating"]:>4.1f}  {addr}')

    # ─── 輸出 stores.json ───
    # Sort: by region then by review count
    region_order = {r['name']: i for i, r in enumerate(REGIONS)}
    region_order['其他'] = len(REGIONS)
    all_places.sort(key=lambda x: (region_order.get(x['region'], 99),
                                    -x['review_count']))

    output_stores = [
        {'name': p['name'], 'url': p['url'], 'region': p['region']}
        for p in all_places
    ]

    if args.merge and args.output.exists():
        existing = json.loads(args.output.read_text(encoding='utf-8'))
        existing_urls = {s['url'] for s in existing}
        new_stores = [s for s in output_stores if s['url'] not in existing_urls]
        output_stores = existing + new_stores
        print(f'\n合併模式：原有 {len(existing)} 家 + 新增 {len(new_stores)} 家 '
              f'= {len(output_stores)} 家')

    args.output.write_text(
        json.dumps(output_stores, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print(f'\n📁 已寫入: {args.output} ({len(output_stores)} 家)')
    print(f'   可直接用於: python review_scraper/batch_crawl.py')
    print(f'\n💡 檢查清單後可手動補漏，每個區域都列出來了方便對照')


if __name__ == '__main__':
    main()
