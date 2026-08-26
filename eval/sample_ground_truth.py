#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Review-level ground truth 分層抽樣腳本 (Issue #67)
===================================================

從 audit_cache 分層抽樣 100 家店，每家抽 20 則評論，產出待人工標註的 CSV。
標註完成後可用 evaluate_v2.py --sweep-config 做 parameter sweep。

用法:
  python eval/sample_ground_truth.py
  python eval/sample_ground_truth.py --stores 50 --per-store 30
  python eval/sample_ground_truth.py --seed 123

產出:
  eval/ground_truth_labeling/          每家店一個 CSV（人工標註用）
  eval/ground_truth_labeling.json      完整抽樣資訊（含 Stage 1 信號，供事後分析）
"""
import argparse
import csv
import json
import os
import random
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / 'review_scraper'))


# ─── Store name extraction (same as evaluate_stage2_cost.py) ──

def _extract_store_name(url: str) -> str:
    decoded = unquote(url).replace('+', ' ')
    m = re.search(r'[?&]query=([^&]+)', decoded)
    if m:
        return m.group(1).strip()
    m = re.search(r'[?&]q=([^&]+)', decoded)
    if m:
        full = m.group(1)
        nm = re.search(r'號(.+)', full)
        if nm:
            name = nm.group(1).strip(' -')
            name = re.sub(r'\d+\s*樓$', '', name).strip()
            if name:
                return name
    return decoded[:30]


def _extract_place_id(url: str) -> str:
    """Extract ChIJ... place_id from query_place_id param if present."""
    m = re.search(r'query_place_id=([^&]+)', url)
    return m.group(1) if m else ''


# ─── Data loading ──────────────────────────────────────────

def load_stores(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT place_id, audit_json FROM audit_cache")

    stores = []
    for url_key, audit_json in cursor:
        data = json.loads(audit_json)
        audited = data.get('auditedReviews', [])
        signals = data.get('signals', {})

        if len(audited) < 10:  # skip stores with too few reviews
            continue

        n_total = len(audited)
        n_washed = sum(1 for r in audited if r.get('audit', {}).get('isWashed'))
        wash_rate = n_washed / n_total

        # Count by issueType
        type_counts = {}
        for r in audited:
            it = r.get('audit', {}).get('issueType') or 'null'
            type_counts[it] = type_counts.get(it, 0) + 1

        stores.append({
            'url_key': url_key,
            'store_name': _extract_store_name(url_key),
            'place_id': _extract_place_id(url_key),
            'n_total': n_total,
            'n_washed': n_washed,
            'wash_rate': wash_rate,
            'type_counts': type_counts,
            'audited_reviews': audited,
            'signals': signals,
        })

    conn.close()
    return stores


# ─── Stratified store sampling ─────────────────────────────

def stratified_store_sample(stores: list[dict], n: int, seed: int) -> list[dict]:
    """Sample n stores with 3 strata by wash rate, matching Issue #67 spec:
      - high wash (>15%): oversampled for signal validation
      - mid wash (3-15%): the borderline cases
      - low wash (<3%): verify false negatives
    """
    rng = random.Random(seed)

    high = [s for s in stores if s['wash_rate'] > 0.15]
    mid = [s for s in stores if 0.03 <= s['wash_rate'] <= 0.15]
    low = [s for s in stores if s['wash_rate'] < 0.03]

    # Allocation: 30% high, 40% mid, 30% low (oversample extremes)
    n_high = round(n * 0.30)
    n_low = round(n * 0.30)
    n_mid = n - n_high - n_low

    n_high = min(n_high, len(high))
    n_mid = min(n_mid, len(mid))
    n_low = min(n_low, len(low))

    sampled = (
        rng.sample(high, n_high)
        + rng.sample(mid, n_mid)
        + rng.sample(low, n_low)
    )

    return sampled


# ─── Review sampling within a store ────────────────────────

def sample_reviews(audited_reviews: list[dict], n: int, seed: int) -> list[dict]:
    """Sample n reviews from a store with stratification to ensure coverage:
      - All S1-washed reviews (up to n/2) — need to verify precision
      - Remaining from non-washed, prioritizing 5-star with text — check recall
    """
    rng = random.Random(seed)

    washed = [r for r in audited_reviews if r.get('audit', {}).get('isWashed')]
    clean = [r for r in audited_reviews if not r.get('audit', {}).get('isWashed')]

    # Take up to half from washed
    n_washed = min(len(washed), n // 2)
    # Fill rest from clean
    n_clean = n - n_washed

    rng.shuffle(washed)
    picked_washed = washed[:n_washed]

    # Prioritize 5-star with text (most likely to contain missed washing)
    five_star_text = [r for r in clean if r.get('stars') == 5 and (r.get('text') or '').strip()]
    other_clean = [r for r in clean if r not in five_star_text]
    rng.shuffle(five_star_text)
    rng.shuffle(other_clean)

    # Take 60% from 5-star-with-text, rest from other
    n_five = min(len(five_star_text), round(n_clean * 0.6))
    n_other = n_clean - n_five
    n_other = min(n_other, len(other_clean))

    picked_clean = five_star_text[:n_five] + other_clean[:n_other]

    result = picked_washed + picked_clean
    rng.shuffle(result)  # mix so labeler isn't biased by ordering
    return result


# ─── Output ────────────────────────────────────────────────

def write_store_csv(out_dir: Path, store_name: str, reviews: list[dict], store_idx: int):
    """Write one CSV for human labeling."""
    # Sanitize filename
    safe_name = re.sub(r'[/\\:*?"<>|]', '_', store_name)[:50]
    filename = f"{store_idx:03d}_{safe_name}.csv"
    filepath = out_dir / filename

    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Username', 'Stars', 'Time', 'Text',
            'S1_isWashed', 'S1_issueType', 'S1_confidence',
            'Label',  # ← human fills: 洗 / 沒洗 / 不確定
        ])
        for r in reviews:
            audit = r.get('audit', {})
            writer.writerow([
                r.get('username', ''),
                r.get('stars', ''),
                r.get('time', ''),
                (r.get('text') or '').replace('\n', '\\n'),
                '是' if audit.get('isWashed') else '否',
                audit.get('issueType') or '',
                audit.get('confidenceScore', ''),
                '',  # empty for human to fill
            ])
    return filename


def main():
    parser = argparse.ArgumentParser(description='Review-level ground truth 抽樣 (Issue #67)')
    parser.add_argument('--stores', type=int, default=100, help='抽樣店數 (預設 100)')
    parser.add_argument('--per-store', type=int, default=20, help='每店抽幾則 (預設 20)')
    parser.add_argument('--seed', type=int, default=67, help='隨機種子 (預設 67)')
    parser.add_argument('--db', default=str(REPO_ROOT / 'cache.db'), help='cache.db 路徑')
    args = parser.parse_args()

    print(f'\n{"=" * 70}')
    print(f'Review-level ground truth 抽樣 (Issue #67)')
    print(f'{"=" * 70}')
    print(f'目標: {args.stores} 家店 × {args.per_store} 則/店 = ~{args.stores * args.per_store} 則')
    print(f'seed={args.seed}')

    # Load
    stores = load_stores(args.db)
    print(f'\n載入 {len(stores)} 家店（≥10 則評論）')

    # Stratify
    high = [s for s in stores if s['wash_rate'] > 0.15]
    mid = [s for s in stores if 0.03 <= s['wash_rate'] <= 0.15]
    low = [s for s in stores if s['wash_rate'] < 0.03]
    print(f'  高洗 (>15%): {len(high)} 家')
    print(f'  中洗 (3-15%): {len(mid)} 家')
    print(f'  低洗 (<3%):  {len(low)} 家')

    sampled = stratified_store_sample(stores, args.stores, args.seed)
    print(f'\n抽樣 {len(sampled)} 家:')

    s_high = sum(1 for s in sampled if s['wash_rate'] > 0.15)
    s_mid = sum(1 for s in sampled if 0.03 <= s['wash_rate'] <= 0.15)
    s_low = sum(1 for s in sampled if s['wash_rate'] < 0.03)
    print(f'  高洗: {s_high}, 中洗: {s_mid}, 低洗: {s_low}')

    # Sample reviews and write CSVs
    out_dir = REPO_ROOT / 'eval' / 'ground_truth_labeling'
    out_dir.mkdir(exist_ok=True)

    print(f'\n{"=" * 70}')
    print(f'{"#":<4} {"店名":<30} {"總":>5} {"洗率":>6} {"抽":>4} {"S1洗":>5}')
    print(f'{"-" * 70}')

    all_samples = []
    total_reviews = 0
    total_washed_in_sample = 0

    for i, store in enumerate(sorted(sampled, key=lambda s: s['wash_rate'])):
        reviews = sample_reviews(store['audited_reviews'], args.per_store, args.seed + i)
        n_washed = sum(1 for r in reviews if r.get('audit', {}).get('isWashed'))
        total_reviews += len(reviews)
        total_washed_in_sample += n_washed

        filename = write_store_csv(out_dir, store['store_name'], reviews, i + 1)

        name_short = store['store_name'][:28]
        print(f'{i+1:<4} {name_short:<30} {store["n_total"]:>5} '
              f'{store["wash_rate"]:>5.1%} {len(reviews):>4} {n_washed:>5}')

        all_samples.append({
            'store_name': store['store_name'],
            'place_id': store['place_id'],
            'url_key': store['url_key'],
            'n_total': store['n_total'],
            'wash_rate_s1': round(store['wash_rate'], 4),
            'type_counts': store['type_counts'],
            'n_sampled': len(reviews),
            'n_washed_in_sample': n_washed,
            'csv_file': filename,
        })

    # Summary
    print(f'\n{"=" * 70}')
    print(f'總計')
    print(f'{"=" * 70}')
    print(f'  店數: {len(sampled)}')
    print(f'  總評論: {total_reviews}')
    print(f'  其中 S1 判洗: {total_washed_in_sample} ({total_washed_in_sample/total_reviews:.1%})')
    print(f'  CSV 目錄: {out_dir}/')

    # Write index JSON
    index = {
        'created': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'seed': args.seed,
        'n_stores': len(sampled),
        'per_store': args.per_store,
        'total_reviews': total_reviews,
        'strata': {'high': s_high, 'mid': s_mid, 'low': s_low},
        'stores': all_samples,
    }
    index_path = REPO_ROOT / 'eval' / 'ground_truth_labeling.json'
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  索引檔: {index_path}')

    print(f'\n下一步:')
    print(f'  1. 開啟 {out_dir}/ 的 CSV 檔')
    print(f'  2. 每則評論的 Label 欄填入: 洗 / 沒洗 / 不確定')
    print(f'  3. 標完後可用 evaluate_v2.py 做 parameter sweep')


if __name__ == '__main__':
    main()
