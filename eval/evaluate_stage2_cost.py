#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stage 2 成本評估腳本 (Issue #69)
================================

從 audit_cache 中分層抽樣 50 家店，模擬 production mode 的 Stage 2 流程
（15 則上限 + spike/normal 分層抽樣），實際呼叫 Gemini 評估 Stage 2 相對
於 Stage 1 的邊際偵測能力和 API 成本。

用法:
  # 乾跑模式（不呼叫 API，只估算成本和抽樣統計）
  python eval/evaluate_stage2_cost.py

  # 實際呼叫 Gemini API（需 .env 中的 GEMINI_API_KEY）
  python eval/evaluate_stage2_cost.py --run

  # 指定抽樣數量 / 提供者
  python eval/evaluate_stage2_cost.py --stores 30 --run
  python eval/evaluate_stage2_cost.py --run --provider deepseek

產出:
  eval/stage2_cost_report.json — 完整報告（抽樣明細、成本估算、Stage 1 vs 2 比較）
"""
import argparse
import json
import math
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, date
from pathlib import Path

# Allow importing from review_scraper/
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / 'review_scraper'))

from rule_engine import RuleConfig, run_stage1_audit

TODAY = date.today()
STAGE2_CAP = 15

# Gemini 2.5 Flash pricing (USD per 1M tokens, non-thinking mode)
GEMINI_INPUT_PRICE = 0.15    # $0.15 / 1M input tokens
GEMINI_OUTPUT_PRICE = 0.60   # $0.60 / 1M output tokens
PROMPT_TEMPLATE_CHARS = 15_000  # audit_prompt.txt ~15KB
CHARS_PER_TOKEN = 3.5  # rough CJK estimate


# ─── Data loading ──────────────────────────────────────────

def _extract_store_name(url: str) -> str:
    """Extract a human-readable store name from an audit_cache URL key."""
    from urllib.parse import unquote
    decoded = unquote(url).replace('+', ' ')
    # Format 1 (majority): /maps/search/?api=1&query=<name>&query_place_id=ChIJ...
    m = re.search(r'[?&]query=([^&]+)', decoded)
    if m:
        return m.group(1).strip()
    # Format 2: maps?q=<address+name>
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


def load_all_stores_from_cache(db_path: str) -> list[dict]:
    """Load all stores from audit_cache, returning enriched dicts."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT place_id, audit_json FROM audit_cache")

    stores = []
    for place_id, audit_json in cursor:
        audit_data = json.loads(audit_json)
        audited = audit_data.get('auditedReviews', [])
        signals = audit_data.get('signals', {})

        if not audited:
            continue

        n_total = len(audited)
        n_washed = sum(1 for r in audited if r.get('audit', {}).get('isWashed'))
        n_null = sum(1 for r in audited if r.get('audit', {}).get('issueType') is None)
        wash_rate = n_washed / n_total if n_total else 0

        store_name = _extract_store_name(place_id)

        stores.append({
            'place_id': place_id,
            'store_name': store_name,
            'n_total': n_total,
            'n_washed': n_washed,
            'n_null': n_null,
            'wash_rate': wash_rate,
            'audited_reviews': audited,
            'signals': signals,
        })

    conn.close()
    return stores


# ─── Stratified sampling (mirrors Results.tsx logic) ───────

def stratified_store_sample(stores: list[dict], n: int, seed: int = 42) -> list[dict]:
    """Sample n stores stratified by wash rate quartile."""
    rng = random.Random(seed)
    sorted_stores = sorted(stores, key=lambda s: s['wash_rate'])
    n_stores = len(sorted_stores)

    # 4 strata: low (0-25%), mid-low (25-50%), mid-high (50-75%), high (75-100%)
    strata = []
    for i in range(4):
        start = i * n_stores // 4
        end = (i + 1) * n_stores // 4
        strata.append(sorted_stores[start:end])

    per_stratum = n // 4
    remainder = n % 4
    sampled = []
    for i, stratum in enumerate(strata):
        k = per_stratum + (1 if i < remainder else 0)
        k = min(k, len(stratum))
        sampled.extend(rng.sample(stratum, k))

    return sampled


