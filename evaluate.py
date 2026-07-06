#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TrueRating QA 評估腳本
======================

用途:對 restaurant_data/ 內的標注資料,跑 Stage 1 規則引擎,
     算出系統判定 vs 人工標籤的混淆矩陣與 F1 分數。

使用方式:
    python3 evaluate.py <restaurant_data 路徑>

預期資料夾結構:
    restaurant_data/
    ├── 拉麵__有洗/
    │   ├── 店A.csv
    │   └── 店B.csv
    ├── 拉麵__沒洗/
    │   └── ...
    ├── 手搖__有洗/
    └── ...

CSV 欄位:Username, Stars, Time, RawTime, Text, Images

輸出:
    - 終端機:每家店分析結果 + 整體混淆矩陣 + F1
    - results.json:完整數據
    - report.md:可直接複製到測試報告的段落

判斷邏輯依據 TRUE_RATING_LOGIC.md(僅實作 Stage 1,Stage 2 LLM 部分需在
完整系統環境內執行)。
"""

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ============================================================
# Stage 1 規則(摘自 TRUE_RATING_LOGIC.md)
# ============================================================

# 顯性利益交換關鍵字(非「送」字類)
NON_SEND_KEYWORDS = ['打卡', '活動', '五星', '五顆星', '好評']

# 「送 X」類關鍵字
SEND_KEYWORDS = [
    '評論送', '打卡送', '好評送', '免費送',
    '送小菜', '送起司球', '送飲料', '送肉',
    '送單點', '送麻糬', '送奶酪'
]

# 排除詞:含「送」但非利益交換
SEND_EXCLUSIONS = ['外送', '配送', '送禮', '送給']

# 判定門檻:單店洗評比例超過此值,系統判定該店為「有洗」
WASH_VERDICT_THRESHOLD = 0.05

# Jaccard 相似度門檻
JACCARD_THRESHOLD = 0.75
MIN_TEMPLATE_CHARS = 6


def check_explicit_bribe(text):
    """規則 2.1:顯性利益交換關鍵字匹配"""
    if not text:
        return False
    for kw in NON_SEND_KEYWORDS:
        if kw in text:
            return True
    for kw in SEND_KEYWORDS:
        if kw in text:
            return True
    return False


def get_2gram_chars(text):
    """擷取 2-Gram 字符特徵(去空白)"""
    text = re.sub(r'\s+', '', text or '')
    if len(text) < 2:
        return set()
    return set(text[i:i + 2] for i in range(len(text) - 1))


def jaccard(s1, s2):
    if not s1 or not s2:
        return 0.0
    inter = len(s1 & s2)
    union = len(s1 | s2)
    return inter / union if union else 0.0


def detect_template_clusters(reviews):
    """規則 2.2:Pairwise Jaccard 相似度模板偵測"""
    grams = []
    for r in reviews:
        text = r.get('Text', '') or ''
        cleaned = re.sub(r'\s+', '', text)
        grams.append(get_2gram_chars(text) if len(cleaned) > MIN_TEMPLATE_CHARS else None)

    flags = [False] * len(reviews)
    for i in range(len(reviews)):
        if grams[i] is None:
            continue
        for j in range(i + 1, len(reviews)):
            if grams[j] is None:
                continue
            if jaccard(grams[i], grams[j]) > JACCARD_THRESHOLD:
                flags[i] = True
                flags[j] = True
    return flags


def detect_spike_months(reviews):
    """輔助規則:時間密度暴增特徵"""
    month_counts = defaultdict(int)
    review_months = []
    for r in reviews:
        date_str = r.get('Time', '')
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            mk = dt.strftime('%Y-%m')
            month_counts[mk] += 1
            review_months.append(mk)
        except (ValueError, TypeError):
            review_months.append(None)

    if not month_counts:
        return [False] * len(reviews)

    avg = sum(month_counts.values()) / len(month_counts)
    spike = {m for m, c in month_counts.items() if c > avg * 2 and c >= 10}
    return [(m in spike) if m else False for m in review_months]


# ============================================================
# 分析單家店
# ============================================================

def analyze_restaurant(csv_path):
    reviews = []
    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            reviews.append(row)

    if not reviews:
        return None

    bribe_flags = [check_explicit_bribe(r.get('Text', '')) for r in reviews]
    template_flags = detect_template_clusters(reviews)
    spike_flags = detect_spike_months(reviews)

    # Stage 1 洗評判定:顯性關鍵字 OR 樣板
    washed_flags = [b or t for b, t in zip(bribe_flags, template_flags)]

    total = len(reviews)
    valid_stars = [int(r['Stars']) for r in reviews if r.get('Stars', '').isdigit()]
    avg = sum(valid_stars) / len(valid_stars) if valid_stars else 0
    five_star = sum(1 for s in valid_stars if s == 5)

    # 過濾後星等:完全排除洗評
    clean_stars = [int(r['Stars']) for r, w in zip(reviews, washed_flags)
                   if not w and r.get('Stars', '').isdigit()]
    filtered_rating = sum(clean_stars) / len(clean_stars) if clean_stars else 0

    washed_count = sum(washed_flags)
    bribe_count = sum(bribe_flags)
    template_count = sum(template_flags)
    spike_count = sum(spike_flags)
    washed_ratio = washed_count / total

    verdict = '有洗' if washed_ratio > WASH_VERDICT_THRESHOLD else '沒洗'

    return {
        'total_reviews': total,
        'avg_stars': round(avg, 2),
        'five_star_ratio': round(five_star / total, 3),
        'filtered_rating': round(filtered_rating, 2),
        'rating_correction': round(avg - filtered_rating, 2),
        'washed_count': washed_count,
        'washed_ratio': round(washed_ratio, 3),
        'bribe_keyword_hits': bribe_count,
        'template_hits': template_count,
        'spike_period_reviews': spike_count,
        'system_verdict': verdict,
    }


# ============================================================
# 評估資料集
# ============================================================

def evaluate_dataset(base_path):
    base = Path(base_path)
    results = []

    for subdir in sorted(base.iterdir()):
        if not subdir.is_dir() or '__' not in subdir.name:
            continue
        category, label = subdir.name.split('__', 1)
        for csv_file in sorted(subdir.glob('*.csv')):
            stats = analyze_restaurant(csv_file)
            if stats:
                results.append({
                    'restaurant': csv_file.stem,
                    'category': category,
                    'true_label': label,
                    **stats,
                })

    return results


def confusion_matrix(results):
    """以「有洗」為 positive class"""
    tp = sum(1 for r in results if r['true_label'] == '有洗' and r['system_verdict'] == '有洗')
    fn = sum(1 for r in results if r['true_label'] == '有洗' and r['system_verdict'] == '沒洗')
    fp = sum(1 for r in results if r['true_label'] == '沒洗' and r['system_verdict'] == '有洗')
    tn = sum(1 for r in results if r['true_label'] == '沒洗' and r['system_verdict'] == '沒洗')

    total = len(results)
    accuracy = (tp + tn) / total if total else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    return {
        'TP': tp, 'FN': fn, 'FP': fp, 'TN': tn,
        'accuracy': round(accuracy, 3),
        'precision': round(precision, 3),
        'recall': round(recall, 3),
        'f1': round(f1, 3),
    }


# ============================================================
# 報告輸出
# ============================================================

def print_report(results, cm):
    print('\n' + '=' * 60)
    print('TrueRating QA 評估報告')
    print('=' * 60)

    print(f'\n[資料集] 總計 {len(results)} 家店\n')
    print(f"{'店家':<20} {'類別':<6} {'標籤':<6} {'評論數':<6} {'平均':<6} "
          f"{'過濾後':<6} {'洗評率':<8} {'判定':<6}")
    print('-' * 80)
    for r in results:
        print(f"{r['restaurant']:<20} {r['category']:<6} {r['true_label']:<6} "
              f"{r['total_reviews']:<6} {r['avg_stars']:<6} {r['filtered_rating']:<6} "
              f"{r['washed_ratio']:<8.1%} {r['system_verdict']:<6}")

    print('\n' + '=' * 60)
    print('混淆矩陣 (Positive = 有洗)')
    print('=' * 60)
    print(f"                    系統判: 有洗    系統判: 沒洗")
    print(f"  人工標: 有洗        {cm['TP']:>4}            {cm['FN']:>4}")
    print(f"  人工標: 沒洗        {cm['FP']:>4}            {cm['TN']:>4}")

    print('\n' + '=' * 60)
    print('量化指標')
    print('=' * 60)
    print(f"  準確率 Accuracy    = {cm['accuracy']:.1%}")
    print(f"  精準度 Precision   = {cm['precision']:.1%}")
    print(f"  召回率 Recall      = {cm['recall']:.1%}")
    print(f"  F1 Score           = {cm['f1']:.3f}")
    print()


def write_markdown_report(results, cm, out_path):
    lines = []
    lines.append('# TrueRating QA 評估報告\n')
    lines.append(f'> 自動生成於 `evaluate.py` · 依據 `TRUE_RATING_LOGIC.md` Stage 1 規則\n')

    lines.append('## 資料集摘要\n')
    lines.append(f'- 樣本數:{len(results)} 家店')
    cats = defaultdict(int)
    for r in results:
        cats[f"{r['category']}-{r['true_label']}"] += 1
    for k, v in sorted(cats.items()):
        lines.append(f'- {k}:{v} 家')

    lines.append('\n## 混淆矩陣\n')
    lines.append('|  | 系統判定:有洗 | 系統判定:沒洗 |')
    lines.append('|--|---------------|---------------|')
    lines.append(f"| **人工標籤:有洗** | {cm['TP']} | {cm['FN']} |")
    lines.append(f"| **人工標籤:沒洗** | {cm['FP']} | {cm['TN']} |")

    lines.append('\n## 量化指標\n')
    lines.append(f"- **準確率 (Accuracy)**:{cm['accuracy']:.1%}")
    lines.append(f"- **精準度 (Precision)**:{cm['precision']:.1%}")
    lines.append(f"- **召回率 (Recall)**:{cm['recall']:.1%}")
    lines.append(f"- **F1 Score**:{cm['f1']:.3f}")

    lines.append('\n## 各店家詳細結果\n')
    lines.append('| 店家 | 類別 | 標籤 | 評論數 | 原始平均 | 過濾後 | 修正幅度 | 洗評率 | 系統判定 |')
    lines.append('|------|------|------|--------|----------|--------|----------|--------|----------|')
    for r in results:
        match = '✅' if r['true_label'] == r['system_verdict'] else '❌'
        lines.append(f"| {r['restaurant']} | {r['category']} | {r['true_label']} | "
                     f"{r['total_reviews']} | {r['avg_stars']} | {r['filtered_rating']} | "
                     f"{r['rating_correction']:+.2f} | {r['washed_ratio']:.1%} | "
                     f"{r['system_verdict']} {match} |")

    lines.append('\n## 已知限制\n')
    lines.append('1. 本評估僅涵蓋 Stage 1(本地規則引擎),Stage 2(Gemini 語意複審)需於完整系統環境執行。')
    lines.append('2. 人工標籤為團隊內部判斷,未經多人 inter-rater reliability 驗證。')
    lines.append(f'3. 判定門檻 `WASH_VERDICT_THRESHOLD = {WASH_VERDICT_THRESHOLD}` 為啟發式設定,可調整以權衡 Precision / Recall。')

    Path(out_path).write_text('\n'.join(lines), encoding='utf-8')


# ============================================================
# main
# ============================================================

def main():
    if len(sys.argv) < 2:
        print('用法:python3 evaluate.py <restaurant_data 路徑>')
        sys.exit(1)

    base = sys.argv[1]
    results = evaluate_dataset(base)

    if not results:
        print(f'錯誤:在 {base} 找不到資料。')
        print('預期結構:子資料夾命名為「類別__標籤」(如 拉麵__有洗),內含 CSV 檔。')
        sys.exit(1)

    cm = confusion_matrix(results)
    print_report(results, cm)

    out_dir = Path('.').resolve()
    json_path = out_dir / 'results.json'
    md_path = out_dir / 'report.md'

    json_path.write_text(json.dumps({'results': results, 'metrics': cm},
                                    ensure_ascii=False, indent=2), encoding='utf-8')
    write_markdown_report(results, cm, md_path)

    print(f'已輸出:')
    print(f'  - {json_path}')
    print(f'  - {md_path}')


if __name__ == '__main__':
    main()
