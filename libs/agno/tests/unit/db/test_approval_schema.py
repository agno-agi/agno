"""Unit tests for agno.db.schemas.approval — Approval dataclass and serialization."""

import time

import pytest

from agno.db.schemas.approval import Approval


def _has_sqlalchemy() -> bool:
    try:
        import sqlalchemy  # noqa: F401

        return True
    except ImportError:
        return False


# =============================================================================
# Construction and defaults
# =============================================================================


class TestApprovalConstruction:
    def test_required_fields(self):
        a = Approval(id="a1", run_id="r1", session_id="s1")
        assert a.id == "a1"
        assert a.run_id == "r1"
        assert a.session_id == "s1"

    def test_default_values(self):
        a = Approval(id="a1", run_id="r1", session_id="s1")
        assert a.status == "pending"
        assert a.source_type == "agent"
        assert a.pause_type == "confirmation"
        assert a.approval_type is None
        assert a.tool_name is None
        assert a.tool_args is None
        assert a.expires_at is None
        assert a.agent_id is None
        assert a.team_id is None
        assert a.workflow_id is None
        assert a.user_id is None
        assert a.schedule_id is None
        assert a.schedule_run_id is None
        assert a.source_name is None
        assert a.requirements is None
        assert a.context is None
        assert a.resolution_data is None
        assert a.resolved_by is None
        assert a.resolved_at is None
        assert a.updated_at is None

    def test_created_at_auto_set(self):
        before = int(time.time())
        a = Approval(id="a1", run_id="r1", session_id="s1")
        after = int(time.time())
        assert before <= a.created_at <= after

    def test_created_at_preserved_when_provided(self):
        a = Approval(id="a1", run_id="r1", session_id="s1", created_at=1000)
        assert a.created_at == 1000

    def test_resolved_at_converted_via_to_epoch_s(self):
        ts = int(time.time())
        a = Approval(id="a1", run_id="r1", session_id="s1", resolved_at=ts)
        assert a.resolved_at == ts

    def test_updated_at_converted_via_to_epoch_s(self):
        ts = int(time.time())
        a = Approval(id="a1", run_id="r1", session_id="s1", updated_at=ts)
        assert a.updated_at == ts


# =============================================================================
# to_dict
# =============================================================================


class TestApprovalToDict:
    def test_all_keys_present(self):
        a = Approval(id="a1", run_id="r1", session_id="s1")
        d = a.to_dict()
        expected_keys = {
            "id",
            "run_id",
            "session_id",
            "status",
            "source_type",
            "approval_type",
            "pause_type",
            "tool_name",
            "tool_args",
            "expires_at",
            "agent_id",
            "team_id",
            "workflow_id",
            "user_id",
            "schedule_id",
            "schedule_run_id",
            "source_name",
            "requirements",
            "context",
            "resolution_data",
            "resolved_by",
            "resolved_at",
            "created_at",
            "updated_at",
        }
        assert set(d.keys()) == expected_keys

    def test_preserves_none_values(self):
        """to_dict should preserve None values, not strip them."""
        a = Approval(id="a1", run_id="r1", session_id="s1")
        d = a.to_dict()
        assert d["tool_name"] is None
        assert d["agent_id"] is None
        assert d["resolved_by"] is None

    def test_round_trip_values(self):
        a = Approval(
            id="a1",
            run_id="r1",
            session_id="s1",
            status="approved",
            source_type="team",
            approval_type="required",
            pause_type="user_input",
            tool_name="delete_file",
            tool_args={"path": "/tmp/x"},
            agent_id="agent-1",
            team_id="team-1",
            user_id="user-1",
            source_name="MyTeam",
            context={"tool_names": ["delete_file"]},
            resolution_data={"values": {"reason": "ok"}},
            resolved_by="admin",
        )
        d = a.to_dict()
        assert d["status"] == "approved"
        assert d["tool_args"] == {"path": "/tmp/x"}
        assert d["context"]["tool_names"] == ["delete_file"]
        assert d["resolution_data"]["values"]["reason"] == "ok"


# =============================================================================
# from_dict
# =============================================================================


