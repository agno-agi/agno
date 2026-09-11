"""Unit tests for where a metrics recalculation resumes.

Records are one per owner per day now, so a day can hold a completed record beside an
incomplete one: the owner whose sessions were deleted leaves a record no recalculation
can rebuild. Resuming at it would restart the recalculation there for every future run,
so the resume point is bounded below by the last day that did complete.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from agno.db.utils import metrics_starting_date_from_records


def _record(day, *, completed):
    """A stored metrics record, reduced to the two fields the resume rule reads."""
    return {"date": day, "completed": completed}


def test_no_records_leaves_the_caller_to_fall_back_to_sessions():
    assert metrics_starting_date_from_records([]) is None


def test_every_day_completed_resumes_the_day_after_the_latest():
    records = [_record("2026-01-01", completed=True), _record("2026-01-03", completed=True)]
    assert metrics_starting_date_from_records(records) == date(2026, 1, 4)


def test_nothing_completed_resumes_at_the_earliest_incomplete_day():
    records = [_record("2026-01-05", completed=False), _record("2026-01-02", completed=False)]
    assert metrics_starting_date_from_records(records) == date(2026, 1, 2)


def test_an_owner_whose_sessions_went_does_not_hold_the_day():
    """The day has a completed record, so it was rebuilt after it ended: move past it."""
    records = [_record("2026-01-01", completed=False), _record("2026-01-01", completed=True)]
    assert metrics_starting_date_from_records(records) == date(2026, 1, 2)


def test_an_older_incomplete_day_is_ignored_once_a_later_day_completed():
    records = [
        _record("2026-01-01", completed=False),
        _record("2026-01-04", completed=True),
    ]
    assert metrics_starting_date_from_records(records) == date(2026, 1, 5)


def test_the_earliest_incomplete_day_wins_so_a_gap_is_not_skipped():
    """Two incomplete days after the last completed one: both still need rebuilding."""
    records = [
        _record("2026-01-01", completed=True),
        _record("2026-01-04", completed=False),
        _record("2026-01-02", completed=False),
    ]
    assert metrics_starting_date_from_records(records) == date(2026, 1, 2)


def test_a_missing_completed_field_counts_as_incomplete():
    assert metrics_starting_date_from_records([{"date": "2026-01-02"}]) == date(2026, 1, 2)


@pytest.mark.parametrize(
    "day",
    [
        "2026-01-02",
        date(2026, 1, 2),
        datetime(2026, 1, 2, 13, 30, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 13, 30, tzinfo=timezone.utc).timestamp(),
    ],
    ids=["iso_string", "date", "datetime", "epoch"],
)
def test_every_stored_date_shape_reads_as_the_same_day(day):
    assert metrics_starting_date_from_records([_record(day, completed=False)]) == date(2026, 1, 2)


def test_an_unusable_date_is_skipped_rather_than_raised_on():
    records = [_record("not-a-day", completed=False), _record("2026-01-02", completed=False)]
    assert metrics_starting_date_from_records(records) == date(2026, 1, 2)


def test_only_unusable_dates_leaves_no_resume_point():
    assert metrics_starting_date_from_records([_record(None, completed=False)]) is None


def test_a_completed_day_ahead_of_today_does_not_resume_in_the_future():
    """The day after it holds no traffic to rebuild, and the caller's range of days comes back empty for good."""
    today = datetime.now(timezone.utc).date()
    assert (
        metrics_starting_date_from_records([_record((today + timedelta(days=400)).isoformat(), completed=True)])
        == today
    )


def test_an_incomplete_day_ahead_of_today_does_not_resume_in_the_future():
    today = datetime.now(timezone.utc).date()
    assert (
        metrics_starting_date_from_records([_record((today + timedelta(days=400)).isoformat(), completed=False)])
        == today
    )


def test_a_day_that_has_already_passed_resumes_where_the_records_say():
    """Only days ahead of today are pulled back: an ordinary past day is left where the rule put it."""
    records = [_record("2026-01-01", completed=True), _record("2026-01-03", completed=False)]
    assert metrics_starting_date_from_records(records) == date(2026, 1, 3)


def test_today_is_a_day_still_owing_and_resumes_at_itself():
    today = datetime.now(timezone.utc).date()
    assert metrics_starting_date_from_records([_record(today, completed=False)]) == today
