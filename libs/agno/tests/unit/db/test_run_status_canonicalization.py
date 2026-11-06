"""The shared run-row builders store the run status in its canonical form.

``canonical_run_status`` exists because the indexed ``status`` column is read
case-sensitively: ``HISTORY_SKIP_STATUSES`` is applied as a SQL ``notin_`` list
(sqlite, postgres and their async twins; SurrealDB passes it as ``skip``) and
``get_runs`` compares status filters against ``RunStatus.value``.

Both builders feed that column. ``build_single_run_row`` backs ``upsert_run``
on gcs_json, surrealdb, firestore, redis, valkey and dynamo, and the public
``upsert_run`` signature accepts a plain ``Dict[str, Any]`` -- so a caller
passing ``"cancelled"`` must not end up with a run that silently stops being
excluded from history.
"""

from agno.db.utils import (
    HISTORY_SKIP_STATUSES,
    build_run_rows_for_session,
    build_single_run_row,
    filter_context_runs,
)
from agno.run.base import RunStatus


class TestBuildSingleRunRowCanonicalizesStatus:
    """``build_single_run_row`` normalizes status for dict and enum callers."""

    def test_lowercase_status_is_stored_canonically(self):
        row = build_single_run_row(
            {"run_id": "r1", "agent_id": "a1", "status": "completed"},
            session_id="s1",
            run_index=0,
        )
        assert row["status"] == RunStatus.completed.value

    def test_enum_status_is_stored_as_its_value(self):
        row = build_single_run_row(
            {"run_id": "r1", "agent_id": "a1", "status": RunStatus.completed},
            session_id="s1",
            run_index=0,
        )
        assert row["status"] == RunStatus.completed.value

    def test_run_data_is_canonicalized_alongside_the_column(self):
        # The row carries run_data next to the indexed column; readers that
        # rehydrate a run from run_data must not see a different status.
        row = build_single_run_row(
            {"run_id": "r1", "agent_id": "a1", "status": "completed"},
            session_id="s1",
            run_index=0,
        )
        assert row["run_data"]["status"] == RunStatus.completed.value

    def test_caller_dict_is_not_mutated(self):
        run = {"run_id": "r1", "agent_id": "a1", "status": "completed"}
        build_single_run_row(run, session_id="s1", run_index=0)
        assert run["status"] == "completed"

    def test_canonical_status_passes_through_unchanged(self):
        row = build_single_run_row(
            {"run_id": "r1", "agent_id": "a1", "status": "COMPLETED"},
            session_id="s1",
            run_index=0,
        )
        assert row["status"] == "COMPLETED"

    def test_missing_status_stays_none(self):
        row = build_single_run_row({"run_id": "r1", "agent_id": "a1"}, session_id="s1", run_index=0)
        assert row["status"] is None

    def test_unknown_status_passes_through(self):
        # canonical_run_status documents unknown values as pass-through; the
        # builder must not invent a status it cannot map.
        row = build_single_run_row(
            {"run_id": "r1", "agent_id": "a1", "status": "not-a-status"},
            session_id="s1",
            run_index=0,
        )
        assert row["status"] == "not-a-status"


class TestCancelledRunStaysOutOfHistory:
    """The reason the canonical form matters: history filtering is exact-match."""

    def test_lowercase_cancelled_is_still_skipped(self):
        row = build_single_run_row(
            {"run_id": "r-cancelled", "agent_id": "a1", "status": "cancelled"},
            session_id="s1",
            run_index=0,
        )
        assert row["status"] in HISTORY_SKIP_STATUSES
        assert filter_context_runs([row]) == []

    def test_lowercase_completed_is_still_kept(self):
        row = build_single_run_row(
            {"run_id": "r-done", "agent_id": "a1", "status": "completed"},
            session_id="s1",
            run_index=0,
        )
        assert [r["run_id"] for r in filter_context_runs([row])] == ["r-done"]


class TestBuildRunRowsForSessionCanonicalizesStatus:
    """The bulk builder follows the same rule as the single-run one."""

    def test_session_rows_are_canonicalized(self):
        class _Session:
            session_id = "s1"
            user_id = "u1"
            runs = [
                {"run_id": "r1", "agent_id": "a1", "status": "completed"},
                {"run_id": "r2", "agent_id": "a1", "status": "cancelled"},
            ]

        rows = build_run_rows_for_session(_Session())
        assert [row["status"] for row in rows] == [
            RunStatus.completed.value,
            RunStatus.cancelled.value,
        ]
        assert [row["run_data"]["status"] for row in rows] == [
            RunStatus.completed.value,
            RunStatus.cancelled.value,
        ]
