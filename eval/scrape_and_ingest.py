#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批次爬取 Google Maps 評論 → 轉存為 restaurant_data/ CSV。

用法:
  # 先設定 APIFY_TOKEN 環境變數
  export APIFY_TOKEN=your_token_here
  python3 eval/scrape_and_ingest.py

會自動爬取 STORES 清單中的所有店家，存入對應的 restaurant_data/<類別>__<判定>/ 資料夾。
"""
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
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

# ─── 店家清單 ───────────────────────────────────────────────────

STORES = [
    # (店名, Google Maps URL, 類別, 判定)
    ('詹記', 'https://maps.app.goo.gl/q3qdgNk2Qg4KDqt28', '餐廳', '沒洗'),
    ('池先生', 'https://maps.app.goo.gl/U6nL9DLtyWVZhUCy7', '餐廳', '沒洗'),
    ('藍家割包', 'https://maps.app.goo.gl/cUB9XwJtBr16dqg66', '觀光客店', '沒洗'),
    ('Yoyo韓式飯捲', 'https://maps.app.goo.gl/jLAsj1mV9cNtGUBX7', '餐廳', '沒洗'),
    ('Rice & Roux', 'https://maps.app.goo.gl/uSRZFJSDDUFgU73N8', '餐廳', '沒洗'),
    ('高記-信義小館', 'https://maps.app.goo.gl/2NpNpa3cnj2WqUxt6', '餐廳', '有洗'),
    ('立馬吃一鍋 仁愛店', 'https://maps.app.goo.gl/PgRoYkGKjuDvTa31A', '餐廳', '有洗'),
    ('燒肉政宗', 'https://maps.app.goo.gl/iStux1xcVc5fzBBP9', '餐廳', '有洗'),
    ('麥當勞-台北新生餐廳', 'https://maps.app.goo.gl/vYHs5esmrkfwnpmBA', '連鎖店', '沒洗'),
    ('青山青茶', 'https://maps.app.goo.gl/rQpPa4M4ThLVCjD49', '飲料店', '有洗'),
    ('龜記茗品 公館店', 'https://maps.app.goo.gl/sKFFjHiv47DScw4a9', '飲料店', '沒洗'),
    ('小王煮瓜', 'https://maps.app.goo.gl/vH4tT59dSUmm6Kqz6', '觀光客店', '沒洗'),
    ('韓國時間', 'https://maps.app.goo.gl/xq4kXhe8PN3LUeueA', '餐廳', '沒洗'),
    ('芋芋甜點舖', 'https://maps.app.goo.gl/XXUUXwqcQ7GzScaV7', '餐廳', '沒洗'),
    ('老哥雞肉飯乾拌麵', 'https://maps.app.goo.gl/iztbntTgKYDeEqAp6', '餐廳', '沒洗'),
    ('格芮潘義式創意廚房', 'https://maps.app.goo.gl/SxZwW1GGUBVGFi1D6', '餐廳', '沒洗'),
    ('女九餐廳', 'https://share.google/q1Gk3mMbFBVyLPDqf', '連鎖店', '沒洗'),
    ('活大餐廳', 'https://share.google/4WAt3vInFTWFha9Iu', '連鎖店', '沒洗'),
    ('嘎逼GABI COFFEE-公館店', 'https://share.google/aru0kTHTVhNE8M3I2', '飲料店', '有洗'),
]

MAX_REVIEWS = 300

# 社群曝光相關詞（統計用，不影響判定）
SOCIAL_KEYWORDS = re.compile(
    r'IG|ig|Instagram|instagram|限動|小紅書|網紅|推薦|廣告|KOL|kol|'
    r'YouTub|youtub|部落客|Dcard|dcard|抖音|TikTok|tiktok'
)

# ─── Apify 爬蟲 ────────────────────────────────────────────────

def scrape_via_apify(url: str, max_reviews: int) -> list:
    """Call Apify Google Maps Reviews Scraper and return raw review list."""
    try:
        from apify_client import ApifyClient
    except ImportError:
        print('ERROR: apify-client not installed. Run: pip install apify-client')
        sys.exit(1)

    token = os.environ.get('APIFY_TOKEN')
    if not token:
        print('ERROR: APIFY_TOKEN environment variable not set.')
        sys.exit(1)

    client = ApifyClient(token)
    run = client.actor('compass/Google-Maps-Reviews-Scraper').call(
        run_input={
            'startUrls': [{'url': url}],
            'maxReviews': max_reviews,
            'reviewsSort': 'newest',
            'language': 'zh-TW',
        },
        timeout_secs=300,
    )

    if run.get('status') != 'SUCCEEDED':
        raise RuntimeError(f"Apify run failed: {run.get('status')}")

    dataset_id = run.get('defaultDatasetId')
    if not dataset_id:
        raise RuntimeError('No dataset ID returned')

    items = list(client.dataset(dataset_id).iterate_items())
    return items


def normalize_apify_review(raw: dict) -> dict:
    """Convert Apify review to our CSV format."""
    username = raw.get('name') or raw.get('reviewerName') or 'Anonymous'
    stars = raw.get('stars') or raw.get('rating') or 5
    try:
        stars = int(stars)
    except (ValueError, TypeError):
        stars = 5

    # Time
    time_str = raw.get('publishedAtDate') or raw.get('publishedAt') or ''
    if time_str:
        # Try to parse ISO format to YYYY-MM-DD
        try:
            time_str = datetime.fromisoformat(time_str.replace('Z', '+00:00')).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass

    raw_time = raw.get('publishedAtDate') or ''

    # Text — keep empty for no-text reviews
    text = (raw.get('text') or raw.get('textTranslated') or '').strip() or ''

    # Images
    images = raw.get('reviewImageUrls') or raw.get('images') or []
    if isinstance(images, list):
        image_count = len(images)
    else:
        image_count = 0

    return {
        'Username': username,
        'Stars': stars,
        'Time': time_str,
        'RawTime': raw_time,
        'Text': text,
        'Images': image_count,
    }


def write_csv(reviews: list, path: Path):
    """Write normalized reviews to CSV, newest first."""
    # Sort by Time descending
    def parse_date(r):
        try:
            return datetime.strptime(r['Time'], '%Y-%m-%d')
        except (ValueError, TypeError):
            return datetime.min
    reviews.sort(key=parse_date, reverse=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['Username', 'Stars', 'Time', 'RawTime', 'Text', 'Images'])
        writer.writeheader()
        writer.writerows(reviews)


def count_social_mentions(reviews: list) -> int:
    """Count reviews containing social/influencer keywords."""
    return sum(1 for r in reviews if SOCIAL_KEYWORDS.search(r.get('Text', '')))


# ─── main ───────────────────────────────────────────────────────

def main():
    base = Path(__file__).resolve().parent.parent / 'restaurant_data'
    results = []
    failures = []

    print(f'準備爬取 {len(STORES)} 家店，每家最多 {MAX_REVIEWS} 則\n')

    for i, (name, url, category, label) in enumerate(STORES, 1):
        folder = base / f'{category}__{label}'
        csv_path = folder / f'{name}.csv'

        print(f'[{i}/{len(STORES)}] {name} ({category}__{label})')

        # Strip tracking params from URL
        clean_url = url.split('?')[0] if '?g_st=' in url else url

        try:
            raw_reviews = scrape_via_apify(clean_url, MAX_REVIEWS)
            reviews = [normalize_apify_review(r) for r in raw_reviews]
            write_csv(reviews, csv_path)

            total = len(reviews)
            no_text = sum(1 for r in reviews if not r['Text'])
            social = count_social_mentions(reviews)

            results.append({
                'name': name,
                'category': category,
                'label': label,
                'total': total,
                'no_text': no_text,
                'social_mentions': social,
                'path': str(csv_path.relative_to(base.parent)),
            })
            print(f'  ✓ {total} 則 (無文字: {no_text}, 社群詞: {social})')

        except Exception as e:
            failures.append({'name': name, 'url': clean_url, 'error': str(e)})
            print(f'  ✗ 失敗: {e}')

        # Rate limit courtesy
        if i < len(STORES):
            time.sleep(3)

    # ─── 報告 ───
    print('\n' + '=' * 70)
    print('爬取完成報告')
    print('=' * 70)

    print(f'\n成功: {len(results)}/{len(STORES)} 家\n')
    print(f'{"店名":<25} {"類別":<10} {"判定":<6} {"總則數":>6} {"無文字":>6} {"社群詞":>6}')
    print('-' * 70)
    for r in results:
        print(f'{r["name"]:<25} {r["category"]:<10} {r["label"]:<6} {r["total"]:>6} {r["no_text"]:>6} {r["social_mentions"]:>6}')

    if failures:
        print(f'\n失敗: {len(failures)} 家')
        for f in failures:
            print(f'  ✗ {f["name"]}: {f["error"]}')

    # Save report
    report_path = Path(__file__).resolve().parent / 'scrape_report.json'
    report_path.write_text(
        json.dumps({'results': results, 'failures': failures},
                   ensure_ascii=False, indent=2),
        encoding='utf-8')
    print(f'\n詳細報告: {report_path}')


if __name__ == '__main__':
    main()
