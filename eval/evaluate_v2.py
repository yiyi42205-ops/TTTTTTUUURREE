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
  python3 eval/evaluate_v2.py restaurant_data [--window N] [--offset M]
  --window N  只取每家店最新 N 則評論(預設 100),避免評估吃到未標註的舊評論
  --offset M  跳過最新 M 則評論再取 window（滑動窗口到歷史區間）

  # 用自訂的參數組合清單（JSON 陣列，每個物件是 RuleConfig 的部分欄位）覆寫預設清單
  python3 evaluate_v2.py restaurant_data --sweep-config my_configs.json

  # 切 4 家 holdout 店，sweep 只在 train 上跑，best config 再到 holdout 上驗證
  python3 evaluate_v2.py restaurant_data --holdout 4

  # 指定 holdout 店家（逗號分隔，覆寫隨機挑選）
  python3 evaluate_v2.py restaurant_data --holdout 4 --holdout-stores "店A,店B,店C,店D"

  # 小樣本 Gemini 測試模式：實際呼叫 API，僅抽 3 家店（需要 .env 內的 GEMINI_API_KEY）
  python3 evaluate_v2.py restaurant_data --llm-sample 3

產出:
  - tune_results.json    參數掃描完整結果（含 holdout 驗證結果）
  - llm_input.json       給 Claude 跑 Stage 2 模擬的抽樣(把整份貼給 Claude)
