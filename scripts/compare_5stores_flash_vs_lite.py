#!/usr/bin/env python3 -u
"""
Phase 1: Cache Stage 1 results + stratified sample 40 ambiguous reviews per store.
Phase 2: Send to Flash + Flash-Lite, compare.

Usage:
  review_scraper/venv/bin/python scripts/compare_5stores_flash_vs_lite.py --prepare   # Phase 1 only
  review_scraper/venv/bin/python scripts/compare_5stores_flash_vs_lite.py --run        # Phase 2 (needs Phase 1)
  review_scraper/venv/bin/python scripts/compare_5stores_flash_vs_lite.py              # Both
"""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from rule_engine import run_stage1_audit
from prompt_builder import build_prompt
from llm_client import parse_llm_json

SEED = 42
SAMPLE_PER_STORE = 40
EVAL_DIR = Path(__file__).resolve().parent.parent / 'eval'
CACHE_PATH = EVAL_DIR / 'compare_5stores_cache.json'
RESULT_PATH = EVAL_DIR / 'compare_5stores_results.json'

# 5 stores with different characteristics
TARGET_STORES = {
    # 高模糊低洗 — 最難判斷
    '桂冠窩廚房': {'trait': '高模糊低洗 (85%模糊 12%洗, 短評多)'},
    # 中洗率 + 多 spike
    'Oneway CAFE': {'trait': '中洗+spike (76%模糊 20%洗, 2 spike月, 短評多)'},
    # 高洗率邊緣
    '一丁堂拉麵': {'trait': '高洗率邊緣 (66%模糊 29%洗)'},
    # 長評多 — Lite 應該和 Flash 一致
    '墨爾本布蕾斯': {'trait': '長評多 (56短 198中 95長, 3 spike月)'},
    # 均衡分布
    'Pasta 2 Go': {'trait': '均衡 (83短 169中 57長, 3 spike月)'},
}


def find_target_stores():
    """Find target stores in scrape_cache by name substring match."""
    import sqlite3
    import re
    from urllib.parse import unquote
    from cache_store import get_cached_metadata

    stores_list = json.load(open(Path(__file__).resolve().parent.parent / 'review_scraper' / 'stores.json'))
    name_map = {}
    for s in stores_list:
        url = s.get('url', '')
        m = re.search(r'query_place_id=([^&]+)', url)
        if m:
            name_map[m.group(1)] = s.get('name', '')

    def extract_name(place_id):
        for pid_suffix, name in name_map.items():
            if pid_suffix in place_id:
                return name
        decoded = unquote(place_id)
        m = re.search(r'query=([^&]+)', decoded)
        if m:
            return m.group(1).replace('+', ' ')[:60]
        return place_id[:40]

    conn = sqlite3.connect(Path(__file__).resolve().parent.parent / 'cache.db')
    cur = conn.cursor()
    cur.execute('SELECT place_id, reviews_json FROM scrape_cache')

    found = {}
    for place_id, rj in cur.fetchall():
        name = extract_name(place_id)
        for target_key in TARGET_STORES:
            if target_key in name and target_key not in found:
                found[target_key] = (place_id, name, json.loads(rj))
    conn.close()
    return found


