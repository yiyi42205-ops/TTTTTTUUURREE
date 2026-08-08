"""
Cross-language validation: detect_hot_term_signals() and
detect_nearby_long_review_counts() in evaluate_v2.py must produce the same
values as their TypeScript originals (computeHotTermSignals /
computeNearbyLongReviewCounts in src/app/utils/auditEngine.ts) for the same
input. Rather than spawning both runtimes together, both sides assert against
the same hardcoded golden values for one shared fixture — see the sibling
test in auditEngine.test.ts ("cross-language fixture" describe block), which
uses the identical usernames/stars/time/text. If either implementation
drifts, its own test fails.
"""

from evaluate_v2 import detect_hot_term_signals, detect_nearby_long_review_counts

# Same data as auditEngine.test.ts's `sharedFixture`, reshaped into CSV-row
# dicts (string values, PascalCase keys) the way csv.DictReader would produce.
SHARED_FIXTURE = [
    {
        'Username': 'u1', 'Stars': '5', 'Time': '2025-01-01T09:00:00',
        'Text': '今天特地來嚐鮮，招牌黑蒜油豚骨拉麵真的很推薦，湯頭濃郁順口，叉燒軟嫩多汁，非常值得一試，下次還會再來品嚐更多菜色。',
    },
    {
        'Username': 'u2', 'Stars': '5', 'Time': '2025-01-01T09:15:00',
        'Text': '朋友介紹來吃黑蒜油豚骨拉麵，確實好吃，湯頭順口不油膩，叉燒也很入味，服務態度親切，整體用餐體驗相當不錯值得推薦。',
    },
    {
        'Username': 'u3', 'Stars': '5', 'Time': '2025-01-05T10:00:00',
        'Text': '特地來吃黑蒜油豚骨拉麵，果然名不虛傳，湯頭濃郁香醇，麵條彈牙有嚼勁，是我吃過最好吃的拉麵之一，強力推薦給大家。',
    },
    {
        'Username': 'u4', 'Stars': '5', 'Time': '2025-01-10T08:00:00',
        'Text': '隨便點了個東西，普普通通沒有特別感覺，服務也普通，可能不會再來了。',
    },
]


def test_hot_term_signals_match_typescript_golden_values():
    counts, ratios = detect_hot_term_signals(SHARED_FIXTURE)

    # Golden values computed by running the real computeHotTermSignals() in
    # auditEngine.ts against the identical fixture (see auditEngine.test.ts).
    assert counts == [1, 1, 1, 0]
    assert ratios == [0.75, 0.75, 0.75, 0]


def test_nearby_long_review_counts_match_typescript_golden_values():
    counts = detect_nearby_long_review_counts(SHARED_FIXTURE)

    # Golden values computed by running the real computeNearbyLongReviewCounts()
    # in auditEngine.ts against the identical fixture (see auditEngine.test.ts).
    # u1 (09:00) and u2 (09:15) are both >50 chars and 15 minutes apart -> each
    # counts the other; u3 is long but 4 days away from u1/u2; u4 is <50 chars.
    assert counts == [1, 1, 0, 0]
