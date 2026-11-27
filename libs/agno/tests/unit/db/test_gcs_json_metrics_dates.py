"""``get_metrics`` must skip an unreadable date, not raise out of the whole read.

The shared helper ``metric_record_day`` states the contract:

    Key-value backends store the date as an ISO string; an unparseable one is
    skipped rather than raised, so one bad row cannot break every metrics read.

redis and valkey call it. ``GcsJsonDb.get_metrics`` parsed inline with
``datetime.strptime(metric.get("date", ""), "%Y-%m-%d")``, which has no guard --
so one row with an empty, null or timestamp-shaped date raised out of the call
and no metrics came back at all. The same loop already ran ``drop_legacy_metrics``
over these rows, which tolerates exactly those dates.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from agno.db.gcs_json import GcsJsonDb


def _row(row_id: str, day, runs: int = 1) -> dict:
    return {
        "id": row_id,
        "date": day,
        "user_id": "u1",
        "aggregation_period": "daily",
        "agent_runs_count": runs,
        "updated_at": 100,
    }


@pytest.fixture
def db() -> GcsJsonDb:
    instance = GcsJsonDb.__new__(GcsJsonDb)
    instance.metrics_table_name = "metrics"
    return instance


def _get_metrics(db: GcsJsonDb, rows: list[dict]):
    with patch.object(GcsJsonDb, "_read_json_file", return_value=[dict(r) for r in rows]):
        return db.get_metrics(starting_date=date(2026, 9, 1), ending_date=date(2026, 9, 30), user_id="u1")


class TestGetMetricsToleratesUnreadableDates:
    @pytest.mark.parametrize("bad_date", ["", None, "not-a-date"])
    def test_one_bad_row_does_not_break_the_read(self, db, bad_date):
        rows, _ = _get_metrics(db, [_row("good", "2026-09-01"), _row("bad", bad_date)])

        assert [r["id"] for r in rows] == ["good"]

    def test_an_iso_timestamp_is_read_as_its_day(self, db):
        # `date.isoformat()` gives "2026-09-02"; a datetime gives it a time part.
        # strptime("%Y-%m-%d") rejects the latter outright.
        rows, _ = _get_metrics(db, [_row("ts", "2026-09-02T00:00:00")])

        assert [r["id"] for r in rows] == ["ts"]

    def test_rows_after_a_bad_one_are_still_returned(self, db):
        rows, _ = _get_metrics(
            db,
            [
                _row("first", "2026-09-01"),
                _row("bad", ""),
                _row("last", "2026-09-06"),
            ],
        )

        assert [r["id"] for r in rows] == ["first", "last"]

    def test_date_range_filtering_still_applies(self, db):
        with patch.object(
            GcsJsonDb,
            "_read_json_file",
            return_value=[_row("inside", "2026-09-10"), _row("outside", "2026-10-10")],
        ):
            rows, _ = db.get_metrics(starting_date=date(2026, 9, 1), ending_date=date(2026, 9, 30), user_id="u1")

        assert [r["id"] for r in rows] == ["inside"]
