"""End-to-end regression test for PR #7508.

Mirrors the original bug report: create a workflow through the
Components API path with custom ``session_table`` in its db config,
execute it, and verify the session row lands in the configured custom
table rather than the default ``agno_sessions`` table.
"""

import asyncio
import sqlite3

import pytest

from agno.db.base import ComponentType
from agno.db.sqlite.sqlite import SqliteDb
from agno.workflow import Step, StepOutput
from agno.workflow.workflow import get_workflow_by_id


class _FakeRegistry:
    """Minimal registry stand-in that exposes a single registered db."""

    def __init__(self, db):
        self._db = db
        # The workflow from_dict logic only uses get_db; the other
        # attributes are accessed by other code paths in some tests.
        self.agents = []
        self.teams = []

    def get_db(self, db_id):
        if self._db is not None and getattr(self._db, "id", None) == db_id:
            return self._db
        return None

    def get_all_component_ids(self):
        return set()


def _dummy_step(step_input):
    return StepOutput(content="ok")


class TestWorkflowCustomSessionTable:
    def test_custom_session_table_survives_components_api_roundtrip(self, tmp_path):
        """Regression for agno-agi/agno#7508.

        The workflow is persisted via the Components API (``upsert_component``
        + ``upsert_config``) with a db block that overrides ``session_table``
        and references os_db's id. On reload via ``get_workflow_by_id``
        through the registry-backed path, execution must write sessions
        to the custom table, not the default ``agno_sessions``.
        """
        db_path = tmp_path / "e2e.db"
        os_db = SqliteDb(db_file=str(db_path))
        registry = _FakeRegistry(os_db)

        os_db.upsert_component(
            component_id="wf-custom",
            component_type=ComponentType.WORKFLOW,
            name="wf with custom session table",
        )
        # The stored config references os_db by id so the registry-backed
        # load path is exercised — this is the branch that regressed.
        os_db.upsert_config(
            component_id="wf-custom",
            config={
                "db": {
                    **os_db.to_dict(),
                    "session_table": "custom_workflow_sessions",
                },
                "id": "wf-custom",
                "name": "wf with custom session table",
            },
            stage="published",
        )

        workflow = get_workflow_by_id(db=os_db, id="wf-custom", registry=registry)
        assert workflow is not None
        # Table name from the stored config, not os_db's default.
        assert workflow.db.session_table_name == "custom_workflow_sessions"
        # Engine is shared with os_db so repeated loads don't proliferate pools.
        assert workflow.db.db_engine is os_db.db_engine

        workflow.steps = [Step(name="noop", executor=_dummy_step)]
        asyncio.run(workflow.arun(input="hello", session_id="sess-1"))

        with sqlite3.connect(str(db_path)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        assert "custom_workflow_sessions" in tables, "custom session table was not created"
        assert "agno_sessions" not in tables, "default session table must not be used when an override is configured"

        # Repeated loads must all share one engine (Codex P1 concern).
        seen_engines = set()
        for _ in range(5):
            reloaded = get_workflow_by_id(db=os_db, id="wf-custom", registry=registry)
            assert reloaded is not None
            seen_engines.add(id(reloaded.db.db_engine))
        assert len(seen_engines) == 1

    def test_workflow_without_override_reuses_registered_db_instance(self, tmp_path):
        """Sanity check: when the stored config has no table-name overrides,
        the load path returns the registered db instance directly (no clone),
        which is the fast path we want to preserve."""
        db_path = tmp_path / "noop.db"
        os_db = SqliteDb(db_file=str(db_path))
        registry = _FakeRegistry(os_db)

        os_db.upsert_component(
            component_id="wf-plain",
            component_type=ComponentType.WORKFLOW,
            name="wf plain",
        )
        os_db.upsert_config(
            component_id="wf-plain",
            config={
                "db": os_db.to_dict(),
                "id": "wf-plain",
                "name": "wf plain",
            },
            stage="published",
        )

        workflow = get_workflow_by_id(db=os_db, id="wf-plain", registry=registry)
        assert workflow is not None
        # No clone needed — same Python object as os_db.
        assert workflow.db is os_db


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