class TestApprovalFromDict:
    def test_basic_round_trip(self):
        original = Approval(
            id="a1",
            run_id="r1",
            session_id="s1",
            status="approved",
            approval_type="required",
            tool_name="my_tool",
        )
        d = original.to_dict()
        restored = Approval.from_dict(d)
        assert restored.id == original.id
        assert restored.run_id == original.run_id
        assert restored.status == original.status
        assert restored.approval_type == original.approval_type
        assert restored.tool_name == original.tool_name

    def test_ignores_unknown_keys(self):
        data = {
            "id": "a1",
            "run_id": "r1",
            "session_id": "s1",
            "unknown_field": "should_be_ignored",
            "another_extra": 42,
        }
        a = Approval.from_dict(data)
        assert a.id == "a1"
        assert not hasattr(a, "unknown_field")

    def test_from_dict_does_not_mutate_input(self):
        data = {
            "id": "a1",
            "run_id": "r1",
            "session_id": "s1",
            "extra_key": "should_stay",
        }
        original_data = dict(data)
        Approval.from_dict(data)
        assert data == original_data

    def test_full_round_trip(self):
        """Create -> to_dict -> from_dict -> to_dict should produce same dict."""
        original = Approval(
            id="a1",
            run_id="r1",
            session_id="s1",
            status="rejected",
            source_type="team",
            approval_type="audit",
            pause_type="external_execution",
            tool_name="run_cmd",
            tool_args={"cmd": "ls"},
            agent_id="ag1",
            team_id="t1",
            workflow_id="w1",
            user_id="u1",
            schedule_id="sch1",
            schedule_run_id="sr1",
            source_name="MyTeam",
            requirements=[{"tool_execution": "run_cmd"}],
            context={"tool_names": ["run_cmd"]},
            resolution_data={"result": "ok"},
            resolved_by="admin",
            resolved_at=1700000000,
            created_at=1700000000,
            updated_at=1700000001,
        )
        d1 = original.to_dict()
        restored = Approval.from_dict(d1)
        d2 = restored.to_dict()
        assert d1 == d2


# =============================================================================
# DB schema alignment
# =============================================================================


class TestApprovalSchemaAlignment:
    """Verify that the Approval dataclass fields match the DB schema columns."""

    def _get_approval_dataclass_fields(self):
        return {f.name for f in Approval.__dataclass_fields__.values()}

    @pytest.mark.skipif(
        not _has_sqlalchemy(),
        reason="sqlalchemy not installed",
    )
    def test_postgres_schema_columns_match(self):
        from agno.db.postgres.schemas import APPROVAL_TABLE_SCHEMA

        schema_columns = set(APPROVAL_TABLE_SCHEMA.keys())
        # Remove internal schema keys that aren't columns
        schema_columns -= {"_unique_constraints", "_indexes"}
        dataclass_fields = self._get_approval_dataclass_fields()
        assert schema_columns == dataclass_fields

    @pytest.mark.skipif(
        not _has_sqlalchemy(),
        reason="sqlalchemy not installed",
    )
    def test_sqlite_schema_columns_match(self):
        from agno.db.sqlite.schemas import APPROVAL_TABLE_SCHEMA

        schema_columns = set(APPROVAL_TABLE_SCHEMA.keys())
        schema_columns -= {"_unique_constraints", "_indexes"}
        dataclass_fields = self._get_approval_dataclass_fields()
        assert schema_columns == dataclass_fields

    @pytest.mark.skipif(
        not _has_sqlalchemy(),
        reason="sqlalchemy not installed",
    )
    def test_postgres_and_sqlite_schemas_have_same_columns(self):
        from agno.db.postgres.schemas import APPROVAL_TABLE_SCHEMA as PG_SCHEMA
        from agno.db.sqlite.schemas import APPROVAL_TABLE_SCHEMA as SQLITE_SCHEMA

        pg_cols = set(PG_SCHEMA.keys()) - {"_unique_constraints", "_indexes"}
        sqlite_cols = set(SQLITE_SCHEMA.keys()) - {"_unique_constraints", "_indexes"}
        assert pg_cols == sqlite_cols
