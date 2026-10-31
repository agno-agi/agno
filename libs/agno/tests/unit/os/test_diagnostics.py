"""Diagnostics must report observed failures without making model calls."""

import asyncio
import time

import httpx
import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS
from agno.os.config import MCPConfig
from agno.scheduler import ScheduleManager


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("credentials", ["environment", "explicit", "mixed", "missing", "empty_secret"])
def test_slack_diagnostics_use_runtime_credentials(tmp_path, monkeypatch, use_async, credentials):
    import hashlib
    import hmac

    pytest.importorskip("slack_sdk")
    from agno.agent import Agent
    from agno.os.interfaces.slack import Slack, security
    from agno.tools.slack import SlackTools

    monkeypatch.setenv("SLACK_TOKEN", "environment-token")
    monkeypatch.setattr(security, "SLACK_SIGNING_SECRET", "environment-secret")
    options = {}
    if credentials == "explicit":
        options = {"token": "explicit-token", "signing_secret": "explicit-secret"}
    elif credentials == "mixed":
        options = {"token": "explicit-token"}
    elif credentials == "missing":
        monkeypatch.delenv("SLACK_TOKEN")
    elif credentials == "empty_secret":
        options = {"signing_secret": ""}
    agent = Agent(id="slack-agent")
    slack = Slack(agent=agent, **options)
    os = AgentOS(db=SqliteDb(db_file=str(tmp_path / "slack.db")), interfaces=[slack], telemetry=False)
    result = diagnostic(os, "interfaces", use_async)
    assert result.status == ("FAIL" if credentials in ("missing", "empty_secret") else "PASS")
    assert "environment-secret" not in result.detail and "explicit-secret" not in result.detail
    if result.status == "PASS":
        # Exercise actual credential resolution without making a Slack network call.
        assert SlackTools(token=slack.token).token == (slack.token or "environment-token")
        secret = slack.signing_secret if slack.signing_secret is not None else security.SLACK_SIGNING_SECRET
        timestamp = str(int(time.time()))
        signature = "v0=" + hmac.new(secret.encode(), f"v0:{timestamp}:{{}}".encode(), hashlib.sha256).hexdigest()
        assert security.verify_slack_signature(b"{}", timestamp, signature, signing_secret=slack.signing_secret)


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("invalid", [None, "duplicate", "missing"])
def test_component_diagnostics_respect_type_namespaces(tmp_path, use_async, invalid):
    from agno.agent import Agent
    from agno.team import Team
    from agno.workflow import Workflow

    agent = Agent(id="shared")
    os = AgentOS(
        db=SqliteDb(db_file=str(tmp_path / "ids.db")),
        agents=[agent],
        teams=[Team(id="shared", members=[])],
        workflows=[Workflow(id="shared", steps=[])],
        telemetry=False,
    )
    # Detect bad mutations after construction, while accepting ids shared across types.
    if invalid == "duplicate":
        os.agents.append(Agent(id="shared"))
    elif invalid == "missing":
        agent.id = None
    result = diagnostic(os, "components", use_async)
    assert result.status == ("PASS" if invalid is None else "FAIL")


def diagnostic(os, name, use_async, **kwargs):
    report = asyncio.run(os.arun_diagnostics(**kwargs)) if use_async else os.run_diagnostics(**kwargs)
    return next(check for check in report.checks if check.name == name)


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("async_db", [False, True])
def test_database_connection_failure_is_not_an_empty_session_list(tmp_path, async_db, use_async):
    # A directory is not a usable SQLite file. Table discovery masks this connection
    # failure and get_sessions returns an empty list, so a separate probe is needed.
    db = (AsyncSqliteDb if async_db else SqliteDb)(db_file=str(tmp_path))
    os = AgentOS(db=db, telemetry=False)
    try:
        result = diagnostic(os, "database", use_async)
        assert result.status == "FAIL"
        assert "OperationalError" in result.detail
        assert str(tmp_path) not in result.detail
    finally:
        if async_db:
            asyncio.run(db.close())
        else:
            db.close()


