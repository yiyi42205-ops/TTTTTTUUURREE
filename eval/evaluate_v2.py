#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TrueRating QA 進階評估腳本 v2 — 支援參數掃描
=============================================

功能:
  1. 規則引擎參數掃描：所有門檻值集中在 RuleConfig，對一組參數組合清單逐組
     跑 18 家店的標註資料，輸出每組的 precision/recall/F1 對照表。純本地
     運算，不呼叫 Gemini，速度快，可安心大量嘗試組合。
  2. Stage 2 LLM 抽樣輸出（人工模式）：把 Stage 1 漏抓的店抽出來，輸出成
     可整份貼給 Claude 模擬 Stage 2 的格式。
  3. 小樣本 Gemini 測試模式（選用）：實際呼叫 Gemini API，僅抽 2-3 家店，
     用來測試 prompt / 訊號門檻變體對真實 Stage 2 判定的影響。這個模式會
     產生真實 API 費用與配額消耗，預設不會執行，需明確加上 --llm-sample。

用法:
  python3 eval/evaluate_v2.py restaurant_data [--window N]
  --window N  只取每家店最新 N 則評論(預設 100),避免評估吃到未標註的舊評論

  # 用自訂的參數組合清單（JSON 陣列，每個物件是 RuleConfig 的部分欄位）覆寫預設清單
  python3 evaluate_v2.py restaurant_data --sweep-config my_configs.json

  # 小樣本 Gemini 測試模式：實際呼叫 API，僅抽 3 家店（需要 .env 內的 GEMINI_API_KEY）
  python3 evaluate_v2.py restaurant_data --llm-sample 3

產出:
  - tune_results.json    參數掃描完整結果
  - llm_input.json       給 Claude 跑 Stage 2 模擬的抽樣(把整份貼給 Claude)
