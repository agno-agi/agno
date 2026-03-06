from datetime import date, datetime, timezone

from agno.db.surrealdb.models import desurrealize_dates, surrealize_dates


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
