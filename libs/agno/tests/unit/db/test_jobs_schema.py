"""Unit tests for the job queue job schema and durability config."""

import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.config import QueueConfig


class TestQueuedJob:
    def test_defaults(self):
        job = QueuedJob(id="r1", component_type="agent", component_id="a1", session_id="s1")
        assert job.status == "queued"
        assert job.attempt == 0
        assert job.max_attempts == 1
        assert job.available_at is not None
        assert job.created_at is not None

    def test_round_trip(self):
        job = QueuedJob(
            id="r1",
            component_type="workflow",
            component_id="w1",
            session_id="s1",
            payload={"input": "hello"},
            idempotency_key="key-1",
        )
        restored = QueuedJob.from_dict(job.to_dict())
        assert restored == job

    def test_from_dict_filters_unknown_keys(self):
        data = QueuedJob(id="r1", component_type="agent", component_id="a1", session_id="s1").to_dict()
        data["unknown_column"] = "x"
        assert QueuedJob.from_dict(data).id == "r1"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            QueuedJob(id="r1", component_type="agent", component_id="a1", session_id="s1", status="nope")


class TestQueueConfigDurability:
    def test_defaults_not_durable(self):
        config = QueueConfig()
        assert config.durable is False
        assert config.db is None
        assert config.max_attempts == 1

    def test_db_without_durable_raises(self):
        with pytest.raises(ValueError):
            QueueConfig(db=object())

    def test_db_with_durable_valid(self):
        store = object()
        config = QueueConfig(durable=True, db=store)
        assert config.db is store
