import pytest

from agno.db.schemas.scheduler import SCHEDULE_MUTABLE_COLUMNS, validate_schedule_update


class TestValidateScheduleUpdate:
    def test_mutable_columns_pass(self):
        validate_schedule_update({"cron_expr": "0 9 * * *", "enabled": False, "next_run_at": 1700000000})

    def test_empty_update_rejected(self):
        with pytest.raises(ValueError, match="at least one column"):
            validate_schedule_update({})

    @pytest.mark.parametrize(
        "column",
        [
            "managed_by",
            "owner_actor_id",
            "target_type",
            "target_id",
            "created_by_run_id",
            "created_by_session_id",
            "updated_by_run_id",
            "updated_by_session_id",
            "pending_trigger_count",
            "manual_trigger_claimed",
            "locked_by",
            "locked_at",
        ],
    )
    def test_server_owned_columns_rejected(self, column):
        with pytest.raises(ValueError, match="cannot modify"):
            validate_schedule_update({column: "x"})

    def test_server_owned_column_rejected_even_alongside_mutable_one(self):
        with pytest.raises(ValueError, match="managed_by"):
            validate_schedule_update({"description": "ok", "managed_by": "studio"})

    def test_unknown_column_rejected(self):
        with pytest.raises(ValueError, match="cannot modify"):
            validate_schedule_update({"bckground": True})

    def test_mutable_whitelist_is_exactly_the_public_surface(self):
        assert SCHEDULE_MUTABLE_COLUMNS == {
            "name",
            "description",
            "method",
            "endpoint",
            "payload",
            "cron_expr",
            "timezone",
            "timeout_seconds",
            "max_retries",
            "retry_delay_seconds",
            "enabled",
            "next_run_at",
        }


def test_sqlite_update_schedule_enforces_guard(tmp_path):
    from agno.db.sqlite import SqliteDb
    from agno.scheduler.manager import ScheduleManager

    db = SqliteDb(db_file=str(tmp_path / "guard.db"))
    mgr = ScheduleManager(db)
    schedule = mgr.create(name="guarded", cron="0 9 * * *", endpoint="/agents/a1/runs")

    with pytest.raises(ValueError, match="managed_by"):
        db.update_schedule(schedule.id, managed_by="studio", owner_actor_id="attacker")
    with pytest.raises(ValueError, match="managed_by"):
        mgr.update(schedule.id, managed_by="studio")

    # Nothing was written and the row is still generically visible.
    raw = db.get_schedule(schedule.id)
    assert raw["managed_by"] is None
    assert mgr.get(schedule.id) is not None

    # The legitimate surface still works, including SchedulerTools' trigger rewrite.
    assert mgr.update(schedule.id, next_run_at=1700000000).next_run_at == 1700000000
    mgr.close()
