"""Unit tests for folding directory registration counts into day-aggregated metrics.

``merge_registration_counts`` runs after per-user buckets have been collapsed, so it
sees one record per day. Registrations are OS-level, and a day can have them without
any traffic at all.
"""

from datetime import date, datetime, timezone

from agno.db.utils import merge_registration_counts


def _day_epoch(year, month, day):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def _metric_row(day, agent_runs_count=1, period="daily"):
    return {
        "id": f"{day.isoformat()}_{period}",
        "date": day,
        "aggregation_period": period,
        "user_id": "",
        "agent_runs_count": agent_runs_count,
        "users_count": 0,
        "token_metrics": {},
        "model_metrics": [],
        "created_at": 1,
        "updated_at": 2,
    }


class TestMergeRegistrationCounts:
    def test_no_registrations_leaves_rows_untouched(self):
        rows = [_metric_row(date(2026, 1, 1))]
        assert merge_registration_counts(rows, {}) == rows

    def test_count_is_attached_to_the_matching_day(self):
        rows = [_metric_row(date(2026, 1, 1)), _metric_row(date(2026, 1, 2))]
        merged = merge_registration_counts(rows, {_day_epoch(2026, 1, 2): 3})
        assert [(r["date"], r["users_created_count"]) for r in merged] == [
            (date(2026, 1, 1), 0),
            (date(2026, 1, 2), 3),
        ]

    def test_traffic_is_preserved_when_a_count_is_attached(self):
        merged = merge_registration_counts(
            [_metric_row(date(2026, 1, 1), agent_runs_count=7)], {_day_epoch(2026, 1, 1): 2}
        )
        assert merged[0]["agent_runs_count"] == 7
        assert merged[0]["users_created_count"] == 2

    def test_a_day_with_registrations_and_no_traffic_is_synthesised(self):
        # A directory-only deployment: someone signed up, nothing ran. Without the
        # synthesised row the day would not be reported at all.
        merged = merge_registration_counts([], {_day_epoch(2026, 1, 5): 4})
        assert len(merged) == 1
        assert merged[0]["date"] == date(2026, 1, 5)
        assert merged[0]["users_created_count"] == 4
        assert merged[0]["agent_runs_count"] == 0
        assert merged[0]["id"] == "2026-01-05_daily"

    def test_synthesised_and_stored_rows_come_back_in_date_order(self):
        merged = merge_registration_counts(
            [_metric_row(date(2026, 1, 3))],
            {_day_epoch(2026, 1, 1): 1, _day_epoch(2026, 1, 9): 2},
        )
        assert [r["date"] for r in merged] == [date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 9)]

    def test_zero_count_days_are_not_synthesised(self):
        assert merge_registration_counts([], {_day_epoch(2026, 1, 1): 0}) == []

    def test_non_daily_buckets_are_left_alone(self):
        rows = [_metric_row(date(2026, 1, 1), period="monthly")]
        merged = merge_registration_counts(rows, {_day_epoch(2026, 1, 1): 5})
        # The monthly row keeps its shape, and the day still gets reported on its own row.
        assert merged[0] == rows[0]
        assert [r["users_created_count"] for r in merged if r.get("aggregation_period") == "daily"] == [5]
