from datetime import datetime

from agno.session.summary import SessionSummary


def test_from_dict_does_not_mutate_caller_dict():
    data = {"summary": "hello", "topics": ["a"], "updated_at": "2026-01-01T00:00:00"}

    summary = SessionSummary.from_dict(data)
    assert isinstance(summary.updated_at, datetime)

    # The caller's dict must be untouched (was rewritten str -> datetime in place).
    assert data["updated_at"] == "2026-01-01T00:00:00"


def test_from_dict_is_repeatable_on_same_dict():
    data = {"summary": "hello", "topics": ["a"], "updated_at": "2026-01-01T00:00:00"}

    # Deserializing the same stored dict twice used to raise
    # "TypeError: fromisoformat: argument must be str" on the second call.
    first = SessionSummary.from_dict(data)
    second = SessionSummary.from_dict(data)
    assert first.updated_at == second.updated_at