@pytest.mark.parametrize("async_db", [False, True])
def test_database_probe_accepts_unprovisioned_database_without_creating_tables(tmp_path, async_db):
    import sqlite3

    path = tmp_path / "empty.db"
    db = (AsyncSqliteDb if async_db else SqliteDb)(db_file=str(path))
    os = AgentOS(db=db, telemetry=False)
    try:
        result = diagnostic(os, "database", True)
        assert result.status == "PASS" and result.evidence == "live"
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    finally:
        if async_db:
            asyncio.run(db.close())
        else:
            db.close()


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("overdue", [False, True])
def test_scheduler_checks_schedules_after_first_page(tmp_path, use_async, overdue):
    db = SqliteDb(db_file=str(tmp_path / "schedules.db"))
    manager = ScheduleManager(db)
    schedule = manager.create(name="old-overdue", cron="0 0 * * *", endpoint="/unused")
    if overdue:
        db.update_schedule(schedule.id, next_run_at=int(time.time()) - 3600)
    table = db._get_table("schedules")
    with db.db_engine.begin() as connection:
        connection.execute(table.update().where(table.c.id == schedule.id).values(created_at=1))
    for index in range(100):
        manager.create(name=f"healthy-{index}", cron="0 0 * * *", endpoint="/unused")
    try:
        rows, total = db.get_schedules(enabled=True, page=2)
        assert total == 101 and rows[0]["id"] == schedule.id
        os = AgentOS(db=db, scheduler=True, telemetry=False)
        result = diagnostic(os, "scheduler", use_async)
        assert result.status == ("WARN" if overdue else "PASS")
        if overdue:
            assert "1 enabled schedules are overdue" in result.detail
    finally:
        manager.close()
        db.close()


def test_scheduler_does_not_claim_health_when_scan_is_incomplete(tmp_path, monkeypatch):
    db = SqliteDb(db_file=str(tmp_path / "schedules.db"))
    os = AgentOS(db=db, scheduler=True, telemetry=False)
    pages = []

    async def schedules(enabled, limit, page, raise_on_error):
        pages.append(page)
        return [{"next_run_at": int(time.time()) + 3600}] * limit, 100_000

    monkeypatch.setattr(db, "get_schedules", schedules)
    result = diagnostic(os, "scheduler", True)
    assert result.status == "WARN" and "incomplete" in result.detail.lower()
    assert 1 < len(pages) <= 100 and pages == list(range(1, len(pages) + 1))


def test_scheduler_reports_error_on_later_page(tmp_path, monkeypatch):
    db = SqliteDb(db_file=str(tmp_path / "schedules.db"))
    os = AgentOS(db=db, scheduler=True, telemetry=False)

    async def schedules(enabled, limit, page, raise_on_error):
        if page == 2:
            raise RuntimeError("private connection details")
        return [{"next_run_at": int(time.time()) + 3600}] * limit, 101

    monkeypatch.setattr(db, "get_schedules", schedules)
    result = diagnostic(os, "scheduler", True)
    assert result.status == "FAIL" and "RuntimeError" in result.detail
    assert "private" not in result.detail


@pytest.mark.parametrize("path,root_host", [("/mcp", None), ("/tools", None), ("/tools", "localhost")])
async def test_mcp_probe_reaches_configured_endpoint(tmp_path, monkeypatch, path, root_host):
    os = AgentOS(
        db=SqliteDb(db_file=str(tmp_path / "mcp.db")),
        mcp=MCPConfig(path=path, root_host=root_host, default_tools=True),
        telemetry=False,
    )
    app = os.get_app()
    original = httpx.AsyncClient
    requested = []

    async def record(request):
        requested.append(request.url.path)

    def local_client(*args, **kwargs):
        return original(*args, transport=httpx.ASGITransport(app=app), event_hooks={"request": [record]}, **kwargs)

    async with app.router.lifespan_context(app):
        monkeypatch.setattr(httpx, "AsyncClient", local_client)
        report = await os.arun_diagnostics(network_probe=True, public_url="http://localhost:7777")
    result = next(check for check in report.checks if check.name == "mcp")
    assert result.status == "PASS" and "HTTP 200" in result.detail
    assert requested == ["/" if root_host else path]


def test_mcp_probe_preserves_public_base_path(tmp_path, monkeypatch):
    os = AgentOS(
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        mcp=MCPConfig(path="/tools", default_tools=True),
        telemetry=False,
    )
    original = httpx.AsyncClient

    def respond(request):
        assert str(request.url) == "https://example.test/platform/tools"
        return httpx.Response(200)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *args, **kwargs: original(*args, transport=httpx.MockTransport(respond), **kwargs)
    )
    result = diagnostic(os, "mcp", False, network_probe=True, public_url="https://example.test/platform/")
    assert result.status == "PASS"
