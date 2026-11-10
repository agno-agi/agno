"""Regression test: deserialize_run must tolerate a str run_data payload.

MySQL/SingleStore JSON columns (and SQLite TEXT) can hand the run payload back
as a JSON string rather than a dict, depending on the driver. ``deserialize_run``
fed that straight into ``RunOutput.from_dict``, which breaks on a str. It now
normalizes a str payload with ``json.loads`` first, so ``get_run``/``get_runs``
work uniformly across adapters.
"""

from __future__ import annotations

import json

from agno.db.utils import deserialize_run


class TestDeserializeRunStrPayload:
    def test_str_payload_matches_dict_payload(self):
        run = {"run_id": "r1", "agent_id": "a1", "status": "COMPLETED"}

        from_str = deserialize_run("agent", json.dumps(run))
        from_dict = deserialize_run("agent", run)

        assert from_str.run_id == from_dict.run_id == "r1"

    def test_str_payload_with_inferred_run_type(self):
        # run_type=None forces get_run_type() to inspect the (parsed) payload.
        run = {"run_id": "r1", "team_id": "t1"}

        result = deserialize_run(None, json.dumps(run))

        assert result.run_id == "r1"
