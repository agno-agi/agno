"""The /config queue block: capability discovery for queue-aware clients.

A chat tray cannot probe the admin-scoped /queue surface, so /config reports
EFFECTIVE background-run capabilities to any authenticated caller: whether
acceptance is durable, and whether same-session submissions actually run
FIFO (the serialize flag gates durable claims only - without a durable
queue it enforces nothing and must be reported false).
"""

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS


def _queue_block(tmp_path, queue=None):
    agent = Agent(id="cfg-agent", name="Cfg Agent", db=SqliteDb(db_file=str(tmp_path / "t.db")))
    app = AgentOS(agents=[agent], queue=queue, telemetry=False).get_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/config")
    assert resp.status_code == 200, resp.text
    return resp.json()["queue"]


class TestQueueCapabilities:
    def test_no_queue_config_reports_nothing_enabled(self, tmp_path):
        assert _queue_block(tmp_path) == {"durable": False, "queue_per_session": False}

    def test_bounded_only_queue_is_not_durable(self, tmp_path):
        block = _queue_block(tmp_path, QueueConfig(max_concurrency=4))
        assert block == {"durable": False, "queue_per_session": False}

    def test_durable_defaults_report_serialized(self, tmp_path):
        block = _queue_block(tmp_path, QueueConfig(durable=True, db=InMemoryQueueStore()))
        assert block == {"durable": True, "queue_per_session": True}

    def test_serialize_opt_out_is_visible(self, tmp_path):
        block = _queue_block(tmp_path, QueueConfig(durable=True, db=InMemoryQueueStore(), queue_per_session=False))
        assert block == {"durable": True, "queue_per_session": False}

    def test_serialize_flag_without_durable_reports_false(self, tmp_path):
        block = _queue_block(tmp_path, QueueConfig(max_concurrency=2, queue_per_session=True))
        assert block == {"durable": False, "queue_per_session": False}
