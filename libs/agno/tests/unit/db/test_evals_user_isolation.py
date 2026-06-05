"""Unit tests for per-user eval-run isolation on SqliteDb.

Locks in the contract that eval-run reads/writes/deletes scope by ``user_id``
when one is supplied (the OS passes the caller's id under user_isolation), and
stay global when it is ``None`` (single-user / admin). Mirrors the schedules /
metrics isolation contract from PR #8245.
"""

import pytest

from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.sqlite import SqliteDb


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "evals_isolation.db"))


def _make(db, run_id, user_id):
    # The eval framework persists the run; the OS sets the owner afterwards.
    db.create_eval_run(
        EvalRunRecord(
            run_id=run_id,
            eval_type=EvalType.ACCURACY,
            eval_data={"eval_status": "PASSED"},
            eval_input={},
        )
    )
    if user_id is not None:
        db.update_eval_run_user_id(run_id, user_id)


class TestScopedReads:
    def test_list_scoped_to_owner(self, db):
        _make(db, "r_alice", "alice")
        _make(db, "r_bob", "bob")

        alice_rows, alice_total = db.get_eval_runs(user_id="alice", deserialize=False)
        assert [r["run_id"] for r in alice_rows] == ["r_alice"]
        assert alice_total == 1

    def test_list_unscoped_sees_all(self, db):
        """user_id=None (admin / single-user) sees every run."""
        _make(db, "r_alice", "alice")
        _make(db, "r_bob", "bob")

        rows, total = db.get_eval_runs(deserialize=False)
        assert {r["run_id"] for r in rows} == {"r_alice", "r_bob"}
        assert total == 2

    def test_get_run_ownership(self, db):
        _make(db, "r_alice", "alice")

        assert db.get_eval_run("r_alice", user_id="alice") is not None
        assert db.get_eval_run("r_alice", user_id="bob") is None  # cross-user blocked
        assert db.get_eval_run("r_alice") is not None  # unscoped (admin) sees it


class TestScopedWrites:
    def test_delete_scoped(self, db):
        _make(db, "r_alice", "alice")
        _make(db, "r_bob", "bob")

        # bob cannot delete alice's run
        db.delete_eval_runs(["r_alice"], user_id="bob")
        assert db.get_eval_run("r_alice") is not None

        # alice can delete her own
        db.delete_eval_runs(["r_alice"], user_id="alice")
        assert db.get_eval_run("r_alice") is None
        # bob's run untouched
        assert db.get_eval_run("r_bob") is not None

    def test_rename_scoped(self, db):
        _make(db, "r_alice", "alice")

        # bob cannot rename alice's run -> returns None, name unchanged
        assert db.rename_eval_run("r_alice", "hacked", user_id="bob") is None
        assert db.get_eval_run("r_alice", deserialize=False)["name"] != "hacked"  # type: ignore

        # alice can rename her own
        renamed = db.rename_eval_run("r_alice", "my eval", user_id="alice")
        assert renamed is not None
        assert db.get_eval_run("r_alice", deserialize=False)["name"] == "my eval"  # type: ignore


class TestOwnerStamping:
    def test_update_eval_run_user_id(self, db):
        """The OS stamps the owner after the eval framework persists an unowned run."""
        _make(db, "r_new", None)  # framework writes with no owner
        assert db.get_eval_run("r_new", deserialize=False)["user_id"] is None  # type: ignore

        db.update_eval_run_user_id("r_new", "alice")

        assert db.get_eval_run("r_new", user_id="alice") is not None
        assert db.get_eval_run("r_new", user_id="bob") is None


class TestNoCrossLeak:
    def test_totals_are_per_user(self, db):
        for i in range(3):
            _make(db, f"a{i}", "alice")
        for i in range(2):
            _make(db, f"b{i}", "bob")

        _, alice_total = db.get_eval_runs(user_id="alice", deserialize=False)
        _, bob_total = db.get_eval_runs(user_id="bob", deserialize=False)
        _, grand_total = db.get_eval_runs(deserialize=False)
        assert (alice_total, bob_total, grand_total) == (3, 2, 5)