def stage2_stratified_review_sample(audited_reviews: list[dict], signals: dict, cap: int = STAGE2_CAP) -> list[dict]:
    """Replicate the frontend's stratified sampling of ambiguous reviews.

    Mirrors Results.tsx lines 255-293: split ambiguous reviews into spike vs
    normal pools, proportionally allocate the cap, then evenly space within
    each pool for temporal spread.
    """
    spike_months = set(signals.get('spikeMonths', []))

    # Collect ambiguous reviews with their signal context
    ambiguous = []
    for i, r in enumerate(audited_reviews):
        audit = r.get('audit', {})
        if audit.get('issueType') is not None:
            continue  # Stage 1-final — skip
        if r.get('stars') != 5:
            continue  # Only 5-star reviews go to Stage 2
        if not (r.get('text') or '').strip():
            continue  # Need text for LLM

        try:
            dt = datetime.strptime(r['time'], '%Y-%m-%d').date()
            days_elapsed = (TODAY - dt).days
            month = dt.strftime('%Y-%m')
        except (ValueError, KeyError):
            days_elapsed = 0
            month = None

        sim = signals['similarity'][i] if i < len(signals.get('similarity', [])) else {}
        hot = signals['hotTerm'][i] if i < len(signals.get('hotTerm', [])) else {}
        nearby = signals.get('nearbyLongReviewCounts', [])
        nearby_count = nearby[i] if i < len(nearby) else 0

        ambiguous.append({
            'username': r.get('username', '?'),
            'text': r['text'].strip(),
            'stars': 5,
            'daysElapsed': days_elapsed,
            'isSpikePeriod': month in spike_months if month else False,
            'maxSimilarity': round(sim.get('maxSimilarity', 0), 3),
            'similarCount': sim.get('similarCount', 0),
            'hotTermCount': hot.get('hotTermCount', 0),
            'hotTermMaxRatio': hot.get('hotTermMaxRatio', 0),
            'nearbyLongReviewCount': nearby_count,
            '_index': i,
        })

    if len(ambiguous) <= cap:
        return ambiguous

    # Split by spike period
    spike_pool = [r for r in ambiguous if r['isSpikePeriod']]
    normal_pool = [r for r in ambiguous if not r['isSpikePeriod']]

    spike_ratio = len(spike_pool) / len(ambiguous) if ambiguous else 0
    spike_count = round(cap * spike_ratio)
    normal_count = cap - spike_count

    def even_sample(pool, n):
        if n >= len(pool):
            return pool
        step = len(pool) / n
        return [pool[int(i * step)] for i in range(n)]

    sampled = (
        even_sample(spike_pool, min(spike_count, len(spike_pool)))
        + even_sample(normal_pool, min(normal_count, len(normal_pool)))
    )
    return sampled


# ─── Token estimation ─────────────────────────────────────

def estimate_tokens(n_reviews: int) -> dict:
    """Estimate input/output tokens for a batch of reviews."""
    # Input: prompt template + review payload
    avg_review_chars = 200  # average CJK review payload per review
    input_chars = PROMPT_TEMPLATE_CHARS + n_reviews * avg_review_chars
    input_tokens = int(input_chars / CHARS_PER_TOKEN)

    # Output: ~80 tokens per review (verdict JSON fields)
    output_tokens = n_reviews * 80

    input_cost = input_tokens * GEMINI_INPUT_PRICE / 1_000_000
    output_cost = output_tokens * GEMINI_OUTPUT_PRICE / 1_000_000

    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'input_cost_usd': input_cost,
        'output_cost_usd': output_cost,
        'total_cost_usd': input_cost + output_cost,
    }


# ─── Live Gemini execution ────────────────────────────────

def run_stage2_on_store(provider: str, client, store_name: str, reviews: list[dict]) -> list[dict]:
    """Call the LLM on a batch of reviews, return per-review verdicts."""
    from llm_client import call_llm_batch
    # Clean internal fields before sending
    clean = [{k: v for k, v in r.items() if not k.startswith('_')} for r in reviews]
    return call_llm_batch(provider, client, store_name, clean)


def init_llm_client(provider: str):
    """Initialize the LLM client from .env credentials."""
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / '.env')
    except ImportError:
        pass

    if provider == 'gemini':
        from google import genai
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('缺少 GEMINI_API_KEY。請在 .env 中設定。')
        return genai.Client(api_key=api_key)
    elif provider == 'deepseek':
        import openai
        api_key = os.getenv('DEEPSEEK_API_KEY')
        if not api_key:
            raise RuntimeError('缺少 DEEPSEEK_API_KEY。請在 .env 中設定。')
        return openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ─── Main ─────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description='Stage 2 成本評估 (Issue #69)')
    parser.add_argument('--stores', type=int, default=50,
                        help='抽樣店數 (預設 50)')
    parser.add_argument('--seed', type=int, default=42,
                        help='隨機種子 (預設 42)')
    parser.add_argument('--run', action='store_true',
                        help='實際呼叫 Gemini API（預設為乾跑模式）')
    parser.add_argument('--provider', choices=['gemini', 'deepseek'], default='gemini',
                        help='LLM 提供者 (預設 gemini)')
    parser.add_argument('--db', default=str(REPO_ROOT / 'cache.db'),
                        help='cache.db 路徑')
    return parser.parse_args()


