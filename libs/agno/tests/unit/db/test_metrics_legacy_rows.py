"""Unit tests for legacy metric records at the adapter's own read.

Key-value and document backends changed the metric id when ownership landed, so the
record a pre-v3.0 version wrote is never matched again and stays beside its per-user
replacements. ``get_metrics`` drops it, so a direct SDK read does not count the day twice.
"""

from datetime import date

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.json import JsonDb

TARGET_DATE = date(2026, 1, 1)
DAY = TARGET_DATE.isoformat()


def _record(user_id, runs, *, record_id=None, users_count=None):
    """A stored metrics record. ``user_id`` None omits the field, as pre-v3.0 writers did."""
    record = {
        "id": record_id or f"{DAY}_{user_id}_daily",
        "date": DAY,
        "aggregation_period": "daily",
        "agent_runs_count": runs,
        "agent_sessions_count": 1,
        "team_runs_count": 0,
        "team_sessions_count": 0,
        "workflow_runs_count": 0,
        "workflow_sessions_count": 0,
        "users_count": users_count if users_count is not None else (0 if user_id in (None, "") else 1),
        "token_metrics": {},
        "model_metrics": [],
        "created_at": 1,
        "updated_at": 1,
        "completed": False,
    }
    if user_id is not None:
        record["user_id"] = user_id
    return record


ALICE = _record("alice", 2)
BOB = _record("bob", 1)
# Most backends wrote no user_id at all; valkey wrote one and filed every user under it.
NO_OWNER_FIELD = _record(None, 99, record_id=f"{DAY}_daily", users_count=2)
UNOWNED_BUCKET_SHAPED = _record("", 99, record_id=f"{DAY}__daily", users_count=2)


@pytest.fixture(params=["json", "in_memory"])
def db(request, tmp_path):
    return JsonDb(db_path=str(tmp_path)) if request.param == "json" else InMemoryDb()


def _seed(db, records):
    """Put records in the store the way the adapter itself holds them."""
    if isinstance(db, InMemoryDb):
        db._metrics = list(records)
    else:
        db._write_json_file(db.metrics_table_name, list(records))


def _runs(rows):
    return sum(row.get("agent_runs_count") or 0 for row in rows)


class TestLegacyMetricRecords:
    @pytest.mark.parametrize("legacy", [NO_OWNER_FIELD, UNOWNED_BUCKET_SHAPED], ids=["no_field", "unowned_shaped"])
    def test_unscoped_read_drops_the_legacy_record(self, db, legacy):
        _seed(db, [legacy, ALICE, BOB])

        rows, _ = db.get_metrics()

        assert _runs(rows) == 3
        assert sorted(row["id"] for row in rows) == sorted([ALICE["id"], BOB["id"]])

    def test_legacy_record_alone_is_still_the_day(self, db):
        _seed(db, [NO_OWNER_FIELD])

        rows, _ = db.get_metrics()

        assert _runs(rows) == 99

    def test_scoped_read_is_unaffected(self, db):
        _seed(db, [NO_OWNER_FIELD, ALICE, BOB])

        rows, _ = db.get_metrics(user_id="alice")

        assert [row["id"] for row in rows] == [ALICE["id"]]
