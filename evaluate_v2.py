#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TrueRating QA 進階評估腳本 v2
=============================

功能:
  1. 超參數網格搜尋(找最佳 WASH_VERDICT_THRESHOLD)
  2. Stage 2 LLM 抽樣輸出(把 Stage 1 漏抓的店抽出來給 LLM 分析)

用法:
  python3 evaluate_v2.py restaurant_data

產出:
  - tune_results.json    網格搜尋完整結果
  - llm_input.json       給 Claude 跑 Stage 2 模擬的抽樣(把整份貼給 Claude)
"""
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

TODAY = date.today()

# ─── Stage 1 規則(摘自 TRUE_RATING_LOGIC.md)───────────────
NON_SEND_KEYWORDS = ['打卡', '活動', '五星', '五顆星', '好評']
SEND_KEYWORDS = ['評論送', '打卡送', '好評送', '免費送', '送小菜', '送起司球',
                 '送飲料', '送肉', '送單點', '送麻糬', '送奶酪']
JACCARD_THRESHOLD = 0.75
MIN_TEMPLATE_CHARS = 6

# 網格搜尋的門檻列表
GRID_THRESHOLDS = [0.005, 0.01, 0.015, 0.02, 0.025, 0.03,
                   0.04, 0.05, 0.06, 0.08, 0.10, 0.15]


# ─── 規則引擎 ───────────────────────────────────────────────

# Mirrors auditEngine.ts's EMPTY_WORDS / low_info logic, so this offline
# evaluator's washed_ratio stays behaviorally consistent with the live Stage 1
# engine: a short generic review is low-information, not washing evidence by
# itself, unless it co-occurs with a spike period or high cross-review
# similarity (see detect_low_info_and_escalated below).
EMPTY_WORDS = {
    '讚', '超讚', '好吃', '推', '棒', '美味', '讚的', '讚啦', '很讚', '推推',
    '讚喔', '好喝', '讚讚', '不錯', '好讚', '好店', '優', '優質', '讚哩',
    '讚啊', '極推', '大推', '好食', '真讚', '好美味',
}
REPEATING_PRAISE_RE = re.compile(r'^(讚+|推+|棒+|好+|讚+推+)$')
STRIP_PUNCT_RE = re.compile(r'[\s!！~～.。?？,，、]')

SIMILARITY_SIGNAL_NGRAM = 3
SIMILARITY_SIGNAL_THRESHOLD = 0.45
LOW_INFO_ESCALATION_SIMILAR_COUNT = 2


def has_bribe(text):
    if not text:
        return False
    return any(kw in text for kw in NON_SEND_KEYWORDS + SEND_KEYWORDS)


def get_ngram(text, n=2):
    text = re.sub(r'\s+', '', text or '')
    return set(text[i:i + n] for i in range(len(text) - n + 1)) if len(text) >= n else set()


def get_2gram(text):
    return get_ngram(text, 2)


def jaccard(a, b):
    if not a or not b:
        return 0
    return len(a & b) / len(a | b)


def detect_templates(reviews):
    grams = []
    for r in reviews:
        text = r.get('Text', '') or ''
        cleaned = re.sub(r'\s+', '', text)
        grams.append(get_2gram(text) if len(cleaned) > MIN_TEMPLATE_CHARS else None)
    flags = [False] * len(reviews)
    for i in range(len(reviews)):
        if grams[i] is None:
            continue
        for j in range(i + 1, len(reviews)):
            if grams[j] is None:
                continue
            if jaccard(grams[i], grams[j]) > JACCARD_THRESHOLD:
                flags[i] = flags[j] = True
    return flags


def detect_similar_counts(reviews, threshold=SIMILARITY_SIGNAL_THRESHOLD, n=SIMILARITY_SIGNAL_NGRAM):
    """Mirrors auditEngine.ts's soft structural-similarity signal (3-gram,
    ~45%) — counts, per review, how many OTHER reviews it's similar to. Purely
    a diagnostic/escalation signal here, not a standalone washed criterion."""
    grams = []
    for r in reviews:
        text = r.get('Text', '') or ''
        cleaned = re.sub(r'\s+', '', text)
        grams.append(get_ngram(text, n) if len(cleaned) > MIN_TEMPLATE_CHARS else None)

    counts = [0] * len(reviews)
    for i in range(len(reviews)):
        if grams[i] is None:
            continue
        for j in range(i + 1, len(reviews)):
            if grams[j] is None:
                continue
            if jaccard(grams[i], grams[j]) >= threshold:
                counts[i] += 1
                counts[j] += 1
    return counts


def is_generic_short_review(text, stars):
    if stars < 4:
        return False
    cleaned = STRIP_PUNCT_RE.sub('', text or '')
    return cleaned in EMPTY_WORDS or bool(REPEATING_PRAISE_RE.match(cleaned))


def detect_low_info_and_escalated(reviews, bribe_flags, spike_flags, similar_counts):
    """Mirrors auditEngine.ts's low_info category. Short, generic, no-incentive
    reviews are informationally weak rather than washed evidence — UNLESS they
    also co-occur with a spike period or a high cross-review similarity count,
    which together indicate deliberate templated posting rather than an
    authentic (if terse) customer. Returns (low_info_flags, escalated_flags);
    escalated_flags should be folded into washed_flags, low_info_flags should not."""
    low_info_flags = []
    escalated_flags = []
    for r, bribe, spike, sim_count in zip(reviews, bribe_flags, spike_flags, similar_counts):
        text = r.get('Text', '') or ''
        try:
            stars = int(r.get('Stars') or 0)
        except ValueError:
            stars = 0

        if bribe or not is_generic_short_review(text, stars):
            low_info_flags.append(False)
            escalated_flags.append(False)
            continue

        escalated = bool(spike) or sim_count >= LOW_INFO_ESCALATION_SIMILAR_COUNT
        low_info_flags.append(not escalated)
        escalated_flags.append(escalated)
    return low_info_flags, escalated_flags


def detect_spike_months(reviews):
    counts = defaultdict(int)
    months = []
    for r in reviews:
        try:
            dt = datetime.strptime(r.get('Time', ''), '%Y-%m-%d')
            mk = dt.strftime('%Y-%m')
            counts[mk] += 1
            months.append(mk)
        except (ValueError, TypeError):
            months.append(None)
    if not counts:
        return [False] * len(reviews), set()
    avg = sum(counts.values()) / len(counts)
    spike = {m for m, c in counts.items() if c > avg * 2 and c >= 10}
    return [(m in spike) if m else False for m in months], spike


def analyze_restaurant(csv_path):
    reviews = []
    with open(csv_path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            reviews.append(row)
    if not reviews:
        return None

    bribe = [has_bribe(r.get('Text', '')) for r in reviews]
    tmpl = detect_templates(reviews)
    spike_flags, spike_months = detect_spike_months(reviews)
    similar_counts = detect_similar_counts(reviews)
    low_info_flags, escalated_short_flags = detect_low_info_and_escalated(reviews, bribe, spike_flags, similar_counts)

    # escalated_short_flags counts toward washed (spike/similarity-corroborated
    # short reviews); low_info_flags does NOT — those are reported separately
    # below so the comparison against true_label stays clear (low_info is
    # explicitly "not washed", not silently absorbed into either bucket).
    washed = [b or t or e for b, t, e in zip(bribe, tmpl, escalated_short_flags)]

    return {
        'reviews': reviews,
        'bribe_flags': bribe,
        'template_flags': tmpl,
        'spike_flags': spike_flags,
        'spike_months': sorted(spike_months),
        'low_info_flags': low_info_flags,
        'low_info_count': sum(low_info_flags),
        'low_info_ratio': sum(low_info_flags) / len(reviews),
        'escalated_short_flags': escalated_short_flags,
        'washed_flags': washed,
        'washed_ratio': sum(washed) / len(reviews),
        'total': len(reviews),
    }


def evaluate_dataset(base_path):
    base = Path(base_path)
    out = []
    for subdir in sorted(base.iterdir()):
        if not subdir.is_dir() or '__' not in subdir.name:
            continue
        category, label = subdir.name.split('__', 1)
        for csv_file in sorted(subdir.glob('*.csv')):
            a = analyze_restaurant(csv_file)
            if a:
                out.append({
                    'restaurant': csv_file.stem,
                    'csv_path': str(csv_file),
                    'category': category,
                    'true_label': label,
                    **a,
                })
    return out


# ─── 指標計算 ───────────────────────────────────────────────

def confusion_matrix(results, threshold):
    tp = fn = fp = tn = 0
    for r in results:
        v = '有洗' if r['washed_ratio'] > threshold else '沒洗'
        if r['true_label'] == '有洗':
            tp += (v == '有洗')
            fn += (v == '沒洗')
        else:
            fp += (v == '有洗')
            tn += (v == '沒洗')
    total = tp + fn + fp + tn
    p = tp / (tp + fp) if (tp + fp) else 0
    r_ = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * p * r_ / (p + r_) if (p + r_) else 0
    return {
        'TP': tp, 'FN': fn, 'FP': fp, 'TN': tn,
        'accuracy': round((tp + tn) / total, 3) if total else 0,
        'precision': round(p, 3),
        'recall': round(r_, 3),
        'f1': round(f1, 3),
    }


# ─── 網格搜尋 ───────────────────────────────────────────────

def grid_search(results):
    print('\n' + '=' * 70)
    print('超參數網格搜尋:WASH_VERDICT_THRESHOLD')
    print('=' * 70)
    print(f"{'門檻':<8} {'TP':<4} {'FN':<4} {'FP':<4} {'TN':<4} "
          f"{'Acc':<8} {'Prec':<8} {'Rec':<8} {'F1':<8}")
    print('-' * 70)

    rows = [{'threshold': t, **confusion_matrix(results, t)}
            for t in GRID_THRESHOLDS]
    best = max(rows, key=lambda x: x['f1'])

    for r in rows:
        marker = ' ⭐' if r['threshold'] == best['threshold'] else ''
        print(f"{r['threshold']:<8.3f} {r['TP']:<4} {r['FN']:<4} {r['FP']:<4} {r['TN']:<4} "
              f"{r['accuracy']:<8.1%} {r['precision']:<8.1%} {r['recall']:<8.1%} "
              f"{r['f1']:<8.3f}{marker}")

    print(f"\n⭐ 最佳門檻 = {best['threshold']} → F1 = {best['f1']}")
    return best, rows


# ─── Stage 2 LLM 抽樣 ───────────────────────────────────────

def sample_for_llm(results, best_threshold, per_store=8):
    """挑出『有洗但 Stage 1 漏抓』的店家,抽樣評論"""
    missed = [r for r in results
              if r['true_label'] == '有洗'
              and r['washed_ratio'] <= best_threshold]

    print('\n' + '=' * 70)
    print(f'Stage 2 LLM 抽樣')
    print('=' * 70)
    print(f"找到 {len(missed)} 家「真正有洗但 Stage 1 漏抓」的店家:")

    output = []
    for store in missed:
        five_star = [r for r in store['reviews']
                     if r.get('Stars') == '5' and (r.get('Text') or '').strip()]
        sample = []
        for r in five_star:
            try:
                dt = datetime.strptime(r['Time'], '%Y-%m-%d').date()
                days = (TODAY - dt).days
                month = dt.strftime('%Y-%m')
                text = r['Text'].strip()
                sample.append({
                    'username': r.get('Username', '?'),
                    'text': text,
                    'stars': 5,
                    'daysElapsed': days,
                    'isSpikePeriod': month in store['spike_months'],
                    '_length': len(text),
                })
            except (ValueError, KeyError):
                pass

        # 優先抽:1) spike 期 2) 短評
        sample.sort(key=lambda x: (not x['isSpikePeriod'], x['_length']))
        picked = sample[:per_store]
        for p in picked:
            del p['_length']

        if picked:
            output.append({
                'store_name': store['restaurant'],
                'category': store['category'],
                'true_label': store['true_label'],
                'stage1_washed_ratio': round(store['washed_ratio'], 3),
                'spike_months': store['spike_months'],
                'sample': picked,
            })
            print(f"  • {store['restaurant']:<20} (Stage 1 washed={store['washed_ratio']:.1%}) "
                  f"→ 抽 {len(picked)} 則 5 星評論")

    return output


# ─── main ───────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print('用法: python3 evaluate_v2.py <restaurant_data 路徑>')
        sys.exit(1)

    base = sys.argv[1]
    results = evaluate_dataset(base)
    if not results:
        print(f'錯誤:在 {base} 找不到資料。')
        sys.exit(1)

    print(f'[資料集] 共 {len(results)} 家店')

    avg_low_info = sum(r['low_info_ratio'] for r in results) / len(results)
    total_low_info = sum(r['low_info_count'] for r in results)
    print(f'📋 低資訊評論 (low_info，不計入洗評):共 {total_low_info} 則，平均占比 {avg_low_info:.1%}')

    best, all_rows = grid_search(results)
    llm_input = sample_for_llm(results, best['threshold'])

    # 輸出
    out_dir = Path('.').resolve()
    (out_dir / 'tune_results.json').write_text(
        json.dumps({'best': best, 'grid': all_rows}, ensure_ascii=False, indent=2),
        encoding='utf-8')
    (out_dir / 'llm_input.json').write_text(
        json.dumps(llm_input, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\n' + '=' * 70)
    print('已輸出檔案:')
    print('=' * 70)
    print(f"  📊 tune_results.json   (網格搜尋結果)")
    print(f"  🤖 llm_input.json      ← 把這個整份內容貼給 Claude!")
    print()
    print("下一步:")
    print("  1. 把 llm_input.json 內容整份複製貼給 Claude")
    print("  2. Claude 會扮演 Gemini 跑 Stage 2 LLM 模擬分析")
    print("  3. 拿到 Stage 1 + Stage 2 整合後的最終 F1")


if __name__ == '__main__':
    main()
