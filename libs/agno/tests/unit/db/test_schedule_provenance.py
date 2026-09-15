"""Schedule provenance columns, the update allow-list, and the archive cascade.

The Studio 3.0 schedule governance contract: a generic
update_schedule can never write ownership, provenance, trigger or lock state;
control planes write provenance through stamp_schedule_provenance; archiving a
component disables every schedule aimed at it (provenance-tagged and generic
by endpoint) with a reason the owner's next read explains; enabling clears
the reason.
"""

import pytest

from agno.db.schemas.scheduler import (
    SCHEDULE_MUTABLE_COLUMNS,
    STUDIO_SCHEDULE_MANAGED_BY,
    validate_schedule_update,
)
from agno.db.sqlite import SqliteDb


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="schedule-provenance-db", db_file=str(tmp_path / "sched_prov.db"))


def _mk(db, name, endpoint="/agents/analyst/runs", **extra):
    data = {
        "id": f"sched-{name}",
        "name": name,
        "cron_expr": "0 9 * * *",
        "endpoint": endpoint,
        "method": "POST",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "created_at": 1,
    }
    data.update(extra)
    return db.create_schedule(data)


class TestUpdateAllowList:
    def test_provenance_columns_are_rejected(self, db):
        _mk(db, "guarded")
        for column in ("managed_by", "target_type", "target_id", "created_by_run_id", "updated_by_run_id"):
            with pytest.raises(ValueError, match="update_schedule cannot modify"):
                db.update_schedule("sched-guarded", **{column: "x"})

    def test_user_id_is_a_filter_never_a_write(self, db):
        # update_schedule's user_id parameter scopes the WHERE clause; it can
        # never move a row between owners.
        _mk(db, "owned", user_id="alice")
        assert db.update_schedule("sched-owned", user_id="bob", description="hijack") is None
        row = db.get_schedule("sched-owned")
        assert row["user_id"] == "alice" and row["description"] is None

    def test_mutable_columns_pass(self, db):
        _mk(db, "mutable")
        row = db.update_schedule("sched-mutable", cron_expr="0 10 * * *", description="new")
        assert row is not None and row["cron_expr"] == "0 10 * * *"

    def test_the_allow_list_is_exactly_the_public_surface(self):
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
            "disabled_reason",
        }

    def test_validator_names_the_dedicated_path(self):
        with pytest.raises(ValueError, match="dedicated APIs"):
            validate_schedule_update({"locked_by": "w"})


class TestProvenanceStamp:
    def test_stamp_writes_control_plane_columns(self, db):
        _mk(db, "stamped")
        assert db.stamp_schedule_provenance(
            "sched-stamped",
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            target_type="agent",
            target_id="analyst",
            created_by_run_id="run-1",
        )
        row = db.get_schedule("sched-stamped")
        assert row["managed_by"] == "studio"
        assert row["target_type"] == "agent" and row["target_id"] == "analyst"
        assert row["created_by_run_id"] == "run-1"

    def test_stamp_refuses_everything_else(self, db):
        _mk(db, "sneaky")
        with pytest.raises(ValueError, match="cannot write"):
            db.stamp_schedule_provenance("sched-sneaky", enabled=False)
        with pytest.raises(ValueError, match="cannot write"):
            db.stamp_schedule_provenance("sched-sneaky", user_id="mallory")

    def test_stamp_missing_row_returns_false(self, db):
        assert db.stamp_schedule_provenance("ghost", managed_by="studio") is False


