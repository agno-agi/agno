from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import Engine

from agno.db.sqlite.sqlite import SqliteDb


@pytest.fixture
def mock_pg_engine():
    engine = Mock(spec=Engine)
    engine.url = "postgresql://localhost/test"
    return engine


class TestSqliteDbFromDictRoundTrip:
    def test_v25_fields_survive_roundtrip(self):
        original = SqliteDb(
            db_file="/tmp/test.db",
            session_table="s",
            learnings_table="custom_learnings",
            approvals_table="custom_approvals",
            schedules_table="custom_schedules",
            schedule_runs_table="custom_schedule_runs",
        )

        restored = SqliteDb.from_dict(original.to_dict())

        assert restored.learnings_table_name == "custom_learnings"
        assert restored.approvals_table_name == "custom_approvals"
        assert restored.schedules_table_name == "custom_schedules"
        assert restored.schedule_runs_table_name == "custom_schedule_runs"

    def test_all_fields_survive_roundtrip(self):
        original = SqliteDb(
            db_file="/tmp/test.db",
            session_table="s",
            culture_table="c",
            memory_table="m",
            metrics_table="met",
            eval_table="e",
            knowledge_table="k",
            traces_table="t",
            spans_table="sp",
            versions_table="v",
            components_table="comp",
            component_configs_table="cc",
            component_links_table="cl",
            learnings_table="l",
            schedules_table="sch",
            schedule_runs_table="sr",
            approvals_table="a",
        )

        serialized = original.to_dict()
        restored = SqliteDb.from_dict(serialized)

        assert restored.session_table_name == "s"
        assert restored.culture_table_name == "c"
        assert restored.memory_table_name == "m"
        assert restored.metrics_table_name == "met"
        assert restored.eval_table_name == "e"
        assert restored.knowledge_table_name == "k"
        assert restored.trace_table_name == "t"
        assert restored.span_table_name == "sp"
        assert restored.versions_table_name == "v"
        assert restored.components_table_name == "comp"
        assert restored.component_configs_table_name == "cc"
        assert restored.component_links_table_name == "cl"
        assert restored.learnings_table_name == "l"
        assert restored.schedules_table_name == "sch"
        assert restored.schedule_runs_table_name == "sr"
        assert restored.approvals_table_name == "a"

    def test_defaults_used_when_fields_absent(self):
        restored = SqliteDb.from_dict({"db_file": "/tmp/test.db"})

        assert restored.learnings_table_name == "agno_learnings"
        assert restored.approvals_table_name == "agno_approvals"
        assert restored.schedules_table_name == "agno_schedules"
        assert restored.schedule_runs_table_name == "agno_schedule_runs"


class TestPostgresDbFromDictRoundTrip:
    @patch("agno.db.postgres.postgres.create_engine")
    def test_v25_fields_survive_roundtrip(self, mock_create_engine, mock_pg_engine):
        mock_create_engine.return_value = mock_pg_engine

        from agno.db.postgres.postgres import PostgresDb

        original = PostgresDb(
            db_url="postgresql://localhost/test",
            learnings_table="custom_learnings",
            approvals_table="custom_approvals",
            schedules_table="custom_schedules",
            schedule_runs_table="custom_schedule_runs",
        )

        serialized = original.to_dict()
        restored = PostgresDb.from_dict(serialized)

        assert restored.learnings_table_name == "custom_learnings"
        assert restored.approvals_table_name == "custom_approvals"
        assert restored.schedules_table_name == "custom_schedules"
        assert restored.schedule_runs_table_name == "custom_schedule_runs"
