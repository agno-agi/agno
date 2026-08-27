"""Unit tests for ``merge_runs_table_with_legacy_blob``.

The merge is called by every ported adapter on the read path when a session
may have runs split across the new ``agno_runs`` table and the legacy
``agno_sessions.runs`` blob (partial-migration state). The critical property
under test here is **chronological insertion order**: the reviewer flagged
that the previous implementation returned ``[r0, r2, r1, r3]`` when runs r0
and r2 were migrated but r1 and r3 were still in the blob, silently
reordering the conversation.
"""

from __future__ import annotations

import json

import pytest

from agno.db.utils import merge_runs_table_with_legacy_blob


def _run(run_id: str, **extra) -> dict:
    """Small helper producing a dict shaped like a run row."""
    return {"run_id": run_id, **extra}


class TestPreservesInsertionOrder:
    """Regression tests for reviewer comment #2 — order must match true history."""

    def test_split_odd_even_split_across_table_and_blob(self):
        """Runs r0 and r2 in table, r1 and r3 in blob → merged must be [r0, r1, r2, r3]."""
        table_runs = [_run("r0", content="table-0"), _run("r2", content="table-2")]
        legacy_runs = [
            _run("r0", content="blob-0"),
            _run("r1", content="blob-1"),
            _run("r2", content="blob-2"),
            _run("r3", content="blob-3"),
        ]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2", "r3"], (
            "chronological order must match the historical (legacy) insertion order"
        )

    def test_single_migrated_run_in_middle(self):
        """Only one run migrated; others still in blob. Middle position must survive."""
        table_runs = [_run("r1", content="table-1")]
        legacy_runs = [_run("r0"), _run("r1"), _run("r2"), _run("r3")]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2", "r3"]

    def test_trailing_migrated_run(self):
        """Only the last run is in the table."""
        table_runs = [_run("r3")]
        legacy_runs = [_run("r0"), _run("r1"), _run("r2"), _run("r3")]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2", "r3"]

    def test_leading_migrated_run(self):
        """Only the first run is in the table."""
        table_runs = [_run("r0")]
        legacy_runs = [_run("r0"), _run("r1"), _run("r2"), _run("r3")]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2", "r3"]


class TestConflictResolution:
    """Table wins on run_id conflicts — represents state changes since migration."""

    def test_table_version_wins_over_blob(self):
        table_runs = [_run("r1", status="COMPLETED", content="table-latest")]
        legacy_runs = [_run("r1", status="PAUSED", content="blob-stale")]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        assert len(merged) == 1
        assert merged[0]["status"] == "COMPLETED"
        assert merged[0]["content"] == "table-latest"

    def test_conflict_preserves_legacy_position(self):
        """Even when the table version is used, it should sit at the legacy's
        chronological position — not at the tail."""
        table_runs = [_run("r1", content="table-latest")]
        legacy_runs = [_run("r0"), _run("r1", content="blob-stale"), _run("r2")]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        ids = [r["run_id"] for r in merged]
        contents = [r.get("content") for r in merged]
        assert ids == ["r0", "r1", "r2"]
        # The r1 slot contains the table's (fresh) copy, not the blob's stale one.
        assert contents[1] == "table-latest"


class TestNewRunsAppendedAtTail:
    """Runs that only exist in the table are writes made AFTER migration — they
    are strictly newer than everything the blob knew about."""

    def test_new_run_appended_after_legacy_history(self):
        table_runs = [_run("r4", content="new-post-migration")]
        legacy_runs = [_run("r0"), _run("r1"), _run("r2"), _run("r3")]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2", "r3", "r4"]

    def test_mix_of_conflicts_and_new_runs(self):
        """Table has: r2 (state update to an existing run) + r4 (new run)."""
        table_runs = [
            _run("r2", content="table-r2-updated"),
            _run("r4", content="new-post-migration"),
        ]
        legacy_runs = [
            _run("r0"),
            _run("r1"),
            _run("r2", content="blob-r2-stale"),
            _run("r3"),
        ]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        # r0, r1 from blob; r2 from table (at legacy position!); r3 from blob;
        # r4 appended at the tail.
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2", "r3", "r4"]
        assert merged[2]["content"] == "table-r2-updated"

    def test_multiple_new_runs_keep_table_order(self):
        table_runs = [_run("r4"), _run("r5"), _run("r6")]
        legacy_runs = [_run("r0"), _run("r1")]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r4", "r5", "r6"]


