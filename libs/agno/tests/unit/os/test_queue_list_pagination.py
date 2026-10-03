"""GET /queue/jobs pagination and sorting.

The list endpoint follows the house list-API contract (memory, knowledge,
service accounts): limit/page/sort_by/sort_order params and a
PaginatedResponse body ({data, meta}) instead of a bare list, so the ops UI
can page the table and reuse the shared pagination components.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.routers.job_queue import get_queue_router


@pytest.fixture()
def harness():
    app = FastAPI()
    app.include_router(get_queue_router(SimpleNamespace()))
    store = InMemoryQueueStore()
    app.state.queue_worker = SimpleNamespace(store=store, config=QueueConfig(durable=True))
    return SimpleNamespace(store=store, client=TestClient(app, raise_server_exceptions=False))


def seed(store, job_id, status="queued", created_at=None, attempt=0, session_id="s1", user_id=None):
    job = QueuedJob(
        id=job_id,
        component_type="agent",
        component_id="a1",
        session_id=session_id,
        user_id=user_id,
        payload={"input": "hi"},
        status=status,
        attempt=attempt,
        created_at=created_at,
    ).to_dict()
    store._jobs[job_id] = job


class TestListJobsPagination:
    def test_paginated_shape_and_page_walk(self, harness):
        for i in range(5):
            seed(harness.store, f"j{i}", created_at=1000 + i)

        resp = harness.client.get("/queue/jobs", params={"limit": 2, "page": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert [j["id"] for j in body["data"]] == ["j4", "j3"]
        assert body["meta"]["page"] == 1
        assert body["meta"]["limit"] == 2
        assert body["meta"]["total_count"] == 5
        assert body["meta"]["total_pages"] == 3

        resp = harness.client.get("/queue/jobs", params={"limit": 2, "page": 3})
        assert [j["id"] for j in resp.json()["data"]] == ["j0"]

    def test_sorting_and_status_filter(self, harness):
        seed(harness.store, "j0", status="failed", created_at=1000, attempt=3)
        seed(harness.store, "j1", status="failed", created_at=1001, attempt=1)
        seed(harness.store, "j2", status="completed", created_at=1002)

        resp = harness.client.get("/queue/jobs", params={"status": "failed", "sort_order": "asc"})
        body = resp.json()
        assert [j["id"] for j in body["data"]] == ["j0", "j1"]
        assert body["meta"]["total_count"] == 2

        resp = harness.client.get("/queue/jobs", params={"sort_by": "attempt", "sort_order": "desc"})
        assert [j["attempt"] for j in resp.json()["data"]] == [3, 1, 0]

    def test_multi_status_filter(self, harness):
        seed(harness.store, "j0", status="failed", created_at=1000)
        seed(harness.store, "j1", status="cancelled", created_at=1001)
        seed(harness.store, "j2", status="completed", created_at=1002)
        seed(harness.store, "j3", status="queued", created_at=1003)

        # The requeueable set: any of several statuses via a repeated param
        resp = harness.client.get("/queue/jobs", params={"status": ["failed", "cancelled"]})
        body = resp.json()
        assert {j["id"] for j in body["data"]} == {"j0", "j1"}
        assert body["meta"]["total_count"] == 2

        # One invalid value among several rejects the request
        resp = harness.client.get("/queue/jobs", params={"status": ["failed", "bogus"]})
        assert resp.status_code == 400

    def test_multi_session_and_status_filters_compose(self, harness):
        seed(harness.store, "j0", status="queued", session_id="s1")
        seed(harness.store, "j1", status="running", session_id="s2")
        seed(harness.store, "j2", status="paused", session_id="s3")
        seed(harness.store, "j3", status="completed", session_id="s1")

        resp = harness.client.get(
            "/queue/jobs",
            params={"session_id": ["s1", "s2"], "status": ["queued", "running", "paused"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert {job["id"] for job in body["data"]} == {"j0", "j1"}
        assert body["meta"]["total_count"] == 2

    def test_invalid_params_rejected(self, harness):
        assert harness.client.get("/queue/jobs", params={"status": "bogus"}).status_code == 400
        assert harness.client.get("/queue/jobs", params={"limit": 0}).status_code == 422
        assert harness.client.get("/queue/jobs", params={"limit": 1001}).status_code == 422
        assert harness.client.get("/queue/jobs", params={"page": 0}).status_code == 422
        # Unknown sort fields are silently ignored, not rejected
        assert harness.client.get("/queue/jobs", params={"sort_by": "nope"}).status_code == 200
