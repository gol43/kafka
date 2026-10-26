from app.services.batching import balanced_contiguous


def test_equal_items_are_balanced_instead_of_fifteen_plus_one() -> None:
    items = [str(index) for index in range(16)]
    batches = balanced_contiguous(items, [10] * 16, max_tokens=150, max_items=15)
    assert [len(batch) for batch in batches] == [8, 8]
    assert [item for batch in batches for item in batch] == items


def test_atomic_items_never_exceed_token_limit() -> None:
    items = ["a", "b", "c"]
    batches = balanced_contiguous(items, [99, 2, 99], max_tokens=100, max_items=15)
    assert batches == [["a"], ["b"], ["c"]]


def test_item_limit_is_enforced() -> None:
    items = [str(index) for index in range(7)]
    batches = balanced_contiguous(items, [1] * 7, max_tokens=100, max_items=3)
    assert all(len(batch) <= 3 for batch in batches)
    assert [item for batch in batches for item in batch] == items
