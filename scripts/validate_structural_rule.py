#!/usr/bin/env python3 -u
"""
Validate rule 2.6 (structural template) against scrape_cache.

Runs Stage 1 on all cached stores and reports:
1. How many reviews are caught by rule 2.6 (verdictBasis="structural")
2. Per-store breakdown of hits
3. Sample of caught reviews for manual inspection

Usage:
  review_scraper/venv/bin/python scripts/validate_structural_rule.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'review_scraper'))

from cache_store import iter_all_scrape_cache, get_cached_metadata
from rule_engine import run_stage1_audit

print('Scanning scrape_cache...\n')

total_stores = 0
total_reviews = 0
total_structural = 0
total_ambiguous = 0  # would go to Stage 2
store_hits = []

for place_id, reviews in iter_all_scrape_cache():
    total_stores += 1
    if not reviews or len(reviews) < 3:
        continue

    result = run_stage1_audit(reviews)
    audited = result['auditedReviews']
    total_reviews += len(audited)

    structural = [r for r in audited if r['audit'].get('verdictBasis') == 'structural']
    ambiguous = [r for r in audited if r['audit']['issueType'] is None]
    total_structural += len(structural)
    total_ambiguous += len(ambiguous)

    if structural:
        meta = get_cached_metadata(place_id)
        store_name = (meta or {}).get('title', place_id[:40])
        store_hits.append({
            'store': store_name,
            'place_id': place_id,
            'total': len(audited),
            'structural': len(structural),
            'ambiguous': len(ambiguous),
            'samples': structural[:3],
        })

    if total_stores % 200 == 0:
        print(f'  {total_stores} stores scanned, {total_structural} structural hits so far...')

# ── Summary ──────────────────────────────────────────────────

print(f'\n{"="*80}')
print(f'SUMMARY')
print(f'{"="*80}')
print(f'Stores scanned:        {total_stores}')
print(f'Total reviews:         {total_reviews}')
print(f'Rule 2.6 hits:         {total_structural}')
print(f'Still ambiguous:       {total_ambiguous} (would go to Stage 2)')
print(f'Stores with hits:      {len(store_hits)}')

if total_structural > 0 and total_reviews > 0:
    print(f'Structural hit rate:   {total_structural/total_reviews*100:.2f}%')

if store_hits:
    print(f'\n{"="*80}')
    print(f'TOP STORES BY STRUCTURAL HITS')
    print(f'{"="*80}')
    store_hits.sort(key=lambda x: x['structural'], reverse=True)
    for s in store_hits[:20]:
        pct = s['structural'] / s['total'] * 100
        print(f'  {s["store"][:30]:<30}  {s["structural"]:>3}/{s["total"]:<3} ({pct:.0f}%)  '
              f'still ambiguous: {s["ambiguous"]}')

    print(f'\n{"="*80}')
    print(f'SAMPLE REVIEWS (first 5 stores)')
    print(f'{"="*80}')
    for s in store_hits[:5]:
        print(f'\n--- {s["store"]} ---')
        for r in s['samples']:
            conf = r['audit']['confidenceScore']
            reason = r['audit']['reason']
            text = (r.get('text', '') or '')[:60].replace('\n', ' ')
            print(f'  [{conf}%] {r.get("username", "?")}: "{text}"')
            print(f'         {reason}')