"""
import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, date
from pathlib import Path

# Allow importing from review_scraper/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from rule_engine import (
    RuleConfig,
    has_bribe,
    get_ngram,
    jaccard,
    detect_templates,
    detect_similarity_signals,
    detect_hot_term_signals,
    detect_nearby_long_review_counts,
    detect_spike_months,
    detect_low_info_and_escalated,
    is_generic_short_review,
    _extract_candidate_terms,
    _parse_timestamp,
)

# Guard: if the frontend audit pipeline is being used for evaluation, it must
# run in "evaluate" mode (VITE_AUDIT_MODE=evaluate) so that all ambiguous
# reviews are sent to Stage 2 without the 15-review production cap.  This
# offline script doesn't go through the frontend, but we surface a warning if
# the env var is set to "production" — someone may have forgotten to switch.
_audit_mode = os.getenv("VITE_AUDIT_MODE", "").lower()
if _audit_mode == "production":
    print(
        "⚠️  警告：VITE_AUDIT_MODE 目前設為 production（Stage 2 抽樣上限 15 則）。\n"
        "   若要透過前端進行完整評估，請改為 VITE_AUDIT_MODE=evaluate 以解除上限。\n"
        "   本離線腳本不受此變數影響，但請確認前端環境一致。",
        file=sys.stderr,
    )

TODAY = date.today()


# ─── 參數設定 ───────────────────────────────────────────────

# 預設要掃描的參數組合清單 —— 可用 --sweep-config 換成自訂清單
DEFAULT_SWEEP = [
    RuleConfig(label='baseline'),
    RuleConfig(label='stricter_jaccard_0.85', jaccard_threshold=0.85),
    RuleConfig(label='looser_jaccard_0.65', jaccard_threshold=0.65),
    RuleConfig(label='stricter_similarity_0.55', similarity_threshold=0.55),
    RuleConfig(label='looser_similarity_0.35', similarity_threshold=0.35),
    RuleConfig(label='stricter_low_info_esc_3', low_info_escalation_similar_count=3),
    RuleConfig(label='looser_low_info_esc_1', low_info_escalation_similar_count=1),
    RuleConfig(label='wash_threshold_0.01', wash_verdict_threshold=0.01),
    RuleConfig(label='wash_threshold_0.05', wash_verdict_threshold=0.05),
    RuleConfig(label='wash_threshold_0.10', wash_verdict_threshold=0.10),
]


def load_sweep_configs(path: str) -> list:
    """讀取自訂的參數組合清單(JSON 陣列，每個物件是 RuleConfig 的部分欄位，
    缺的欄位取預設值)。"""
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    return [RuleConfig(**item) for item in raw]


def _normalize_csv_row(row):
    """Convert PascalCase CSV row to lowercase keys expected by rule_engine.

    CSV columns: Username, Stars, Time, Text, Label, ...
    rule_engine expects: username, stars, time, text, ...
    Stars is converted from string to int.
    The original row keys are preserved alongside lowercase ones for
    evaluation-specific code that still needs them (e.g. Label).
    """
    return {
        'username': row.get('Username', ''),
        'stars': int(row.get('Stars', 0) or 0),
        'time': row.get('Time', ''),
        'text': row.get('Text', '') or '',
        # Preserve original keys for evaluation access
        '_label': row.get('Label', ''),
        '_raw': row,
    }


def _sort_reviews_newest_first(reviews):
    """Sort reviews by time descending; missing/unparseable dates go last."""
    def _parse_date(r):
        try:
            return datetime.strptime(r.get('time', ''), '%Y-%m-%d')
        except (ValueError, TypeError):
            return datetime.min
    return sorted(reviews, key=_parse_date, reverse=True)


# Default evaluation window — only the newest N reviews are analysed per store.
# Set to match the labelling window (human annotators reviewed ~50-100 recent
# reviews).  Pass --window to override.
DEFAULT_EVAL_WINDOW = 100


def analyze_restaurant(csv_path, config: RuleConfig, window=DEFAULT_EVAL_WINDOW):
    raw_rows = []
    with open(csv_path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            raw_rows.append(row)
    if not raw_rows:
        return None

    # Convert PascalCase CSV rows to lowercase keys for rule_engine
    reviews = [_normalize_csv_row(row) for row in raw_rows]
    reviews = _sort_reviews_newest_first(reviews)
    if window and window > 0:
        reviews = reviews[:window]

    bribe = [has_bribe(r.get('text', '')) for r in reviews]
    tmpl = detect_templates(reviews, config)
    spike_flags, spike_months = detect_spike_months(reviews)
    max_similarity, similar_counts = detect_similarity_signals(reviews, config)
    hot_term_counts, hot_term_max_ratios = detect_hot_term_signals(reviews)
    nearby_long_review_counts = detect_nearby_long_review_counts(reviews)
    low_info_flags, escalated_short_flags = detect_low_info_and_escalated(
        reviews, bribe, spike_flags, similar_counts, config
    )

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
        'max_similarity': max_similarity,
        'similar_counts': similar_counts,
        'hot_term_counts': hot_term_counts,
        'hot_term_max_ratios': hot_term_max_ratios,
        'nearby_long_review_counts': nearby_long_review_counts,
        'low_info_flags': low_info_flags,
        'low_info_count': sum(low_info_flags),
        'low_info_ratio': sum(low_info_flags) / len(reviews),
        'escalated_short_flags': escalated_short_flags,
        'washed_flags': washed,
        'washed_ratio': sum(washed) / len(reviews),
        'total': len(reviews),
    }


def evaluate_dataset(base_path, config: RuleConfig, window=DEFAULT_EVAL_WINDOW):
    base = Path(base_path)
    out = []
    for subdir in sorted(base.iterdir()):
        if not subdir.is_dir() or '__' not in subdir.name:
            continue
        category, label = subdir.name.split('__', 1)
        for csv_file in sorted(subdir.glob('*.csv')):
            a = analyze_restaurant(csv_file, config, window=window)
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


# ─── 參數組合掃描 ───────────────────────────────────────────

def run_param_sweep(base_path, configs, window=DEFAULT_EVAL_WINDOW):
    """對每組 RuleConfig 重新跑一次規則引擎(18 家店)，並以該組指定的
    wash_verdict_threshold 計算混淆矩陣。純本地運算，不呼叫 Gemini。"""
    rows = []
    for config in configs:
        results = evaluate_dataset(base_path, config, window=window)
        if not results:
            continue
        metrics = confusion_matrix(results, config.wash_verdict_threshold)
        avg_low_info = sum(r['low_info_ratio'] for r in results) / len(results)
        rows.append({
            **asdict(config),
            **metrics,
            'avg_low_info_ratio': round(avg_low_info, 3),
            '_results': results,  # kept for downstream use (best-row LLM sampling); stripped before JSON dump
        })
    return rows


def print_sweep_table(rows):
    print('\n' + '=' * 118)
    print('參數組合掃描結果（規則引擎，純本地，未呼叫 Gemini）')
    print('=' * 118)
    print(f"{'label':<28} {'jaccard':<9} {'sim_thr':<9} {'low_info_esc':<13} {'wash_thr':<10} "
          f"{'Prec':<8} {'Rec':<8} {'F1':<8} {'low_info%':<10}")
    print('-' * 118)

    best = max(rows, key=lambda r: r['f1'])
    for row in rows:
        marker = ' ⭐' if row is best else ''
        print(f"{row['label']:<28} {row['jaccard_threshold']:<9.2f} {row['similarity_threshold']:<9.2f} "
              f"{row['low_info_escalation_similar_count']:<13} {row['wash_verdict_threshold']:<10.3f} "
              f"{row['precision']:<8.1%} {row['recall']:<8.1%} {row['f1']:<8.3f} "
              f"{row['avg_low_info_ratio']:<10.1%}{marker}")

    print(f"\n⭐ 最佳組合 = {best['label']} → F1 = {best['f1']}")
    return best


# ─── Stage 2 LLM 抽樣(人工貼給 Claude 模擬) ──────────────────

def sample_for_llm(results, threshold, per_store=8):
    """挑出『有洗但 Stage 1 漏抓』的店家,抽樣評論"""
    missed = [r for r in results
              if r['true_label'] == '有洗'
              and r['washed_ratio'] <= threshold]

    print('\n' + '=' * 70)
    print(f'Stage 2 LLM 抽樣')
    print('=' * 70)
    print(f"找到 {len(missed)} 家「真正有洗但 Stage 1 漏抓」的店家:")

    output = []
    for store in missed:
        five_star = [r for r in store['reviews']
                     if r.get('stars') == 5 and (r.get('text') or '').strip()]
        sample = []
        for r in five_star:
            try:
                dt = datetime.strptime(r['time'], '%Y-%m-%d').date()
                days = (TODAY - dt).days
                month = dt.strftime('%Y-%m')
                text = r['text'].strip()
                sample.append({
                    'username': r.get('username', '?'),
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


# ─── 小樣本 Gemini 測試模式(選用，會實際呼叫 API) ─────────────

def select_llm_sample_stores(results, config: RuleConfig, num_stores=3):
    """挑選用於小樣本 Gemini 測試的店家：優先挑規則引擎判定「最接近門檻」的
    店家(washed_ratio 與 wash_verdict_threshold 相距最近)，因為這些最能反映
    Stage 2 語意複審相對於 Stage 1 的邊際效益，抽樣最有資訊量。"""
    scored = sorted(results, key=lambda r: abs(r['washed_ratio'] - config.wash_verdict_threshold))
    return scored[:num_stores]


def run_llm_sample_mode(base_path, config: RuleConfig, num_stores=3, store_names=None):
    """實際呼叫 Gemini API 對少量店家跑 Stage 2 複審，用來測試 prompt 或訊號
    門檻變體對『真實』Stage 2 判定結果的影響 —— 而不只是規則引擎本身的
    precision/recall。這個模式會產生真實 API 費用與配額消耗，因此僅抽
    {num_stores} 家店（預設 3 家）以控制成本，且必須透過 --llm-sample 明確啟用。

    所有訊號函式（detect_similarity_signals / detect_hot_term_signals /
    detect_nearby_long_review_counts 等）直接從 rule_engine.py 匯入，
    與後端 /api/audit-rules 共用同一份實作。

    需要環境變數 GEMINI_API_KEY（可透過專案根目錄的 .env 設定）。
    """
    repo_root = Path(__file__).resolve().parent.parent

    import os
    try:
        from dotenv import load_dotenv
        load_dotenv(repo_root / '.env')
    except ImportError:
        pass

    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError(
            '缺少 GEMINI_API_KEY 環境變數，無法執行小樣本 Gemini 測試模式。'
            '請在專案根目錄的 .env 檔案中設定 GEMINI_API_KEY（可參考 .env.example）。'
        )

    from google import genai
    from gemini_client import call_gemini_batch

    results = evaluate_dataset(base_path, config)
    if store_names:
        sample_stores = [r for r in results if r['restaurant'] in store_names]
    else:
        sample_stores = select_llm_sample_stores(results, config, num_stores)

    client = genai.Client(api_key=api_key)

    print('\n' + '=' * 70)
    print(f'小樣本 Gemini 測試模式（實際呼叫 API，共 {len(sample_stores)} 家店）')
    print('=' * 70)

    report = []
    for store in sample_stores:
        reviews = store['reviews']
        spike_months = set(store['spike_months'])
        ambiguous = []
        for r, bribe, tmpl, escalated, max_sim, sim_count, hot_count, hot_ratio, nearby_count in zip(
            reviews, store['bribe_flags'], store['template_flags'],
            store['escalated_short_flags'], store['max_similarity'], store['similar_counts'],
            store['hot_term_counts'], store['hot_term_max_ratios'], store['nearby_long_review_counts']
        ):
            if bribe or tmpl or escalated:
                continue
            if r.get('stars') != 5 or not (r.get('text') or '').strip():
                continue
            try:
                dt = datetime.strptime(r['time'], '%Y-%m-%d').date()
                days_elapsed = (TODAY - dt).days
                month = dt.strftime('%Y-%m')
            except (ValueError, KeyError):
                days_elapsed = 0
                month = None
            ambiguous.append({
                'username': r.get('username', '?'),
                'text': r['text'].strip(),
                'stars': 5,
                'daysElapsed': days_elapsed,
                'isSpikePeriod': month in spike_months if month else False,
                'maxSimilarity': round(max_sim, 3),
                'similarCount': sim_count,
                'hotTermCount': hot_count,
                'hotTermMaxRatio': hot_ratio,
                'nearbyLongReviewCount': nearby_count,
            })

        if not ambiguous:
            print(f"  • {store['restaurant']:<20} 無需送審的模糊評論，略過")
            continue

        try:
            items = call_gemini_batch(client, store['restaurant'], ambiguous)
        except Exception as e:
            print(f"  ✗ {store['restaurant']:<20} Gemini 呼叫失敗：{e}")
            continue

        washed_from_llm = sum(1 for item in items if item.get('isWashed'))
        print(f"  • {store['restaurant']:<20} (真實標籤={store['true_label']}) "
              f"送審 {len(ambiguous)} 則 → Gemini 判洗評 {washed_from_llm} 則")
        report.append({
            'store_name': store['restaurant'],
            'true_label': store['true_label'],
            'stage1_washed_ratio': round(store['washed_ratio'], 3),
            'sent_to_gemini': len(ambiguous),
            'gemini_washed_count': washed_from_llm,
            'gemini_items': items,
        })

    return report


# ─── main ───────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description='TrueRating QA 進階評估腳本 v2 — 支援參數掃描')
    parser.add_argument('data_path', help='restaurant_data 路徑')
    parser.add_argument('--window', type=int, default=DEFAULT_EVAL_WINDOW,
                        help=f'每家店只取最新 N 則評論 (預設 {DEFAULT_EVAL_WINDOW})')
    parser.add_argument('--sweep-config', help='自訂參數組合清單的 JSON 檔案路徑（覆寫內建 DEFAULT_SWEEP）')
    parser.add_argument('--llm-sample', type=int, metavar='N', default=None,
                         help='啟用小樣本 Gemini 測試模式，抽 N 家店實際呼叫 API（會產生真實費用，需要 GEMINI_API_KEY）')
    parser.add_argument('--llm-sample-stores', help='小樣本模式要測試的店家名稱清單，逗號分隔（覆寫自動挑選）')
    return parser.parse_args()


def main():
    args = parse_args()
    base = args.data_path

    configs = load_sweep_configs(args.sweep_config) if args.sweep_config else DEFAULT_SWEEP

    rows = run_param_sweep(base, configs, window=args.window)
    if not rows:
        print(f'錯誤:在 {base} 找不到資料。')
        sys.exit(1)

    print(f'[資料集] 共 {len(rows[0]["_results"])} 家店，掃描 {len(rows)} 組參數組合')

    best_row = print_sweep_table(rows)
    best_config = RuleConfig(**{k: v for k, v in best_row.items() if k in RuleConfig.__dataclass_fields__})
    best_results = best_row['_results']

    llm_input = sample_for_llm(best_results, best_config.wash_verdict_threshold)

    # 輸出(移除 _results，避免把整份規則計算中間結果都塞進 JSON)
    out_dir = Path('.').resolve()
    tune_output = [{k: v for k, v in row.items() if k != '_results'} for row in rows]
    (out_dir / 'tune_results.json').write_text(
        json.dumps({'best_label': best_config.label, 'sweep': tune_output}, ensure_ascii=False, indent=2),
        encoding='utf-8')
    (out_dir / 'llm_input.json').write_text(
        json.dumps(llm_input, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\n' + '=' * 70)
    print('已輸出檔案:')
    print('=' * 70)
    print(f"  📊 tune_results.json   (參數掃描結果)")
    print(f"  🤖 llm_input.json      ← 把這個整份內容貼給 Claude!")
    print()
    print("下一步:")
    print("  1. 把 llm_input.json 內容整份複製貼給 Claude")
    print("  2. Claude 會扮演 Gemini 跑 Stage 2 LLM 模擬分析")
    print("  3. 拿到 Stage 1 + Stage 2 整合後的最終 F1")

    if args.llm_sample is not None:
        store_names = args.llm_sample_stores.split(',') if args.llm_sample_stores else None
        run_llm_sample_mode(base, best_config, num_stores=args.llm_sample, store_names=store_names)


if __name__ == '__main__':
    main()
