#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 Google Places API (New) 搜尋台大附近的餐飲店家，產出 stores.json。

用法:
  # 設定 API key（去 Google Cloud Console 啟用 Places API (New)）
  export GOOGLE_PLACES_API_KEY=your_key_here

  # 搜尋並產出 stores.json
  python review_scraper/discover_stores.py

  # 自訂搜尋範圍（預設台大 1km）
  python review_scraper/discover_stores.py --lat 25.0174 --lng 121.5405 --radius 1500

  # 輸出到指定檔案
  python review_scraper/discover_stores.py -o my_stores.json

Google Places API (New) 免費額度：每月 $200 credit，Nearby Search 每次 $0.032，
搜 200 家大約 $1-2，免費額度內綽綽有餘。

產出格式與 stores.json 相容，可直接用於 batch_crawl.py。
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# NTU main campus center
DEFAULT_LAT = 25.0174
DEFAULT_LNG = 121.5405
DEFAULT_RADIUS = 1000  # meters

# Google Maps place types relevant to restaurants/drinks
PLACE_TYPES = [
    'restaurant',
    'cafe',
    'bakery',
    'meal_takeaway',
    'bar',
]

# Grid offsets (meters) for multi-point search to get better coverage.
# A single Nearby Search returns max 20 results; by searching from
# multiple points we cover more ground.
GRID_OFFSETS_M = [
    (0, 0),
    (400, 0), (-400, 0),
    (0, 400), (0, -400),
    (400, 400), (-400, -400),
    (400, -400), (-400, 400),
]

# Approximate meters per degree at latitude ~25
METERS_PER_DEG_LAT = 110574
METERS_PER_DEG_LNG = 101320  # at lat 25


def nearby_search(api_key: str, lat: float, lng: float, radius: int,
                  place_type: str) -> list:
    """Call Places API (New) Nearby Search and return place results."""
    url = 'https://places.googleapis.com/v1/places:searchNearby'
    body = {
        'includedTypes': [place_type],
        'maxResultCount': 20,
        'locationRestriction': {
            'circle': {
                'center': {'latitude': lat, 'longitude': lng},
                'radius': float(radius),
            }
        },
        'languageCode': 'zh-TW',
    }
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': api_key,
        'X-Goog-FieldMask': 'places.id,places.displayName,places.googleMapsUri,'
                            'places.formattedAddress,places.types,'
                            'places.userRatingCount,places.rating',
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('places', [])
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='replace')
        print(f'  ❌ API error {e.code}: {error_body[:200]}')
        return []
    except Exception as e:
        print(f'  ❌ Request failed: {e}')
        return []


def offset_coords(lat: float, lng: float, offset_m: tuple) -> tuple:
    """Offset lat/lng by (north_m, east_m)."""
    dy, dx = offset_m
    new_lat = lat + dy / METERS_PER_DEG_LAT
    new_lng = lng + dx / METERS_PER_DEG_LNG
    return new_lat, new_lng


def main():
    parser = argparse.ArgumentParser(
        description='用 Google Places API 搜尋台大附近餐飲店家')
    parser.add_argument('--lat', type=float, default=DEFAULT_LAT,
                        help=f'搜尋中心緯度 (預設 {DEFAULT_LAT})')
    parser.add_argument('--lng', type=float, default=DEFAULT_LNG,
                        help=f'搜尋中心經度 (預設 {DEFAULT_LNG})')
    parser.add_argument('--radius', type=int, default=DEFAULT_RADIUS,
                        help=f'搜尋半徑公尺 (預設 {DEFAULT_RADIUS})')
    parser.add_argument('-o', '--output', type=Path,
                        default=Path(__file__).resolve().parent / 'stores.json',
                        help='輸出檔案路徑 (預設 review_scraper/stores.json)')
    parser.add_argument('--merge', action='store_true',
                        help='合併到現有 stores.json（不覆蓋已有的店）')
    parser.add_argument('--min-reviews', type=int, default=10,
                        help='最少評論數門檻，過濾太冷門的店 (預設 10)')
    args = parser.parse_args()

    api_key = os.environ.get('GOOGLE_PLACES_API_KEY')
    if not api_key:
        print('❌ 請設定 GOOGLE_PLACES_API_KEY 環境變數')
        print('   去 Google Cloud Console → APIs & Services → 啟用 Places API (New)')
        print('   然後建立 API key')
        sys.exit(1)

    # Deduplicate by place ID
    seen_ids = set()
    all_places = []

    total_queries = len(GRID_OFFSETS_M) * len(PLACE_TYPES)
    query_num = 0

    for place_type in PLACE_TYPES:
        for offset in GRID_OFFSETS_M:
            query_num += 1
            search_lat, search_lng = offset_coords(args.lat, args.lng, offset)
            print(f'[{query_num}/{total_queries}] '
                  f'{place_type} @ ({search_lat:.4f}, {search_lng:.4f})')

            places = nearby_search(api_key, search_lat, search_lng,
                                   args.radius, place_type)

            new_count = 0
            for p in places:
                pid = p.get('id', '')
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)

                rating_count = p.get('userRatingCount', 0)
                if rating_count < args.min_reviews:
                    continue

                name = p.get('displayName', {}).get('text', '')
                maps_url = p.get('googleMapsUri', '')

                all_places.append({
                    'name': name,
                    'url': maps_url,
                    'address': p.get('formattedAddress', ''),
                    'rating': p.get('rating', 0),
                    'review_count': rating_count,
                    'place_id': pid,
                })
                new_count += 1

            print(f'  → {len(places)} 筆，新增 {new_count}（累計 {len(all_places)}）')
            time.sleep(0.3)  # rate limit courtesy

    # Sort by review count descending (most popular first)
    all_places.sort(key=lambda x: x['review_count'], reverse=True)

    print(f'\n{"=" * 60}')
    print(f'搜尋完成：共找到 {len(all_places)} 家店')
    print(f'{"=" * 60}')

    # Show top 20
    print(f'\n{"店名":<25} {"評論數":>6} {"評分":>4}  地址')
    print('-' * 80)
    for p in all_places[:20]:
        print(f'{p["name"]:<25} {p["review_count"]:>6} {p["rating"]:>4.1f}  '
              f'{p["address"][:30]}')
    if len(all_places) > 20:
        print(f'... 還有 {len(all_places) - 20} 家')

    # Prepare output (stores.json format)
    output_stores = [{'name': p['name'], 'url': p['url']} for p in all_places]

    # Merge with existing if requested
    if args.merge and args.output.exists():
        existing = json.loads(args.output.read_text(encoding='utf-8'))
        existing_urls = {s['url'] for s in existing}
        new_stores = [s for s in output_stores if s['url'] not in existing_urls]
        output_stores = existing + new_stores
        print(f'\n合併模式：原有 {len(existing)} 家 + 新增 {len(new_stores)} 家 '
              f'= {len(output_stores)} 家')

    # Write output
    args.output.write_text(
        json.dumps(output_stores, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print(f'\n📁 已寫入: {args.output} ({len(output_stores)} 家)')
    print(f'   可直接用於: python review_scraper/batch_crawl.py')


if __name__ == '__main__':
    main()
