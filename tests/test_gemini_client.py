from llm_client import make_batches


def test_make_batches_sorts_by_days_elapsed_before_splitting():
    """Each batch must be a contiguous stretch of the globally time-sorted
    review list — the closest a fixed-size chunking scheme can get to keeping
    temporally-close reviews together for Gemini to cross-reference."""
    reviews = [
        {'username': 'a', 'daysElapsed': 100},
        {'username': 'b', 'daysElapsed': 5},
        {'username': 'c', 'daysElapsed': 50},
        {'username': 'd', 'daysElapsed': 6},
        {'username': 'e', 'daysElapsed': 4},
    ]

    batches = make_batches(reviews, target_size=2, max_size=2)

    concatenated = [r['daysElapsed'] for batch in batches for r in batch]
    assert concatenated == sorted(r['daysElapsed'] for r in reviews)

    # Each individual batch is itself internally sorted (a contiguous slice).
    for batch in batches:
        days = [r['daysElapsed'] for r in batch]
        assert days == sorted(days)


def test_make_batches_single_batch_still_sorted():
    reviews = [
        {'username': 'a', 'daysElapsed': 30},
        {'username': 'b', 'daysElapsed': 10},
        {'username': 'c', 'daysElapsed': 20},
    ]

    batches = make_batches(reviews, target_size=40, max_size=50)

    assert len(batches) == 1
    assert [r['daysElapsed'] for r in batches[0]] == [10, 20, 30]


def test_make_batches_missing_days_elapsed_defaults_to_zero_and_does_not_crash():
    reviews = [{'username': 'a'}, {'username': 'b', 'daysElapsed': 5}]
    batches = make_batches(reviews)
    assert len(batches) == 1
    assert [r.get('daysElapsed', 0) for r in batches[0]] == [0, 5]