class TestDisableForTarget:
    def test_disables_tagged_and_generic_rows_across_owners(self, db):
        _mk(db, "alices", user_id="alice")
        db.stamp_schedule_provenance("sched-alices", managed_by="studio", target_type="agent", target_id="analyst")
        _mk(db, "bobs", user_id="bob")
        db.stamp_schedule_provenance("sched-bobs", managed_by="studio", target_type="agent", target_id="analyst")
        _mk(db, "generic-same-endpoint")  # untagged, same endpoint
        _mk(db, "unrelated", endpoint="/agents/other/runs")

        count = db.disable_schedules_for_target("agent", "analyst", reason="target_archived:agent:analyst")
        assert count == 3
        for sid in ("sched-alices", "sched-bobs", "sched-generic-same-endpoint"):
            row = db.get_schedule(sid)
            assert row["enabled"] in (False, 0), sid
            assert row["disabled_reason"] == "target_archived:agent:analyst", sid
        assert db.get_schedule("sched-unrelated")["enabled"] in (True, 1)

    def test_second_call_counts_zero(self, db):
        _mk(db, "once")
        db.stamp_schedule_provenance("sched-once", managed_by="studio", target_type="agent", target_id="analyst")
        assert db.disable_schedules_for_target("agent", "analyst") == 1
        assert db.disable_schedules_for_target("agent", "analyst") == 0

    def test_enable_clears_the_reason(self, db):
        _mk(db, "revivable")
        db.disable_schedules_for_target("agent", "analyst", reason="target_archived:agent:analyst")
        row = db.update_schedule("sched-revivable", enabled=True)
        assert row["enabled"] in (True, 1)
        assert row["disabled_reason"] is None

    def test_cascade_reason_round_trips_through_the_enable_guard_parser(self, db):
        # The enable guard (SchedulerTools / the REST enable route) parses the
        # cascade's reason back into (type, id); the writer and the parser must
        # not drift.
        from agno.tools.scheduler import _parse_target_archived_reason

        _mk(db, "parsed")
        db.disable_schedules_for_target("agent", "analyst", reason="target_archived:agent:analyst")
        row = db.get_schedule("sched-parsed")
        assert _parse_target_archived_reason(row["disabled_reason"]) == ("agent", "analyst")


class TestRunEndpointHelpers:
    """The single builder/matcher pair, so builder and parser cannot drift."""

    def test_builder_matches_the_regex_it_is_paired_with(self):
        from agno.db.schemas.scheduler import RUN_ENDPOINT_RE, build_run_endpoint

        for target_type, target_id in (("agent", "analyst"), ("team", "t1"), ("workflow", "w1")):
            endpoint = build_run_endpoint(target_type, target_id)
            match = RUN_ENDPOINT_RE.match(endpoint)
            assert match is not None
            assert match.group(1) == f"{target_type}s"
            assert match.group(2) == target_id

    def test_matcher_tolerates_the_trailing_slash_the_regex_accepts(self):
        from agno.db.schemas.scheduler import match_run_endpoint

        assert match_run_endpoint("/agents/analyst/runs", "agent", "analyst")
        assert match_run_endpoint("/agents/analyst/runs/", "agent", "analyst")
        assert not match_run_endpoint("/agents/other/runs", "agent", "analyst")
        assert not match_run_endpoint("/teams/analyst/runs", "agent", "analyst")


class TestDisableForTargetTrailingSlash:
    """RUN_ENDPOINT_RE accepts "/runs/", so the cascade must too.

    A schedule stored with a trailing slash is a valid run endpoint the router
    accepts and the executor fires; if the cascade misses it, archiving the
    target leaves it firing 404s forever - the exact failure the primitive exists
    to prevent.
    """

    def test_generic_row_with_trailing_slash_is_disabled(self, db):
        _mk(db, "slashed", endpoint="/agents/analyst/runs/")
        count = db.disable_schedules_for_target("agent", "analyst", reason="target_archived:agent:analyst")
        assert count == 1
        row = db.get_schedule("sched-slashed")
        assert row["enabled"] in (False, 0)
        assert row["disabled_reason"] == "target_archived:agent:analyst"

    def test_both_spellings_disabled_together(self, db):
        _mk(db, "plain", endpoint="/agents/analyst/runs")
        _mk(db, "slashed", endpoint="/agents/analyst/runs/")
        _mk(db, "unrelated-slashed", endpoint="/agents/other/runs/")
        assert db.disable_schedules_for_target("agent", "analyst") == 2
        assert db.get_schedule("sched-unrelated-slashed")["enabled"] in (True, 1)