class TestEmptyInputs:
    def test_empty_legacy_returns_table_verbatim(self):
        table_runs = [_run("r0"), _run("r1"), _run("r2")]
        merged = merge_runs_table_with_legacy_blob(table_runs, [])
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2"]

    def test_none_legacy_returns_table_verbatim(self):
        table_runs = [_run("r0"), _run("r1")]
        merged = merge_runs_table_with_legacy_blob(table_runs, None)
        assert [r["run_id"] for r in merged] == ["r0", "r1"]

    def test_empty_table_returns_legacy_verbatim(self):
        legacy_runs = [_run("r0"), _run("r1"), _run("r2")]
        merged = merge_runs_table_with_legacy_blob([], legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2"]

    def test_both_empty_returns_empty(self):
        assert merge_runs_table_with_legacy_blob([], []) == []
        assert merge_runs_table_with_legacy_blob([], None) == []


class TestLegacyStringInput:
    """SQL adapters may return the legacy blob as a JSON-encoded string."""

    def test_json_string_legacy_is_parsed(self):
        legacy_json = json.dumps([_run("r0"), _run("r1")])
        merged = merge_runs_table_with_legacy_blob([_run("r2")], legacy_json)
        assert [r["run_id"] for r in merged] == ["r0", "r1", "r2"]

    def test_malformed_json_string_falls_back_to_table_only(self):
        """A corrupt legacy blob shouldn't crash the read path — just log and
        fall back to whatever's in the table."""
        merged = merge_runs_table_with_legacy_blob([_run("r0")], "not valid json {")
        assert [r["run_id"] for r in merged] == ["r0"]


class TestDefensiveInputs:
    def test_non_dict_entries_in_legacy_are_skipped(self):
        legacy_runs = [_run("r0"), "corrupted", None, _run("r1")]
        merged = merge_runs_table_with_legacy_blob([], legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1"]

    def test_missing_run_id_in_legacy_is_skipped(self):
        legacy_runs = [_run("r0"), {"content": "no id"}, _run("r1")]
        merged = merge_runs_table_with_legacy_blob([], legacy_runs)
        assert [r["run_id"] for r in merged] == ["r0", "r1"]

    def test_missing_run_id_in_table_is_skipped(self):
        table_runs = [_run("r0"), {"content": "no id"}]
        legacy_runs = [_run("r0"), _run("r1")]
        merged = merge_runs_table_with_legacy_blob(table_runs, legacy_runs)
        # The malformed table row is dropped; r0 comes from table (conflict), r1 from blob.
        assert [r["run_id"] for r in merged] == ["r0", "r1"]


class TestNoDuplicates:
    """Same run_id must never appear twice in the merged output."""

    @pytest.mark.parametrize(
        "table_ids,legacy_ids",
        [
            (["r0", "r1", "r2"], ["r0", "r1", "r2"]),  # full overlap
            (["r1"], ["r0", "r1", "r2"]),
            (["r0", "r2"], ["r0", "r1", "r2", "r3"]),
            ([], ["r0", "r1"]),
            (["r0", "r1"], []),
        ],
    )
    def test_no_duplicate_run_ids(self, table_ids, legacy_ids):
        merged = merge_runs_table_with_legacy_blob(
            [_run(rid) for rid in table_ids],
            [_run(rid) for rid in legacy_ids],
        )
        result_ids = [r["run_id"] for r in merged]
        assert len(result_ids) == len(set(result_ids)), f"duplicate run_id detected: {result_ids}"
