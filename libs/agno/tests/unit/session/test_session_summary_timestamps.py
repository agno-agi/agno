"""``SessionSummary.updated_at`` must survive the shapes the rest of the layer accepts.

The session API declares its ``summary`` body as an unvalidated ``Dict[str, Any]``, and
every session read reaches this reader through ``AgentSession.from_dict`` /
``TeamSession.from_dict``, so whatever a client stores is what this parser has to take.
"""

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from agno.session.agent import AgentSession
from agno.session.summary import SessionSummary

# 2025-09-01T07:53:17+00:00
EPOCH_S = 1_756_713_197
UTC_STAMP = datetime(2025, 9, 1, 7, 53, 17, tzinfo=timezone.utc)


def test_from_dict_accepts_epoch_seconds():
    summary = SessionSummary.from_dict({"summary": "s", "updated_at": EPOCH_S})

    assert summary.updated_at == UTC_STAMP
    assert summary.updated_at.tzinfo is not None


def test_from_dict_accepts_a_z_suffixed_stamp():
    # Python 3.9/3.10, both inside ``requires-python``, reject "Z" outright; the trailing
    # offset is what pydantic serializes and what a browser Date.toISOString() sends.
    summary = SessionSummary.from_dict({"summary": "s", "updated_at": "2025-09-01T07:53:17Z"})

    assert summary.updated_at == UTC_STAMP


def test_from_dict_accepts_an_already_parsed_datetime():
    assert SessionSummary.from_dict({"summary": "s", "updated_at": UTC_STAMP}).updated_at is UTC_STAMP


def test_from_dict_keeps_reading_a_naive_stamp_as_wall_clock():
    # Pinned so the added branches stay additive: an offset-less stamp reads back exactly
    # as it did before, matching the round trip the summary writer performs.
    summary = SessionSummary.from_dict({"summary": "s", "updated_at": "2023-01-01T12:00:00"})

    assert summary.updated_at == datetime(2023, 1, 1, 12, 0, 0)
    assert summary.updated_at.tzinfo is None


def test_from_dict_rejects_a_value_that_is_not_a_timestamp():
    with pytest.raises(TypeError, match="SessionSummary.updated_at"):
        SessionSummary.from_dict({"summary": "s", "updated_at": True})


def test_from_dict_does_not_mutate_the_callers_dict():
    data = {"summary": "s", "updated_at": EPOCH_S}

    SessionSummary.from_dict(data)

    assert data["updated_at"] == EPOCH_S


def test_from_dict_accepts_a_read_only_mapping():
    # The sibling session readers annotate their input as ``Mapping``, and writing back
    # into one is the failure #7462 had to remove one layer up. No in-repo caller hits
    # this with a read-only mapping today; the assertion pins the contract at its source.
    summary = SessionSummary.from_dict(MappingProxyType({"summary": "s", "updated_at": EPOCH_S}))

    assert summary.updated_at == UTC_STAMP


def test_agent_session_read_accepts_an_epoch_summary():
    session = AgentSession.from_dict(
        {"session_id": "s1", "summary": {"summary": "s", "updated_at": EPOCH_S}},
    )

    assert session is not None
    assert session.summary.updated_at == UTC_STAMP


def test_round_trip_survives_to_dict():
    summary = SessionSummary(summary="s", topics=["a"], updated_at=UTC_STAMP)

    assert SessionSummary.from_dict(summary.to_dict()) == summary
