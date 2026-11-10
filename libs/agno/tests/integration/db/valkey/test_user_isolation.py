"""Integration tests for per-user isolation on ValkeyDb metrics, knowledge and eval runs.

Requires a running Valkey instance on localhost:6379.
Run with: pytest libs/agno/tests/integration/db/valkey/test_user_isolation.py -v
"""

import time
from typing import Optional

from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.valkey.valkey import ValkeyDb
from agno.session import AgentSession


def _seed_sessions(valkey_db: ValkeyDb) -> None:
    for session_id, user_id in [
        ("iso_s1", "user_a"),
        ("iso_s2", "user_a"),
        ("iso_s3", "user_b"),
        ("iso_s4", None),
    ]:
        valkey_db.upsert_session(
            AgentSession(
                session_id=session_id,
                agent_id="agent_1",
                user_id=user_id,
                created_at=int(time.time()),
            )
        )


class TestMetricsUserIsolation:
    def test_buckets_per_user(self, valkey_db: ValkeyDb):
        _seed_sessions(valkey_db)
        results = valkey_db.calculate_metrics()

        assert results is not None
        by_user = {record["user_id"]: record for record in results}
        assert set(by_user) == {"user_a", "user_b", ""}
        assert by_user["user_a"]["agent_sessions_count"] == 2
        assert by_user["user_b"]["agent_sessions_count"] == 1
        assert by_user[""]["agent_sessions_count"] == 1
        assert by_user["user_a"]["users_count"] == 1
        assert by_user[""]["users_count"] == 0
        assert by_user[""]["id"].endswith("__daily")

    def test_recalculation_updates_same_records(self, valkey_db: ValkeyDb):
        _seed_sessions(valkey_db)
        first = valkey_db.calculate_metrics()
        second = valkey_db.calculate_metrics()

        assert first is not None and second is not None
        assert sorted(record["id"] for record in first) == sorted(record["id"] for record in second)
        metrics, _ = valkey_db.get_metrics()
        assert len(metrics) == 3

    def test_get_metrics_user_filter_and_sentinel_mapping(self, valkey_db: ValkeyDb):
        _seed_sessions(valkey_db)
        valkey_db.calculate_metrics()

        user_a_metrics, _ = valkey_db.get_metrics(user_id="user_a")
        assert len(user_a_metrics) == 1
        assert user_a_metrics[0]["user_id"] == "user_a"

        all_metrics, _ = valkey_db.get_metrics()
        unowned = [metric for metric in all_metrics if metric["user_id"] is None]
        assert len(unowned) == 1


class TestKnowledgeVisibility:
    def _store(self, valkey_db: ValkeyDb, id: str, user_id: Optional[str] = None) -> None:
        valkey_db.upsert_knowledge_content(KnowledgeRow(id=id, name=f"doc {id}", description="test doc"))
        if user_id is not None:
            # KnowledgeRow gains a user_id column with the isolation work;
            # stamp the owner directly the way the future schema stores it.
            record = valkey_db._get_record("knowledge", id)
            record["user_id"] = user_id
            valkey_db._store_record("knowledge", id, record)

    def test_unowned_rows_visible_to_everyone(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "k_shared")

        assert valkey_db.get_knowledge_content("k_shared", user_id="user_a") is not None
        assert valkey_db.get_knowledge_content("k_shared") is not None

    def test_owned_row_hidden_from_other_users(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "k_a", user_id="user_a")

        assert valkey_db.get_knowledge_content("k_a", user_id="user_b") is None
        assert valkey_db.get_knowledge_content("k_a", user_id="user_a") is not None
        assert valkey_db.get_knowledge_content("k_a") is not None

    def test_get_knowledge_contents_scoped(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "k_shared")
        self._store(valkey_db, "k_a", user_id="user_a")
        self._store(valkey_db, "k_b", user_id="user_b")

        rows, total = valkey_db.get_knowledge_contents(user_id="user_a")
        assert total == 2
        assert {row.id for row in rows} == {"k_shared", "k_a"}

        rows, total = valkey_db.get_knowledge_contents()
        assert total == 3

    def test_delete_scoped_to_owner(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "k_a", user_id="user_a")

        valkey_db.delete_knowledge_content("k_a", user_id="user_b")
        assert valkey_db.get_knowledge_content("k_a") is not None

        valkey_db.delete_knowledge_content("k_a", user_id="user_a")
        assert valkey_db.get_knowledge_content("k_a") is None


class TestEvalRunsUserIsolation:
    def _store(self, valkey_db: ValkeyDb, run_id: str, user_id: Optional[str] = None) -> None:
        # The eval framework persists the run; the OS sets the owner afterwards.
        valkey_db.create_eval_run(
            EvalRunRecord(
                run_id=run_id,
                eval_type=EvalType.ACCURACY,
                eval_data={"eval_status": "PASSED"},
                eval_input={},
            )
        )
        if user_id is not None:
            valkey_db.update_eval_run_user_id(run_id, user_id)

    def test_unowned_runs_visible_to_everyone(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "e_shared")

        assert valkey_db.get_eval_run("e_shared") is not None
        assert valkey_db.get_eval_run("e_shared", user_id="user_a") is None

    def test_owned_run_hidden_from_other_users(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "e_a", user_id="user_a")

        assert valkey_db.get_eval_run("e_a", user_id="user_b") is None
        assert valkey_db.get_eval_run("e_a", user_id="user_a") is not None
        assert valkey_db.get_eval_run("e_a") is not None

    def test_get_eval_runs_scoped(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "e_shared")
        self._store(valkey_db, "e_a", user_id="user_a")
        self._store(valkey_db, "e_b", user_id="user_b")

        rows, total = valkey_db.get_eval_runs(user_id="user_a", deserialize=False)
        assert total == 1
        assert {row["run_id"] for row in rows} == {"e_a"}

        rows, total = valkey_db.get_eval_runs(deserialize=False)
        assert total == 3

    def test_rename_scoped_to_owner(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "e_a", user_id="user_a")

        assert valkey_db.rename_eval_run("e_a", "hacked", user_id="user_b") is None
        renamed = valkey_db.rename_eval_run("e_a", "mine", user_id="user_a")
        assert renamed is not None and renamed.name == "mine"

    def test_delete_scoped_to_owner(self, valkey_db: ValkeyDb):
        self._store(valkey_db, "e_a", user_id="user_a")

        valkey_db.delete_eval_runs(["e_a"], user_id="user_b")
        assert valkey_db.get_eval_run("e_a") is not None

        valkey_db.delete_eval_runs(["e_a"], user_id="user_a")
        assert valkey_db.get_eval_run("e_a") is None
