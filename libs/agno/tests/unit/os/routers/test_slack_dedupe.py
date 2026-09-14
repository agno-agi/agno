from unittest.mock import patch

from agno.os.interfaces.slack.dedupe import EventDeduplicator


def test_first_sight_is_not_duplicate_and_second_is():
    dedupe = EventDeduplicator()
    assert dedupe.is_duplicate("Ev1") is False
    assert dedupe.is_duplicate("Ev1") is True
    assert dedupe.is_duplicate("Ev2") is False


def test_entries_expire_after_ttl():
    dedupe = EventDeduplicator(ttl_seconds=100.0)
    with patch("agno.os.interfaces.slack.dedupe.time.monotonic", return_value=1000.0):
        assert dedupe.is_duplicate("Ev1") is False
    with patch("agno.os.interfaces.slack.dedupe.time.monotonic", return_value=1050.0):
        assert dedupe.is_duplicate("Ev1") is True
    with patch("agno.os.interfaces.slack.dedupe.time.monotonic", return_value=1101.0):
        # Past the TTL the id is forgotten and a late retry would run again
        assert dedupe.is_duplicate("Ev1") is False


def test_duplicate_hit_does_not_refresh_timestamp():
    dedupe = EventDeduplicator(ttl_seconds=100.0)
    with patch("agno.os.interfaces.slack.dedupe.time.monotonic", return_value=1000.0):
        dedupe.is_duplicate("Ev1")
    with patch("agno.os.interfaces.slack.dedupe.time.monotonic", return_value=1090.0):
        assert dedupe.is_duplicate("Ev1") is True
    with patch("agno.os.interfaces.slack.dedupe.time.monotonic", return_value=1101.0):
        assert dedupe.is_duplicate("Ev1") is False


def test_capacity_evicts_oldest_first():
    dedupe = EventDeduplicator(max_entries=3)
    for key in ("a", "b", "c", "d"):
        assert dedupe.is_duplicate(key) is False
    assert len(dedupe) == 3
    assert dedupe.is_duplicate("a") is False  # evicted, so it reads as new
    assert dedupe.is_duplicate("d") is True