def main():
    args = parse_args()

    print(f'\n{"=" * 70}')
    print(f'Stage 2 成本評估 (Issue #69)')
    print(f'{"=" * 70}')
    print(f'模式: {"🔴 LIVE（會呼叫 API）" if args.run else "🟢 乾跑（只估算）"}')
    print(f'抽樣: {args.stores} 家店, seed={args.seed}')

    # Load data
    print(f'\n載入 cache.db ...')
    stores = load_all_stores_from_cache(args.db)
    print(f'  共 {len(stores)} 家店有 audit 資料')

    # Stratified sample
    sampled = stratified_store_sample(stores, args.stores, seed=args.seed)
    print(f'  分層抽樣 {len(sampled)} 家')

    # For each sampled store, apply production sampling
    print(f'\n{"=" * 70}')
    print(f'各店 Stage 2 候選評論統計')
    print(f'{"=" * 70}')
    print(f'{"店名":<30} {"總評論":>6} {"S1洗":>5} {"候選":>5} {"抽樣":>5} {"洗率":>6}')
    print(f'{"-" * 70}')

    total_sampled_reviews = 0
    total_all_ambiguous = 0
    store_results = []

    for store in sampled:
        sampled_reviews = stage2_stratified_review_sample(
            store['audited_reviews'], store['signals'])

        total_sampled_reviews += len(sampled_reviews)
        total_all_ambiguous += store['n_null']

        store_results.append({
            'place_id': store['place_id'],
            'store_name': store['store_name'],
            'n_total': store['n_total'],
            'n_washed_s1': store['n_washed'],
            'n_ambiguous': store['n_null'],
            'n_sampled': len(sampled_reviews),
            'wash_rate_s1': round(store['wash_rate'], 4),
            'sampled_reviews': sampled_reviews,
        })

        name = store['store_name'][:28]
        print(f'{name:<30} {store["n_total"]:>6} {store["n_washed"]:>5} '
              f'{store["n_null"]:>5} {len(sampled_reviews):>5} '
              f'{store["wash_rate"]:>5.1%}')

    # Cost estimation
    print(f'\n{"=" * 70}')
    print(f'成本估算')
    print(f'{"=" * 70}')

    sample_cost = estimate_tokens(total_sampled_reviews)
    print(f'  抽樣 {len(sampled)} 家店 × ≤{STAGE2_CAP} 則/店 = {total_sampled_reviews} 則')
    print(f'  預估 input tokens:  {sample_cost["input_tokens"]:>8,}')
    print(f'  預估 output tokens: {sample_cost["output_tokens"]:>8,}')
    print(f'  預估成本: ${sample_cost["total_cost_usd"]:.4f}')

    # Extrapolate to all 1421 stores
    avg_sampled_per_store = total_sampled_reviews / len(sampled) if sampled else 0
    all_store_reviews = avg_sampled_per_store * len(stores)
    all_cost = estimate_tokens(int(all_store_reviews))
    per_query_cost = estimate_tokens(int(avg_sampled_per_store))

    print(f'\n  --- 外推到全部 {len(stores)} 家店 ---')
    print(f'  每店平均送審: {avg_sampled_per_store:.1f} 則')
    print(f'  全量 input tokens:  {all_cost["input_tokens"]:>10,}')
    print(f'  全量 output tokens: {all_cost["output_tokens"]:>10,}')
    print(f'  全量成本: ${all_cost["total_cost_usd"]:.4f}')
    print(f'  每次查詢成本: ${per_query_cost["total_cost_usd"]:.6f}')

    # Live mode — call Gemini
    live_results = []
    if args.run:
        print(f'\n{"=" * 70}')
        print(f'Stage 2 LLM 執行')
        print(f'{"=" * 70}')

        client = init_llm_client(args.provider)
        total_s2_washed = 0
        total_s2_sent = 0

        for i, sr in enumerate(store_results):
            reviews = sr['sampled_reviews']
            if not reviews:
                print(f'  [{i+1}/{len(store_results)}] {sr["store_name"][:25]:<28} 無候選評論，略過')
                continue

            print(f'  [{i+1}/{len(store_results)}] {sr["store_name"][:25]:<28} '
                  f'送審 {len(reviews)} 則 ...', end=' ', flush=True)

            try:
                verdicts = run_stage2_on_store(
                    args.provider, client, sr['store_name'], reviews)
                n_s2_washed = sum(1 for v in verdicts if v.get('isWashed'))
                total_s2_washed += n_s2_washed
                total_s2_sent += len(reviews)

                print(f'→ S2 判洗 {n_s2_washed}/{len(reviews)}')

                live_results.append({
                    'place_id': sr['place_id'],
                    'store_name': sr['store_name'],
                    'wash_rate_s1': sr['wash_rate_s1'],
                    'n_washed_s1': sr['n_washed_s1'],
                    'n_sent_s2': len(reviews),
                    'n_washed_s2': n_s2_washed,
                    'verdicts': verdicts,
                })

                # Rate limit courtesy
                time.sleep(0.5)

            except Exception as e:
                print(f'✗ 失敗: {e}')
                live_results.append({
                    'place_id': sr['place_id'],
                    'store_name': sr['store_name'],
                    'error': str(e),
                })

        # Summary
        print(f'\n{"=" * 70}')
        print(f'Stage 1 vs Stage 2 比較')
        print(f'{"=" * 70}')

        successful = [r for r in live_results if 'verdicts' in r]
        if successful:
            total_s1_washed = sum(r['n_washed_s1'] for r in successful)
            total_reviews_in_sample = sum(
                sr['n_total'] for sr in store_results
                if sr['place_id'] in {r['place_id'] for r in successful})

            print(f'  成功評估: {len(successful)}/{len(store_results)} 家店')
            print(f'  Stage 1 已攔截: {total_s1_washed} 則 ({total_s1_washed/total_reviews_in_sample:.1%})')
            print(f'  Stage 2 送審: {total_s2_sent} 則')
            print(f'  Stage 2 新增偵測: {total_s2_washed} 則 ({total_s2_washed/total_s2_sent:.1%} of sent)')

            # Marginal value
            combined = total_s1_washed + total_s2_washed
            print(f'  Stage 1+2 合計: {combined} 則 ({combined/total_reviews_in_sample:.1%})')
            s2_marginal = total_s2_washed / combined * 100 if combined else 0
            print(f'  Stage 2 邊際貢獻: {s2_marginal:.1f}% of all detected')

            # Per-store breakdown
            print(f'\n  {"店名":<25} {"S1洗":>5} {"S2送":>5} {"S2洗":>5} {"邊際":>6}')
            print(f'  {"-" * 55}')
            for r in sorted(successful, key=lambda x: x['n_washed_s2'], reverse=True):
                s2_pct = f"{r['n_washed_s2']/r['n_sent_s2']:.0%}" if r['n_sent_s2'] else '—'
                print(f'  {r["store_name"][:23]:<25} {r["n_washed_s1"]:>5} '
                      f'{r["n_sent_s2"]:>5} {r["n_washed_s2"]:>5} {s2_pct:>6}')

    # Output report
    report = {
        'run_date': str(TODAY),
        'mode': 'live' if args.run else 'dry_run',
        'n_stores_total': len(stores),
        'n_stores_sampled': len(sampled),
        'seed': args.seed,
        'stage2_cap': STAGE2_CAP,
        'total_sampled_reviews': total_sampled_reviews,
        'total_all_ambiguous_in_sample': total_all_ambiguous,
        'cost_estimate': {
            'sample': sample_cost,
            'extrapolated_all_stores': all_cost,
            'per_query': per_query_cost,
        },
        'store_summary': [
            {k: v for k, v in sr.items() if k != 'sampled_reviews'}
            for sr in store_results
        ],
    }
    if args.run and live_results:
        # Strip verbose verdict details for the summary, keep them in a separate key
        report['live_results'] = [
            {k: v for k, v in r.items() if k != 'verdicts'}
            for r in live_results
        ]
        report['live_verdicts'] = [
            {'place_id': r['place_id'], 'verdicts': r.get('verdicts', [])}
            for r in live_results if 'verdicts' in r
        ]

        successful = [r for r in live_results if 'verdicts' in r]
        if successful:
            total_s1 = sum(r['n_washed_s1'] for r in successful)
            total_s2 = sum(r['n_washed_s2'] for r in successful)
            total_sent = sum(r['n_sent_s2'] for r in successful)
            report['conclusion'] = {
                'stores_evaluated': len(successful),
                'total_s1_washed': total_s1,
                'total_s2_sent': total_sent,
                'total_s2_new_washed': total_s2,
                's2_detection_rate': round(total_s2 / total_sent, 4) if total_sent else 0,
                's2_marginal_contribution': round(total_s2 / (total_s1 + total_s2), 4) if (total_s1 + total_s2) else 0,
            }

    out_path = REPO_ROOT / 'eval' / 'stage2_cost_report.json'
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n已輸出: {out_path}')


if __name__ == '__main__':
    main()
