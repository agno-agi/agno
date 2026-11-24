"""SurrealDB paging regressions, on the in-process engine or the server SURREALDB_TEST_URL names."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

surrealdb = pytest.importorskip("surrealdb")

from agno.db.surrealdb import metrics  # noqa: E402
from agno.db.utils import METRICS_BATCH_SIZE  # noqa: E402


@pytest.fixture
def run_day():
    url = os.getenv("SURREALDB_TEST_URL", "mem://")
    client = surrealdb.Surreal(url)
    if url != "mem://":
        client.signin({"username": "root", "password": "root"})
    client.use("pr_su_paging", f"pr_su_{uuid4().hex}")
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = [
        {
            "id": surrealdb.RecordID("page_runs", f"run_{index:06d}"),
            "run_id": f"run_{index:06d}",
            "session_id": "included",
            "created_at": start,
            "run_data": {"metrics": {"total_tokens": 1}},
        }
        for index in range(METRICS_BATCH_SIZE + 1)
    ]
    # The page-boundary key must be bound, not interpolated into SurrealQL.
    rows[METRICS_BATCH_SIZE - 1]["id"] = surrealdb.RecordID("page_runs", "run_000999'\\⟩")
    client.insert("page_runs", rows)
    client.insert(
        "page_runs",
        [
            {**rows[0], "id": surrealdb.RecordID("page_runs", "other"), "run_id": "other", "session_id": "other"},
            {
                **rows[0],
                "id": surrealdb.RecordID("page_runs", "old"),
                "run_id": "old",
                "created_at": start - timedelta(days=1),
            },
            {
                **rows[0],
                "id": surrealdb.RecordID("page_runs", "fork"),
                "run_id": "fork",
                "run_data": {"forked_from_session_id": "source"},
            },
        ],
    )
    try:
        yield client, start, [row["run_id"] for row in rows]
    finally:
        client.close()


def observe_pages(monkeypatch):
    original = metrics.utils.query
    pages = []

    def observe(client, query, variables, record_type):
        result = original(client, query, variables, record_type)
        pages.append((query, len(result)))
        return result

    monkeypatch.setattr(metrics.utils, "query", observe)
    return pages


def test_large_day_is_read_completely_in_bounded_pages(run_day, monkeypatch):
    client, start, expected = run_day
    pages = observe_pages(monkeypatch)
    runs = metrics.get_all_runs_for_component_metrics_calculation(
        client, "page_runs", start, start + timedelta(days=1), ["included"]
    )
    assert [run["run_id"] for run in runs] == expected
    assert [count for _, count in pages] == [METRICS_BATCH_SIZE, 1]
    assert all(f"LIMIT {METRICS_BATCH_SIZE}" in query for query, _ in pages)
    assert all("id" not in run for run in runs)


def test_stop_between_pages_does_not_return_a_partial_day(run_day, monkeypatch):
    client, start, _ = run_day
    pages = observe_pages(monkeypatch)
    runs = metrics.get_all_runs_for_component_metrics_calculation(
        client, "page_runs", start, start + timedelta(days=1), ["included"], should_stop=lambda: bool(pages)
    )
    assert runs is None
    assert [count for _, count in pages] == [METRICS_BATCH_SIZE]


def test_stop_during_paged_day_writes_no_partial_metrics(run_day, monkeypatch):
    from agno.db.surrealdb import SurrealDb
    from agno.session import AgentSession

    client, start, _ = run_day
    db = SurrealDb(
        client, os.getenv("SURREALDB_TEST_URL", "mem://"), {}, "pr_su_paging", "unused", runs_table="page_runs"
    )
    db.stop_metrics_refresh_on_read()
    db.upsert_session(AgentSession(session_id="included", agent_id="agent", created_at=int(start.timestamp())))
    client.query("UPDATE page_runs:old SET created_at=$future", {"future": start + timedelta(days=1)})
    original = metrics.utils.query
    page_sizes = []

    def observe(client, query, variables, record_type):
        result = original(client, query, variables, record_type)
        if ("FROM page_runs" in query or variables.get("table") == "page_runs") and "AS run_data" in query:
            page_sizes.append(len(result))
        return result

    monkeypatch.setattr(metrics.utils, "query", observe)
    assert db.calculate_metrics_dates(should_stop=lambda: bool(page_sizes)) is None
    assert page_sizes == [METRICS_BATCH_SIZE]
    assert client.query("SELECT * FROM agno_component_metrics") == []
    assert client.query("SELECT * FROM agno_aggregate_metrics") == []
