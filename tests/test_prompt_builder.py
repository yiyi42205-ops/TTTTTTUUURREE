from prompt_builder import build_review_payload


def test_build_review_payload_includes_new_signal_fields():
    reviews = [
        {
            'username': 'alice',
            'text': '好吃',
            'stars': 5,
            'daysElapsed': 10,
            'isSpikePeriod': True,
            'maxSimilarity': 0.62,
            'similarCount': 4,
            'hotTermCount': 2,
            'hotTermMaxRatio': 0.55,
            'nearbyLongReviewCount': 3,
        }
    ]

    payload = build_review_payload(reviews)

    assert payload[0]['maxSimilarity'] == 0.62
    assert payload[0]['similarCount'] == 4
    assert payload[0]['hotTermCount'] == 2
    assert payload[0]['hotTermMaxRatio'] == 0.55
    assert payload[0]['nearbyLongReviewCount'] == 3


def test_build_review_payload_defaults_missing_signal_fields_to_zero():
    reviews = [{'username': 'bob', 'text': '讚', 'stars': 5}]

    payload = build_review_payload(reviews)

    assert payload[0]['maxSimilarity'] == 0
    assert payload[0]['similarCount'] == 0
    assert payload[0]['hotTermCount'] == 0
    assert payload[0]['hotTermMaxRatio'] == 0
    assert payload[0]['nearbyLongReviewCount'] == 0
    assert payload[0]['daysElapsed'] == 0
    assert payload[0]['isSpikePeriod'] is False
