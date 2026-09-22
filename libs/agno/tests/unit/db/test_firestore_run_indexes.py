"""Regression tests for reviewer comment #6 on PR #8350.

Firestore queries on ``runs`` filter by any of ``session_id / user_id /
agent_id / team_id / workflow_id / status`` and sort by
``run_index + created_at``. Without composite indexes for these filter+sort
combinations, Firestore either rejects the query (``FAILED_PRECONDITION``)
or falls back to unindexed scans.

This test asserts the ``RUNS_COLLECTION_SCHEMA`` declares the composite
indexes the read paths actually need — a schema-level regression fence.
"""

from __future__ import annotations

import importlib.util

import pytest

# Import the schemas module directly (bypassing agno.db.firestore.__init__
# which imports the driver-requiring firestore.py module).
_spec = importlib.util.spec_from_file_location(
    "_firestore_schemas",
    __file__.rsplit("/tests/", 1)[0] + "/agno/db/firestore/schemas.py",
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
RUNS_COLLECTION_SCHEMA = _mod.RUNS_COLLECTION_SCHEMA


def _composite_keys() -> list[list[tuple[str, str]]]:
    """Return every composite (multi-field) index in the runs schema as a
    list of (field, direction) tuples."""
    return [idx["key"] for idx in RUNS_COLLECTION_SCHEMA if isinstance(idx.get("key"), list)]


def _has_index(composites: list[list[tuple[str, str]]], required: list[tuple[str, str]]) -> bool:
    return any(idx == required for idx in composites)


class TestRunsCompositeIndexes:
    def test_session_id_run_index_present(self):
        """The base ordered-per-session read (``_get_session_runs_docs``)."""
        assert _has_index(_composite_keys(), [("session_id", "ASCENDING"), ("run_index", "ASCENDING")])

    @pytest.mark.parametrize("scoped", ["status", "agent_id", "team_id", "workflow_id"])
    def test_session_scoped_filter_indexes_present(self, scoped: str):
        """``get_runs(session_id=..., <scoped>=...)`` needs a 3-field composite."""
        composites = _composite_keys()
        required = [("session_id", "ASCENDING"), (scoped, "ASCENDING"), ("run_index", "ASCENDING")]
        assert _has_index(composites, required), f"missing composite index for session_id + {scoped} + run_index"

    @pytest.mark.parametrize("owner", ["user_id", "agent_id", "team_id", "workflow_id"])
    def test_ownership_created_at_index_present(self, owner: str):
        """Cross-session lookups by owner + created_at sort — dashboards, HITL polling."""
        composites = _composite_keys()
        required = [(owner, "ASCENDING"), ("created_at", "DESCENDING")]
        assert _has_index(composites, required)

    def test_status_created_at_index_present(self):
        """Global run-status queries (e.g. all PENDING background runs)."""
        assert _has_index(
            _composite_keys(),
            [("status", "ASCENDING"), ("created_at", "DESCENDING")],
        )

    def test_user_status_created_at_index_present(self):
        """The HITL/background hot path: 'my pending runs, newest first'."""
        assert _has_index(
            _composite_keys(),
            [("user_id", "ASCENDING"), ("status", "ASCENDING"), ("created_at", "DESCENDING")],
        )
