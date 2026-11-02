from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from agno.db.surrealdb.models import desurrealize_dates, surrealize_dates
from agno.db.surrealdb.surrealdb import SurrealDb


def test_surrealize_int_timestamp_converts_to_correct_utc():
    utc_dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    epoch = int(utc_dt.timestamp())
    result = surrealize_dates({"created_at": epoch})
    assert result["created_at"] == utc_dt


def test_surrealize_result_has_utc_tzinfo():
    result = surrealize_dates({"created_at": 1705320000})
    assert result["created_at"].tzinfo is not None
    assert result["created_at"].tzinfo == timezone.utc


def test_surrealize_does_not_mutate_original():
    record = {"created_at": 1705320000}
    surrealize_dates(record)
    assert record["created_at"] == 1705320000


def test_surrealize_date_converts_to_midnight_utc():
    d = date(2024, 3, 15)
    result = surrealize_dates({"some_date": d})
    expected = datetime(2024, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert result["some_date"] == expected


def test_surrealize_non_date_fields_unchanged():
    result = surrealize_dates({"created_at": 1705320000, "name": "test", "count": 42})
    assert result["name"] == "test"
    assert result["count"] == 42


def test_epoch_round_trip_preserves_value():
    epoch = 1718476200
    surrealized = surrealize_dates({"created_at": epoch, "updated_at": epoch})
    desurrealized = desurrealize_dates(surrealized)
    assert desurrealized["created_at"] == epoch
    assert desurrealized["updated_at"] == epoch


def test_get_runs_strict_distinguishes_missing_table_from_empty_runs():
    db = SurrealDb.__new__(SurrealDb)
    db._get_table = MagicMock(return_value="runs")
    db.table_exists = MagicMock(return_value=True)
    db._count = MagicMock(return_value=0)
    db._query = MagicMock(return_value=[])

    assert db.get_runs(session_id="s1", deserialize=False, raise_on_error=True) == ([], 0)

    db.table_exists.return_value = False
    with pytest.raises(RuntimeError, match="runs table is unavailable"):
        db.get_runs(session_id="s1", deserialize=False, raise_on_error=True)
    db.table_exists.return_value = True

    db._get_table.side_effect = RuntimeError("storage unavailable")
    assert db.get_runs(session_id="s1", deserialize=False) == ([], 0)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        db.get_runs(session_id="s1", deserialize=False, raise_on_error=True)