def prepare():
    """Phase 1: Run Stage 1 + stratified sample, save to cache."""
    random.seed(SEED)
    now = datetime.now()

    print('Finding target stores in scrape_cache...')
    found = find_target_stores()

    for key in TARGET_STORES:
        if key in found:
            print(f'  ✅ {key} → {found[key][1]}')
        else:
            print(f'  ❌ {key} not found!')

    cache_data = {}

    for key, (place_id, store_name, reviews) in found.items():
        print(f'\n{"="*60}')
        print(f'{store_name} — {TARGET_STORES[key]["trait"]}')
        print(f'{"="*60}')

        stage1 = run_stage1_audit(reviews)
        audited = stage1['auditedReviews']
        signals = stage1['signals']
        spike_months_set = set(signals.get('spikeMonths', []))
        similarity = signals.get('similarity', [])
        hot_term = signals.get('hotTerm', [])
        nearby_long = signals.get('nearbyLongReviewCounts', [])

        # Collect ambiguous 5-star reviews with enriched signals
        ambiguous = []
        for idx, r in enumerate(audited):
            audit = r.get('audit', {})
            if r.get('stars') != 5 or audit.get('issueType') is not None:
                continue

            text = r.get('text', '') or ''
            month = (r.get('time') or '')[:7]
            days_elapsed = 0
            if r.get('time'):
                try:
                    rd = datetime.fromisoformat(r['time'][:10])
                    days_elapsed = max(0, (now - rd).days)
                except (ValueError, TypeError):
                    pass

            sim = similarity[idx] if idx < len(similarity) else {}
            ht = hot_term[idx] if idx < len(hot_term) else {}
            nlr = nearby_long[idx] if idx < len(nearby_long) else 0

            ambiguous.append({
                'username': r.get('username', ''),
                'text': text,
                'stars': 5,
                'time': r.get('time', ''),
                'daysElapsed': days_elapsed,
                'isSpikePeriod': month in spike_months_set,
                'maxSimilarity': sim.get('maxSimilarity', 0),
                'similarCount': sim.get('similarCount', 0),
                'hotTermCount': ht.get('hotTermCount', 0),
                'hotTermMaxRatio': ht.get('hotTermMaxRatio', 0),
                'nearbyLongReviewCount': nlr,
                '_textLen': len(text),
            })

        # Stratified sample by text length
        short = [r for r in ambiguous if r['_textLen'] < 20]
        medium = [r for r in ambiguous if 20 <= r['_textLen'] <= 80]
        long = [r for r in ambiguous if r['_textLen'] > 80]

        total_amb = len(ambiguous)
        # Proportional allocation
        n_short = round(SAMPLE_PER_STORE * len(short) / total_amb) if total_amb else 0
        n_med = round(SAMPLE_PER_STORE * len(medium) / total_amb) if total_amb else 0
        n_long = SAMPLE_PER_STORE - n_short - n_med

        # Clamp to available
        n_short = min(n_short, len(short))
        n_med = min(n_med, len(medium))
        n_long = min(n_long, len(long))
        # Fill remainder from largest pool
        remainder = SAMPLE_PER_STORE - n_short - n_med - n_long
        if remainder > 0:
            pools = [('short', short, n_short), ('medium', medium, n_med), ('long', long, n_long)]
            pools.sort(key=lambda p: len(p[1]) - p[2], reverse=True)
            for pname, pool, already in pools:
                take = min(remainder, len(pool) - already)
                if pname == 'short':
                    n_short += take
                elif pname == 'medium':
                    n_med += take
                else:
                    n_long += take
                remainder -= take
                if remainder <= 0:
                    break

        random.shuffle(short)
        random.shuffle(medium)
        random.shuffle(long)
        sampled = short[:n_short] + medium[:n_med] + long[:n_long]
        random.shuffle(sampled)

        # Remove helper field
        for r in sampled:
            del r['_textLen']

        print(f'  模糊: {total_amb}  抽樣: {len(sampled)} (短{n_short} 中{n_med} 長{n_long})')

        cache_data[key] = {
            'place_id': place_id,
            'store_name': store_name,
            'trait': TARGET_STORES[key]['trait'],
            'total_reviews': len(reviews),
            'total_ambiguous': total_amb,
            'sampled': sampled,
            'sample_dist': {'short': n_short, 'medium': n_med, 'long': n_long},
        }

    EVAL_DIR.mkdir(exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    print(f'\n✅ Cached to {CACHE_PATH}')
    return cache_data


def run(cache_data):
    """Phase 2: Send to Flash + Flash-Lite, compare."""
    from dotenv import load_dotenv
    from google import genai

    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print('❌ GEMINI_API_KEY not set')
        sys.exit(1)

    client = genai.Client(
        api_key=api_key,
        http_options={'retry_options': {'attempts': 1}},
    )

    MODELS = ['gemini-2.5-flash', 'gemini-2.5-flash-lite']

    def call_model(model, store_name, batch):
        prompt = build_prompt(store_name, batch)
        config = {
            'response_mime_type': 'application/json',
            'http_options': {'timeout': 120_000},
            'thinking_config': {'thinking_budget': 0},
        }
        try:
            response = client.models.generate_content(
                model=model, contents=prompt, config=config,
            )
            raw_text = getattr(response, 'text', None)
            parsed = parse_llm_json(raw_text)
            return {r['username']: r for r in parsed}
        except Exception as e:
            print(f'  ⚠️ {model} failed: {e}')
            return {}

    # Send all stores × models in parallel
    all_results = {}
    tasks = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for key, data in cache_data.items():
            store_name = data['store_name']
            sampled = data['sampled']
            for model in MODELS:
                fut = pool.submit(call_model, model, store_name, sampled)
                futures[fut] = (key, model)

        total = len(futures)
        done = 0
        for fut in as_completed(futures):
            key, model = futures[fut]
            result = fut.result()
            all_results.setdefault(key, {})[model] = result
            done += 1
            print(f'  [{done}/{total}] {key} × {model.split("-")[-1]}: {len(result)} reviews')

    elapsed = time.time() - t0
    print(f'\nAll calls done in {elapsed:.1f}s')

    # ── Per-store comparison ──────────────────────────────────────────

    output = {'stores': {}}

    for key, data in cache_data.items():
        store_name = data['store_name']
        sampled = data['sampled']
        flash = all_results.get(key, {}).get(MODELS[0], {})
        lite = all_results.get(key, {}).get(MODELS[1], {})

        print(f'\n{"="*100}')
        print(f'{store_name} — {data["trait"]}')
        print(f'{"="*100}')
        print(f'{"Username":<20} {"Flash":^40} {"Flash-Lite":^40}')
        print(f'{"":20} {"I  A  D  wash  issue  basis":^40} {"I  A  D  wash  issue  basis":^40}')
        print(f'{"-"*100}')

        agree = disagree = 0
        f_washed = l_washed = 0
        iad_diffs = []
        f_issue_dist = Counter()
        l_issue_dist = Counter()
        per_review = []

        for r in sampled:
            u = r['username']
            f = flash.get(u, {})
            l = lite.get(u, {})
            if not f or not l:
                continue

            fw = f.get('isWashed', '?')
            lw = l.get('isWashed', '?')
            fi = f.get('incentiveIntensity', '?')
            fa = f.get('sentimentAuthenticity', '?')
            fd = f.get('descriptionGranularity', '?')
            ft = f.get('issueType', '-') or '-'
            fb = f.get('verdictBasis', '?')
            li = l.get('incentiveIntensity', '?')
            la = l.get('sentimentAuthenticity', '?')
            ld = l.get('descriptionGranularity', '?')
            lt = l.get('issueType', '-') or '-'
            lb = l.get('verdictBasis', '?')

            # Skip rows where either model returned '?' for isWashed
            if fw not in (True, False) or lw not in (True, False):
                f_str = f'{fi}  {fa}  {fd}  {str(fw):5}  {ft:11}  {fb}'
                l_str = f'{li}  {la}  {ld}  {str(lw):5}  {lt:11}  {lb}'
                text_pre = r['text'][:20].replace('\n', ' ')
                print(f'⚠️ {u[:18]:<18} {f_str:^40} {l_str:^40}  {text_pre}')
                per_review.append({'username': u, 'text': r['text'], 'flash': f, 'lite': l})
                continue

            mark = '✅' if fw == lw else '❌'
            if fw == lw:
                agree += 1
            else:
                disagree += 1

            if fw is True:
                f_washed += 1
                f_issue_dist[ft] += 1
            if lw is True:
                l_washed += 1
                l_issue_dist[lt] += 1

            if all(isinstance(v, (int, float)) for v in (fi, li, fa, la, fd, ld)):
                iad_diffs.append((abs(fi - li), abs(fa - la), abs(fd - ld)))

            f_str = f'{fi}  {fa}  {fd}  {str(fw):5}  {ft:11}  {fb}'
            l_str = f'{li}  {la}  {ld}  {str(lw):5}  {lt:11}  {lb}'
            text_pre = r['text'][:20].replace('\n', ' ')
            print(f'{mark} {u[:18]:<18} {f_str:^40} {l_str:^40}  {text_pre}')

            per_review.append({
                'username': u, 'text': r['text'],
                'flash': f, 'lite': l,
            })

        total = agree + disagree
        print(f'\n  一致率: {agree}/{total} ({agree/total*100:.1f}%)' if total else '')
        print(f'  Flash洗: {f_washed}/{total} ({f_washed/total*100:.1f}%)  Lite洗: {l_washed}/{total} ({l_washed/total*100:.1f}%)' if total else '')

        if iad_diffs:
            avg_i = sum(d[0] for d in iad_diffs) / len(iad_diffs)
            avg_a = sum(d[1] for d in iad_diffs) / len(iad_diffs)
            avg_d = sum(d[2] for d in iad_diffs) / len(iad_diffs)
            print(f'  IAD差異: I={avg_i:.2f} A={avg_a:.2f} D={avg_d:.2f}')

        # By length
        for label, lo, hi in [('短<20', 0, 20), ('中20-80', 20, 81), ('長>80', 81, 99999)]:
            sub = [r for r in sampled if lo <= len(r['text']) < hi]
            sa = st = 0
            sf = sl = 0
            for r in sub:
                u = r['username']
                fv = flash.get(u, {}).get('isWashed')
                lv = lite.get(u, {}).get('isWashed')
                if fv is None or lv is None:
                    continue
                st += 1
                if fv == lv:
                    sa += 1
                if fv is True:
                    sf += 1
                if lv is True:
                    sl += 1
            if st:
                print(f'    {label}: 一致{sa}/{st}({sa/st*100:.0f}%) Flash洗{sf}/{st}({sf/st*100:.0f}%) Lite洗{sl}/{st}({sl/st*100:.0f}%)')

        output['stores'][key] = {
            'store_name': store_name,
            'trait': data['trait'],
            'total': total,
            'agreement': agree,
            'agreement_pct': round(agree / total * 100, 1) if total else 0,
            'flash_washed': f_washed,
            'lite_washed': l_washed,
            'flash_issue_dist': dict(f_issue_dist),
            'lite_issue_dist': dict(l_issue_dist),
            'per_review': per_review,
        }

    # ── Grand summary ─────────────────────────────────────────────────

    print(f'\n{"="*100}')
    print('GRAND SUMMARY')
    print(f'{"="*100}')
    g_agree = sum(s['agreement'] for s in output['stores'].values())
    g_total = sum(s['total'] for s in output['stores'].values())
    g_fw = sum(s['flash_washed'] for s in output['stores'].values())
    g_lw = sum(s['lite_washed'] for s in output['stores'].values())
    print(f'整體一致率: {g_agree}/{g_total} ({g_agree/g_total*100:.1f}%)' if g_total else '')
    print(f'Flash洗: {g_fw}/{g_total} ({g_fw/g_total*100:.1f}%)  Lite洗: {g_lw}/{g_total} ({g_lw/g_total*100:.1f}%)' if g_total else '')

    with open(RESULT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\nSaved: {RESULT_PATH}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true', help='Phase 1 only: cache Stage 1 + sample')
    parser.add_argument('--run', action='store_true', help='Phase 2 only: send to API + compare')
    args = parser.parse_args()

    if args.prepare:
        prepare()
    elif args.run:
        if not CACHE_PATH.exists():
            print(f'❌ {CACHE_PATH} not found — run --prepare first')
            sys.exit(1)
        cache_data = json.load(open(CACHE_PATH))
        run(cache_data)
    else:
        cache_data = prepare()
        run(cache_data)
