"""`session_data` defaults to None on agent/team/workflow sessions.

`calculate_date_metrics` chained `session.get("session_data", {}).get(...)`, which
crashes when the key is present with a None value (`.get(key, default)` returns None,
not the default). postgres/valkey already guard this with `or {}`; the other backends
did not. These use the dependency-free in_memory/json backends, which share the same
fixed line.
"""

from datetime import date

import pytest

from agno.db.in_memory.utils import calculate_date_metrics as in_memory_metrics
from agno.db.json.utils import calculate_date_metrics as json_metrics


@pytest.mark.parametrize("calculate_date_metrics", [in_memory_metrics, json_metrics])
def test_session_data_none_does_not_crash(calculate_date_metrics):
    sessions_data = {
        "agent": [{"user_id": "u1", "session_data": None, "runs": []}],
        "team": [],
        "workflow": [],
    }
    result = calculate_date_metrics(date(2024, 1, 1), sessions_data)
    assert result["agent_sessions_count"] == 1
    assert result["token_metrics"]["total_tokens"] == 0


@pytest.mark.parametrize("calculate_date_metrics", [in_memory_metrics, json_metrics])
def test_session_data_present_still_aggregates(calculate_date_metrics):
    sessions_data = {
        "agent": [
            {
                "user_id": "u1",
                "session_data": {"session_metrics": {"input_tokens": 5, "total_tokens": 8}},
                "runs": [],
            }
        ],
        "team": [],
        "workflow": [],
    }
    result = calculate_date_metrics(date(2024, 1, 1), sessions_data)
    assert result["token_metrics"]["input_tokens"] == 5
    assert result["token_metrics"]["total_tokens"] == 8