"""
import argparse
import csv
import json
import os
import random
import sys
from dataclasses import asdict
from datetime import datetime, date
from pathlib import Path

# Allow importing from review_scraper/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from rule_engine import RuleConfig, run_stage1_audit

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


def _safe_int_stars(val):
    try:
        return int(float(val or 0))
    except (ValueError, TypeError):
        return 0


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
        'stars': _safe_int_stars(row.get('Stars')),
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


def analyze_restaurant(csv_path, config: RuleConfig, window: int = DEFAULT_EVAL_WINDOW, offset: int = 0):
    raw_rows = []
    with open(csv_path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            raw_rows.append(row)
    if not raw_rows:
        return None

    # Convert PascalCase CSV rows to lowercase keys for rule_engine
    reviews = [_normalize_csv_row(row) for row in raw_rows]
    reviews = _sort_reviews_newest_first(reviews)
    # offset: skip the newest M reviews before taking the window
    if offset and offset > 0:
        reviews = reviews[offset:]
    if window and window > 0:
        reviews = reviews[:window]
    if not reviews:
        return None

    # Delegate all Stage 1 logic to run_stage1_audit — the same function
    # that powers POST /api/audit-rules.  No more manual orchestration.
    result = run_stage1_audit(reviews, config)
    audited_reviews = result['auditedReviews']
    signals = result['signals']

    washed_flags = [r['audit']['isWashed'] for r in audited_reviews]
    low_info_flags = [r['audit']['issueType'] == 'low_info' for r in audited_reviews]

    return {
        'reviews': reviews,
        'audited_reviews': audited_reviews,
        'signals': signals,
        'spike_months': signals['spikeMonths'],
        'washed_flags': washed_flags,
        'washed_ratio': sum(washed_flags) / len(reviews),
        'low_info_flags': low_info_flags,
        'low_info_count': sum(low_info_flags),
        'low_info_ratio': sum(low_info_flags) / len(reviews),
        'total': len(reviews),
    }


def evaluate_dataset(base_path, config: RuleConfig, window: int = DEFAULT_EVAL_WINDOW, offset: int = 0):
    base = Path(base_path)
    out = []
    for subdir in sorted(base.iterdir()):
        if not subdir.is_dir() or '__' not in subdir.name:
            continue
        category, label = subdir.name.split('__', 1)
        for csv_file in sorted(subdir.glob('*.csv')):
            a = analyze_restaurant(csv_file, config, window=window, offset=offset)
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


# ─── Holdout 分割 ──────────────────────────────────────────

def stratified_holdout_split(results, n_holdout, seed=42, store_names=None):
    """Split results into (train, holdout) stratified by true_label.

    If store_names is provided, those stores are used as holdout directly
    (ignoring n_holdout and seed). Otherwise, n_holdout stores are randomly
    selected with proportional representation of 有洗/沒洗."""
    if store_names:
        name_set = set(store_names)
        holdout = [r for r in results if r['restaurant'] in name_set]
        train = [r for r in results if r['restaurant'] not in name_set]
        missing = name_set - {r['restaurant'] for r in holdout}
        if missing:
            print(f"⚠️  找不到指定的 holdout 店家: {', '.join(sorted(missing))}", file=sys.stderr)
        return train, holdout

    if n_holdout <= 0 or n_holdout >= len(results):
        return results, []

    washed = [r for r in results if r['true_label'] == '有洗']
    clean = [r for r in results if r['true_label'] == '沒洗']

    rng = random.Random(seed)
    rng.shuffle(washed)
    rng.shuffle(clean)

    # Proportional split: round to nearest int per class
    n_washed = round(n_holdout * len(washed) / len(results))
    n_clean = n_holdout - n_washed

    holdout = washed[:n_washed] + clean[:n_clean]
    train = washed[n_washed:] + clean[n_clean:]
    return train, holdout


# ─── 參數組合掃描 ───────────────────────────────────────────

def run_param_sweep(base_path, configs, window: int = DEFAULT_EVAL_WINDOW, offset: int = 0):
    """對每組 RuleConfig 重新跑一次規則引擎，並以該組指定的
    wash_verdict_threshold 計算混淆矩陣。純本地運算，不呼叫 Gemini。"""
    rows = []
    for config in configs:
        results = evaluate_dataset(base_path, config, window=window, offset=offset)
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


def run_param_sweep_with_holdout(base_path, configs, n_holdout, window: int = DEFAULT_EVAL_WINDOW,
                                  seed=42, holdout_store_names=None, offset: int = 0):
    """Run sweep on train split, then evaluate best config on holdout split.
    Returns (train_rows, holdout_metrics, train_stores, holdout_stores)."""
    # Use first config to get full results for splitting
    all_results = evaluate_dataset(base_path, configs[0], window=window, offset=offset)
    if not all_results:
        return [], None, [], []

    train_results, holdout_results = stratified_holdout_split(
        all_results, n_holdout, seed=seed, store_names=holdout_store_names)

    train_names = {r['restaurant'] for r in train_results}
    holdout_names = {r['restaurant'] for r in holdout_results}

    # Sweep on train set only
    train_rows = []
    for config in configs:
        results = evaluate_dataset(base_path, config, window=window, offset=offset)
        if not results:
            continue
        train_only = [r for r in results if r['restaurant'] in train_names]
        metrics = confusion_matrix(train_only, config.wash_verdict_threshold)
        avg_low_info = sum(r['low_info_ratio'] for r in train_only) / len(train_only) if train_only else 0
        train_rows.append({
            **asdict(config),
            **metrics,
            'avg_low_info_ratio': round(avg_low_info, 3),
            '_results': train_only,
        })

    if not train_rows:
        return [], None, [], []

    # Find best config from train
    best_train = max(train_rows, key=lambda r: r['f1'])
    best_config = RuleConfig(**{k: v for k, v in best_train.items() if k in RuleConfig.__dataclass_fields__})

    # Evaluate best config on holdout
    holdout_eval = evaluate_dataset(base_path, best_config, window=window, offset=offset)
    holdout_only = [r for r in holdout_eval if r['restaurant'] in holdout_names]
    holdout_metrics = confusion_matrix(holdout_only, best_config.wash_verdict_threshold)
    holdout_avg_low_info = sum(r['low_info_ratio'] for r in holdout_only) / len(holdout_only) if holdout_only else 0
    holdout_metrics['avg_low_info_ratio'] = round(holdout_avg_low_info, 3)
    holdout_metrics['config_label'] = best_config.label

    train_store_info = [(r['restaurant'], r['true_label']) for r in train_results]
    holdout_store_info = [(r['restaurant'], r['true_label']) for r in holdout_results]

    return train_rows, holdout_metrics, train_store_info, holdout_store_info


def print_sweep_table(rows, title='參數組合掃描結果（規則引擎，純本地，未呼叫 Gemini）'):
    print('\n' + '=' * 118)
    print(title)
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


def print_holdout_result(holdout_metrics, train_store_info, holdout_store_info):
    """Print holdout split details and validation result."""
    print('\n' + '=' * 118)
    print('Holdout 分割')
    print('=' * 118)

    n_train_washed = sum(1 for _, label in train_store_info if label == '有洗')
    n_train_clean = len(train_store_info) - n_train_washed
    n_holdout_washed = sum(1 for _, label in holdout_store_info if label == '有洗')
    n_holdout_clean = len(holdout_store_info) - n_holdout_washed

    print(f"Train: {len(train_store_info)} 家 ({n_train_washed} 有洗 / {n_train_clean} 沒洗)")
    for name, label in sorted(train_store_info):
        print(f"  {'🔴' if label == '有洗' else '🟢'} {name}")

    print(f"\nHoldout: {len(holdout_store_info)} 家 ({n_holdout_washed} 有洗 / {n_holdout_clean} 沒洗)")
    for name, label in sorted(holdout_store_info):
        print(f"  {'🔴' if label == '有洗' else '🟢'} {name}")

    print(f"\n{'─' * 70}")
    print(f"Holdout 驗證（使用 train 最佳組合: {holdout_metrics['config_label']}）")
    print(f"{'─' * 70}")
    m = holdout_metrics
    print(f"  TP={m['TP']}  FN={m['FN']}  FP={m['FP']}  TN={m['TN']}")
    print(f"  Precision={m['precision']:.1%}  Recall={m['recall']:.1%}  F1={m['f1']:.3f}")
    print(f"  low_info%={m['avg_low_info_ratio']:.1%}")


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


def run_llm_sample_mode(base_path: str, config: RuleConfig, num_stores: int = 5, store_names: list[str] | None = None, provider: str = 'gemini') -> list[dict]:
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

    from google import genai
    from llm_client import call_llm_batch

    if provider == 'gemini':
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('缺少 GEMINI_API_KEY 環境變數。請在專案根目錄的 .env 檔案中設定。')
        client = genai.Client(api_key=api_key)
    elif provider == 'deepseek':
        import openai
        api_key = os.getenv('DEEPSEEK_API_KEY')
        if not api_key:
            raise RuntimeError('缺少 DEEPSEEK_API_KEY 環境變數。請在專案根目錄的 .env 檔案中設定。')
        client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    else:
        raise ValueError(f"Unknown provider: {provider}")

    results = evaluate_dataset(base_path, config)
    if store_names:
        sample_stores = [r for r in results if r['restaurant'] in store_names]
    else:
        sample_stores = select_llm_sample_stores(results, config, num_stores)
    print('\n' + '=' * 70)
    print(f'小樣本 {provider.capitalize()} 測試模式（實際呼叫 API，共 {len(sample_stores)} 家店）')
    print('=' * 70)

    report = []
    for store in sample_stores:
        reviews = store['reviews']
        audited_reviews = store['audited_reviews']
        signals = store['signals']
        spike_months = set(store['spike_months'])
        ambiguous = []
        for i, r in enumerate(reviews):
            # Skip reviews already caught by Stage 1
            if audited_reviews[i]['audit']['isWashed']:
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
            sim = signals['similarity'][i]
            hot = signals['hotTerm'][i]
            ambiguous.append({
                'username': r.get('username', '?'),
                'text': r['text'].strip(),
                'stars': 5,
                'daysElapsed': days_elapsed,
                'isSpikePeriod': month in spike_months if month else False,
                'maxSimilarity': round(sim['maxSimilarity'], 3),
                'similarCount': sim['similarCount'],
                'hotTermCount': hot['hotTermCount'],
                'hotTermMaxRatio': hot['hotTermMaxRatio'],
                'nearbyLongReviewCount': signals['nearbyLongReviewCounts'][i],
            })

        if not ambiguous:
            print(f"  • {store['restaurant']:<20} 無需送審的模糊評論，略過")
            continue

        try:
            items = call_llm_batch(provider, client, store['restaurant'], ambiguous)
        except Exception as e:
            print(f"  ✗ {store['restaurant']:<20} LLM 呼叫失敗：{e}")
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
    parser.add_argument('--offset', type=int, default=0,
                        help='跳過最新 M 則評論再取 window（用於滑動窗口到歷史區間）')
    parser.add_argument('--sweep-config', help='自訂參數組合清單的 JSON 檔案路徑（覆寫內建 DEFAULT_SWEEP）')
    parser.add_argument('--holdout', type=int, default=0, metavar='N',
                        help='切 N 家店為 holdout，sweep 只在 train 上跑，best config 再到 holdout 上驗證')
    parser.add_argument('--holdout-seed', type=int, default=42,
                        help='holdout 隨機分割的 seed（預設 42，確保可重現）')
    parser.add_argument('--holdout-stores', help='指定 holdout 店家名稱，逗號分隔（覆寫隨機挑選）')
    parser.add_argument('--llm-sample', type=int, metavar='N', default=None,
                         help='啟用小樣本 LLM 測試模式，抽 N 家店實際呼叫 API（會產生真實費用）')
    parser.add_argument('--llm-sample-stores', help='小樣本模式要測試的店家名稱清單，逗號分隔（覆寫自動挑選）')
    parser.add_argument('--llm-provider', choices=['gemini', 'deepseek'], default='gemini',
                         help='要測試的模型提供者 (預設 gemini)')
    return parser.parse_args()


def main():
    args = parse_args()
    print(f"\n[INFO] Evaluating with window={args.window}, offset={args.offset}\n")
    base = args.data_path

    configs = load_sweep_configs(args.sweep_config) if args.sweep_config else DEFAULT_SWEEP

    holdout_store_names = args.holdout_stores.split(',') if args.holdout_stores else None

    if args.holdout > 0 or holdout_store_names:
        n_holdout = len(holdout_store_names) if holdout_store_names else args.holdout
        train_rows, holdout_metrics, train_store_info, holdout_store_info = \
            run_param_sweep_with_holdout(
                base, configs, n_holdout, window=args.window,
                seed=args.holdout_seed, holdout_store_names=holdout_store_names,
                offset=args.offset)

        if not train_rows:
            print(f'錯誤:在 {base} 找不到資料。')
            sys.exit(1)

        n_train = len(train_store_info)
        n_holdout_actual = len(holdout_store_info)
        print(f'[資料集] 共 {n_train + n_holdout_actual} 家店 '
              f'(train {n_train} / holdout {n_holdout_actual})，'
              f'掃描 {len(train_rows)} 組參數組合')

        best_row = print_sweep_table(
            train_rows, title=f'參數組合掃描結果 — Train set（{n_train} 家店）')
        best_config = RuleConfig(**{k: v for k, v in best_row.items() if k in RuleConfig.__dataclass_fields__})
        best_results = best_row['_results']

        print_holdout_result(holdout_metrics, train_store_info, holdout_store_info)

        llm_input = sample_for_llm(best_results, best_config.wash_verdict_threshold)

        # Output JSON
        out_dir = Path('.').resolve()
        tune_output = [{k: v for k, v in row.items() if k != '_results'} for row in train_rows]
        output_data = {
            'best_label': best_config.label,
            'sweep': tune_output,
            'holdout': {
                'seed': args.holdout_seed,
                'stores': [{'name': n, 'label': l} for n, l in holdout_store_info],
                **holdout_metrics,
            },
        }
        (out_dir / 'tune_results.json').write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2), encoding='utf-8')
        (out_dir / 'llm_input.json').write_text(
            json.dumps(llm_input, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        rows = run_param_sweep(base, configs, window=args.window, offset=args.offset)
        if not rows:
            print(f'錯誤:在 {base} 找不到資料。')
            sys.exit(1)

        print(f'[資料集] 共 {len(rows[0]["_results"])} 家店，掃描 {len(rows)} 組參數組合')

        best_row = print_sweep_table(rows)
        best_config = RuleConfig(**{k: v for k, v in best_row.items() if k in RuleConfig.__dataclass_fields__})
        best_results = best_row['_results']

        llm_input = sample_for_llm(best_results, best_config.wash_verdict_threshold)

        # Output JSON
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
        run_llm_sample_mode(base, best_config, num_stores=args.llm_sample, store_names=store_names, provider=args.llm_provider)


if __name__ == '__main__':
    main()
