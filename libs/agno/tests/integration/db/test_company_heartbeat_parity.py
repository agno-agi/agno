"""Sources and durable evidence deduplication on all four supported SQL adapters."""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.agent import Agent
from agno.company import Product, Source
from agno.company.bootstrap import arehydrate_product
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.registry import Registry


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def heartbeat(request, tmp_path):
    schema = "heartbeat_" + uuid4().hex
    if "postgres" in request.param:
        cls = AsyncPostgresDb if request.param.startswith("async") else PostgresDb
        db = cls(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    else:
        cls = AsyncSqliteDb if request.param.startswith("async") else SqliteDb
        db = cls(db_file=str(tmp_path / "heartbeat.db"))
    registry = Registry(agents=[Agent(id="reader", telemetry=False)])
    manager = (
        AsyncCompanyManager(db, registry=registry)
        if isinstance(db, AsyncBaseDb)
        else CompanyManager(db, registry=registry)
    )

    async def call(method, /, *args, **kwargs):
        fn = getattr(manager, method)
        return (
            await fn(*args, **kwargs)
            if inspect.iscoroutinefunction(fn)
            else await asyncio.to_thread(fn, *args, **kwargs)
        )

    yield db, manager, call
    if isinstance(db, AsyncBaseDb):
        await db.close()
    else:
        db.close()
    if "postgres" in request.param:
        cleanup = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
        with cleanup.db_engine.begin() as conn:
            conn.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
        cleanup.close()


@pytest.mark.asyncio
async def test_evidence_repeat_failure_completion_and_product_scope(heartbeat, tmp_path):
    db, manager, call = heartbeat
    path = tmp_path / "release.md"
    path.write_text("# Release\nA new feature.\n")
    product = await call("create", name="Docs")
    product_project = await call("create_project", product_id=product["id"], name="Work")
    source = await call(
        "create_source", product_id=product["id"], type="markdown", reference=str(path), credential_ref="DOCS_TOKEN"
    )
    proposal = dict(
        title="Document the API",
        brief="Explain the released capability",
        proposal_key="api-docs",
        evidence_links=[path.as_uri()],
    )
    proposal["evidence_hashes"] = {
        item["link"]: item["content_hash"] for item in await call("read_source", source["id"], "observe")
    }
    first = await call(
        "intake", source_id=source["id"], run_id="first-run", proposal=proposal, project_id=product_project["id"]
    )
    assert first["title"] == proposal["title"] and first["brief"] == proposal["brief"]
    assert "content" not in first["evidence"][0]
    assert first["status"] == "backlog"
    assert first["evidence"][0]["run_id"] == "first-run"
    assert first["evidence"][0]["content_hash"]
    repeat = await call(
        "intake", source_id=source["id"], run_id="repeat-run", proposal=proposal, project_id=product_project["id"]
    )
    assert repeat["id"] == first["id"]
    (tmp_path / "unrelated.md").write_text("A sibling is not the configured Source")
    path.unlink()
    with pytest.raises(ValueError, match="Source root is unavailable"):
        await call(
            "intake", source_id=source["id"], run_id="failed-run", proposal=proposal, project_id=product_project["id"]
        )
    assert (await call("list_tasks", product_id=product["id"]))[1] == 1
    path.write_text("# Release\nA new feature.\n")
    for target in ("ready", "in_progress", "in_review", "done"):
        kwargs = {"executor_type": "agent", "executor_id": "reader"} if target == "ready" else {}
        await call("transition_task", task_id=first["id"], target=target, reason="human review", **kwargs)
    after = await call(
        "intake", source_id=source["id"], run_id="after-completion", proposal=proposal, project_id=product_project["id"]
    )
    assert after["id"] == first["id"] and after["status"] == "done"
    await call("delete_task", first["id"])
    assert (
        await call(
            "intake", source_id=source["id"], run_id="after-delete", proposal=proposal, project_id=product_project["id"]
        )
    )["id"] == first["id"]
    other = await call("create", name="Other")
    other_project = await call("create_project", product_id=other["id"], name="Work")
    second_source = await call("create_source", product_id=other["id"], type="markdown", reference=str(path))
    assert (
        await call(
            "intake",
            source_id=second_source["id"],
            run_id="other-product",
            proposal=proposal,
            project_id=other_project["id"],
        )
    )["id"] != first["id"]
    path.write_text("Changed evidence")
    with pytest.raises(ValueError, match="evidence changed"):
        await call(
            "intake", source_id=source["id"], run_id="stale", proposal=proposal, project_id=product_project["id"]
        )
    proposal["evidence_hashes"] = {
        item["link"]: item["content_hash"] for item in await call("read_source", source["id"], "reread")
    }
    assert (
        await call(
            "intake", source_id=source["id"], run_id="changed", proposal=proposal, project_id=product_project["id"]
        )
    )["id"] == first["id"]
    with pytest.raises(ValueError, match="Proposal evidence"):
        await call(
            "intake",
            source_id=source["id"],
            run_id="forged",
            proposal={**proposal, "evidence_links": ["https://unread.test"]},
            project_id=product_project["id"],
        )


@pytest.mark.asyncio
async def test_source_paging_soft_delete_and_restart(heartbeat, tmp_path):
    db, manager, call = heartbeat
    declaration = Product(name="Declared", sources=[Source(type="markdown", reference=str(tmp_path / "x.md"))])
    first = await arehydrate_product(db, declaration)
    await call("update", first["id"], purpose="Human edit")
    again = await arehydrate_product(db, declaration)
    assert again["purpose"] == "Human edit"
    sources, total = await call("list_sources", product_id=first["id"], limit=1)
    assert total == 1
    assert (await call("list_sources", user_id="other"))[1] == 0
    await call("delete_source", sources[0]["id"])
    assert (await call("list_sources"))[1] == 0
    assert (await call("list_sources", include_deleted=True))[1] == 1
    await arehydrate_product(db, declaration)
    assert (await call("list_sources"))[1] == 0
    await call("restore_source", sources[0]["id"])
    assert (await call("list_sources"))[1] == 1


@pytest.mark.asyncio
async def test_setup_race_loser_joins_the_winners_product(heartbeat, tmp_path, monkeypatch):
    db, _, call = heartbeat
    original = db.create_product
    winner = Product(id="company-setup", name="First owner", user_id="alice")

    async def raced(data):
        # Another setup request wins between our empty read and insert.
        monkeypatch.setattr(db, "create_product", original)
        await arehydrate_product(db, winner)
        return await original(data)

    def raced_sync(data):
        monkeypatch.setattr(db, "create_product", original)
        original({**data, "user_id": "alice"})
        return original(data)

    monkeypatch.setattr(db, "create_product", raced if isinstance(db, AsyncBaseDb) else raced_sync)
    loser = Product(
        id="company-setup",
        name="Other owner",
        user_id="bob",
        sources=[Source(type="markdown", reference=str(tmp_path / "private.md"))],
    )
    # Setup is not owner-scoped: the loser adds its declarations and the winner stays the owner.
    await arehydrate_product(db, loser)
    assert (await call("list_sources"))[1] == 1
    assert (await call("get", "company-setup"))["user_id"] == "alice"


def test_website_uses_existing_reader_and_hashes_extracted_content(monkeypatch):
    from agno.company.sources import read_source
    from agno.utils.string import hash_string_sha256

    requested = []

    def page(url, **kwargs):
        requested.append((url, kwargs))
        return url, b"<nav>Navigation</nav><main>Released API</main><a href='/other'>Next</a>"

    monkeypatch.setattr("agno.knowledge.reader.utils.public_fetch.fetch_public_page", page)
    monkeypatch.setattr("agno.knowledge.reader.website_reader.WebsiteReader.delay", lambda self: None)
    monkeypatch.setenv("DOCS_SECRET", "must-not-leave-diagnostics")
    source = dict(id="web", type="website", reference="https://docs.example.test/release", credential_ref="DOCS_SECRET")
    evidence = read_source(source, "web-run")
    assert evidence[0]["content"] == "Released API"
    assert evidence[0]["content_hash"] == hash_string_sha256("Released API")
    assert evidence[0]["run_id"] == "web-run"
    assert evidence[0]["link"] == source["reference"]
    assert len(requested) == 1 and "must-not-leave-diagnostics" not in str(requested)


@pytest.mark.asyncio
async def test_summary_wiki_and_configured_transport(heartbeat, monkeypatch):
    db, manager, call = heartbeat
    delivery = AsyncMock()
    monkeypatch.setattr("agno.company.summary.adeliver_summary", delivery)
    product = await call("create", name="Docs", metadata={"summary": {"interface": "slack", "destination": "docs"}})
    result = await call(
        "summarize",
        product_id=product["id"],
        run_id="summary-run",
        interfaces=[SimpleNamespace(type="slack")],
        narrative="The Product is quiet; no work awaits review.",
    )
    assert result["delivered"] is True and result["quiet"] is True
    assert "Quiet successful check" in (await call("read_wiki", product["id"], result["path"])).content
    assert delivery.await_count == 1
    await call(
        "summarize",
        product_id=product["id"],
        run_id="summary-run",
        interfaces=[],
        narrative="The Product is quiet; no work awaits review.",
    )
    assert delivery.await_count == 1
    again = await call(
        "summarize",
        product_id=product["id"],
        run_id="second-summary",
        interfaces=[],
        narrative="The Product is quiet; no work awaits review.",
    )
    assert again["path"] == result["path"] == "summary.md"
    assert delivery.await_count == 2
    await call(
        "summarize",
        product_id=product["id"],
        run_id="summary-run",
        interfaces=[],
        narrative="The Product is quiet; no work awaits review.",
    )
    assert delivery.await_count == 2
    delivery.side_effect = RuntimeError("Transport unavailable")
    with pytest.raises(RuntimeError, match="Transport unavailable"):
        await call(
            "summarize",
            product_id=product["id"],
            run_id="retry-summary",
            interfaces=[],
            narrative="The Product is quiet; no work awaits review.",
        )
    delivery.side_effect = None
    await call(
        "summarize",
        product_id=product["id"],
        run_id="retry-summary",
        interfaces=[],
        narrative="The Product is quiet; no work awaits review.",
    )
    assert delivery.await_count == 4


@pytest.mark.asyncio
async def test_concurrent_evidence_and_routine_linking(heartbeat, tmp_path):
    from agno.company.execution import _call

    db, manager, call = heartbeat
    product = await call("create", name="Concurrent", metadata={"human": "keep"})
    product_project = await call("create_project", product_id=product["id"], name="Work")
    path = tmp_path / "race.md"
    path.write_text("Same evidence")
    source = await call("create_source", product_id=product["id"], type="markdown", reference=str(path))
    # Initialize the shared tables before racing independent transactions.
    proposal = dict(title="Fix API docs", brief="Describe the API", proposal_key="seed", evidence_links=[path.as_uri()])
    proposal["evidence_hashes"] = {
        item["link"]: item["content_hash"] for item in await call("read_source", source["id"], "observe")
    }
    await call("intake", source_id=source["id"], run_id="seed", proposal=proposal, project_id=product_project["id"])
    proposal["proposal_key"] = "another-issue"
    path.write_text("New evidence")
    proposal["evidence_hashes"] = {
        item["link"]: item["content_hash"] for item in await call("read_source", source["id"], "reread")
    }
    results = await asyncio.gather(
        *(
            call(
                "intake",
                source_id=source["id"],
                run_id="run-" + str(i),
                proposal=proposal,
                project_id=product_project["id"],
            )
            for i in range(6)
        )
    )
    assert len({result["id"] for result in results}) == 1
    assert (await call("list_tasks", product_id=product["id"]))[1] == 2
    await asyncio.gather(*(_call(db, "add_product_routine", product["id"], "schedule-" + str(i)) for i in range(6)))
    metadata = (await call("get", product["id"]))["metadata"]
    assert metadata["human"] == "keep" and len(metadata["routine_ids"]) == 6


@pytest.mark.asyncio
async def test_git_provider_exclusions_and_failed_batch(heartbeat, tmp_path):
    db, manager, call = heartbeat
    root = tmp_path / "repo"
    root.mkdir()
    (root / "readme.md").write_text("Public content")
    (root / ".env").write_text("SECRET=never-in-evidence")
    product = await call("create", name="Repository")
    product_project = await call("create_project", product_id=product["id"], name="Work")
    source = await call("create_source", product_id=product["id"], type="git", reference=str(root))
    evidence = await call("read_source", source["id"], "read")
    assert len(evidence) == 1 and "never-in-evidence" not in str(evidence)
    (root / "image.png").write_bytes(b"\x89PNG\xff")
    (root / "large.txt").write_text("x\n" * 100001)
    evidence = await call("read_source", source["id"], "mixed")
    assert len(evidence) == 1
    assert set(evidence[0]["skipped_paths"]) == {"image.png", "large.txt"}
    selected = await call(
        "create_source", product_id=product["id"], type="git", reference=str(root), config={"paths": ["image.png"]}
    )
    with pytest.raises(ValueError, match="Source read failed"):
        await call("read_source", selected["id"], "explicit")
    invalid = await call(
        "create_source",
        product_id=product["id"],
        type="git",
        reference=str(root),
        config={"paths": ["readme.md", ".env"]},
    )
    with pytest.raises(ValueError, match="Source read failed"):
        await call(
            "intake",
            source_id=invalid["id"],
            run_id="failed",
            proposal=dict(
                title="Proposal",
                brief="Never persisted",
                proposal_key="invalid",
                evidence_links=[(root / ".env").as_uri()],
                evidence_hashes={(root / ".env").as_uri(): "unavailable"},
            ),
            project_id=product_project["id"],
        )
    assert (await call("list_tasks"))[1] == 0


@pytest.mark.asyncio
async def test_intake_requires_a_decision_and_only_stores_selected_evidence(heartbeat, tmp_path):
    _, _, call = heartbeat
    root = tmp_path / "docs"
    root.mkdir()
    for index in range(5):
        (root / (str(index) + ".md")).write_text("External business data " + str(index))
    product = await call("create", name="Selective intake")
    product_project = await call("create_project", product_id=product["id"], name="Work")
    source = await call("create_source", product_id=product["id"], type="git", reference=str(root))
    evidence = await call("read_source", source["id"], "scan")
    assert len(evidence) == 5 and (await call("list_tasks", product_id=product["id"]))[1] == 0
    proposal = dict(
        title="Fix the release guide",
        brief="Explain the newly released options",
        proposal_key="release-options",
        evidence_links=[evidence[0]["link"], evidence[1]["link"]],
        evidence_hashes={item["link"]: item["content_hash"] for item in evidence[:2]},
    )
    task = await call(
        "intake", source_id=source["id"], run_id="proposal", proposal=proposal, project_id=product_project["id"]
    )
    assert len(task["evidence"]) == 2
    assert "External business data" not in str(task)
    (root / "0.md").write_text("Changed business data")
    evidence = await call("read_source", source["id"], "next-scan")
    proposal["evidence_hashes"] = {item["link"]: item["content_hash"] for item in evidence[:2]}
    assert (await call("list_tasks", product_id=product["id"]))[1] == 1
    repeated = await call(
        "intake",
        source_id=source["id"],
        run_id="again",
        proposal={**proposal, "title": "Clarify the guide"},
        project_id=product_project["id"],
    )
    assert repeated["id"] == task["id"]


@pytest.mark.asyncio
async def test_summary_preserves_narrative_changes_and_failure_detail(heartbeat, monkeypatch):
    from agno.company.execution import _call

    db, _, call = heartbeat
    delivery = AsyncMock()
    monkeypatch.setattr("agno.company.summary.adeliver_summary", delivery)
    product = await call(
        "create", name="Reports", metadata={"summary": {"interface": "slack", "destination": "reports"}}
    )
    product_project = await call("create_project", product_id=product["id"], name="Work")
    task = await call("create_task", product_id=product["id"], title="Release docs", project_id=product_project["id"])
    assert task["origin"] == "human"
    await call(
        "summarize",
        product_id=product["id"],
        run_id="before",
        interfaces=[],
        narrative="The release guide is proposed.",
    )
    await call(
        "transition_task",
        task_id=task["id"],
        target="ready",
        reason="Accepted",
        executor_type="agent",
        executor_id="reader",
    )
    task = await call("get_task", task["id"])
    started = await _call(db, "start_task_run", task["id"], 1, task["transitions"])
    await _call(
        db,
        "complete_task_run",
        task["id"],
        started["job_id"],
        {"status": "ERROR", "error": "Documentation build failed"},
    )
    await call(
        "summarize",
        product_id=product["id"],
        run_id="after",
        interfaces=[],
        narrative="The accepted guide failed its build; investigate the broken link.",
    )
    page = (await call("read_wiki", product["id"], "summary.md")).content
    assert "The accepted guide failed its build" in page
    assert "backlog → in_progress" in page
    assert "Documentation build failed" in page
    assert "## Failed Tasks" in page
    assert "Documentation build failed" in delivery.await_args.args[3]
    assert "Company summary snapshot" not in delivery.await_args.args[3]
    await call(
        "summarize",
        product_id=product["id"],
        run_id="unchanged",
        interfaces=[],
        narrative="The same build failure still needs attention.",
    )
    assert (
        "No Task changes since the last delivered summary."
        in (await call("read_wiki", product["id"], "summary.md")).content
    )


@pytest.mark.asyncio
async def test_intake_rejects_stale_and_incomplete_observed_hashes(heartbeat, tmp_path):
    _, _, call = heartbeat
    path = tmp_path / "issue.md"
    path.write_text("Authentication example is broken")
    product = await call("create", name="Observed evidence")
    product_project = await call("create_project", product_id=product["id"], name="Work")
    source = await call("create_source", product_id=product["id"], type="markdown", reference=str(path))
    observed = (await call("read_source", source["id"], "observation"))[0]
    proposal = dict(
        title="Fix example",
        brief="Correct the authentication example",
        proposal_key="auth-example",
        evidence_links=[observed["link"]],
        evidence_hashes={observed["link"]: observed["content_hash"]},
    )
    path.write_text("Authentication example was fixed")
    with pytest.raises(ValueError, match="evidence changed.*read the Source again"):
        await call(
            "intake", source_id=source["id"], run_id="same-run", proposal=proposal, project_id=product_project["id"]
        )
    assert (await call("list_tasks", product_id=product["id"]))[1] == 0
    missing_hashes = {key: value for key, value in proposal.items() if key != "evidence_hashes"}
    with pytest.raises(ValueError, match="evidence_hashes"):
        await call(
            "intake",
            source_id=source["id"],
            run_id="missing-hash",
            proposal=missing_hashes,
            project_id=product_project["id"],
        )
    with pytest.raises(ValueError, match="observed content hash for every selected link"):
        await call(
            "intake",
            source_id=source["id"],
            run_id="wrong-link",
            proposal={**proposal, "evidence_hashes": {"unread": observed["content_hash"]}},
            project_id=product_project["id"],
        )
    fresh = (await call("read_source", source["id"], "reconsider"))[0]
    revised = {
        **proposal,
        "title": "Document the corrected example",
        "brief": "Describe the corrected authentication flow",
        "evidence_hashes": {fresh["link"]: fresh["content_hash"]},
    }
    task = await call(
        "intake", source_id=source["id"], run_id="reconsider", proposal=revised, project_id=product_project["id"]
    )
    assert task["evidence"][0]["content_hash"] == fresh["content_hash"]
    assert task["evidence"][0]["content_hash"] != observed["content_hash"]
    assert (await call("list_tasks", product_id=product["id"]))[1] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_delivery", [False, True])
async def test_summary_delivery_failure_keeps_last_delivered_baseline(heartbeat, monkeypatch, prior_delivery):
    _, _, call = heartbeat
    delivery = AsyncMock()
    monkeypatch.setattr("agno.company.summary.adeliver_summary", delivery)
    product = await call(
        "create", name="Reliable changes", metadata={"summary": {"interface": "slack", "destination": "docs"}}
    )
    product_project = await call("create_project", product_id=product["id"], name="Work")
    await call("create_task", product_id=product["id"], title="Task A", project_id=product_project["id"])
    if prior_delivery:
        await call("summarize", product_id=product["id"], run_id="first", interfaces=[], narrative="First report")
    await call("create_task", product_id=product["id"], title="Task B", project_id=product_project["id"])
    delivery.side_effect = RuntimeError("Transport unavailable")
    with pytest.raises(RuntimeError, match="Transport unavailable"):
        await call("summarize", product_id=product["id"], run_id="failed", interfaces=[], narrative="Pending report")
    assert "Pending report" in (await call("read_wiki", product["id"], "summary.md")).content
    delivery.side_effect = None
    await call("summarize", product_id=product["id"], run_id="next", interfaces=[], narrative="Recovered report")
    changed = delivery.await_args.args[-1].split("## What changed")[1].split("## Waiting")[0]
    assert "Added Task B" in changed
    assert ("Added Task A" in changed) is (not prior_delivery)
    await call(
        "summarize", product_id=product["id"], run_id="quiet", interfaces=[], narrative="Nothing further changed"
    )
    assert "No Task changes since the last delivered summary." in delivery.await_args.args[-1]


@pytest.mark.asyncio
async def test_source_discovery_fragments_and_selected_intake(heartbeat, tmp_path, monkeypatch):
    from agno.tools.workspace import Workspace as WorkspaceTools
    from agno.utils.string import hash_string_sha256

    _, _, call = heartbeat
    root = tmp_path / "large-repo"
    root.mkdir()
    content = ('Useful Unicode evidence: 😀\\"\n' * 2000).rstrip("\n")
    for i in range(25):
        (root / (str(i).zfill(2) + ".md")).write_text(content)
    (root / "broken.png").write_bytes(b"\xff\xfe")
    product = await call("create", name="Large checkout")
    product_project = await call("create_project", product_id=product["id"], name="Work")
    source = await call("create_source", product_id=product["id"], type="git", reference=str(root))
    original = WorkspaceTools._read_file
    reads = []

    def observe(self, path, *args, **kwargs):
        reads.append(path)
        return original(self, path, *args, **kwargs)

    monkeypatch.setattr(WorkspaceTools, "_read_file", observe)
    page = await call("browse_source", source["id"], "scan", pattern="*.md", limit=3)
    assert len(page["data"]) == 3 and page["total_count"] == 25 and page["next_offset"] == 3
    assert not reads and "content" not in page["data"][0]
    next_page = await call("browse_source", source["id"], "scan", pattern="*.md", offset=3, limit=3)
    assert not {item["path"] for item in page["data"]} & {item["path"] for item in next_page["data"]}
    selected = page["data"][0]["path"]
    first = await call("browse_source", source["id"], "scan", path=selected, max_chars=16000)
    import json

    assert len(json.dumps(first).encode()) <= 65536
    assert first["content_hash"] == hash_string_sha256(content)
    assert first["content"] == content[: first["next_content_offset"]]
    assert reads == [selected]
    second = await call(
        "browse_source", source["id"], "scan", path=selected, content_offset=first["next_content_offset"]
    )
    assert second["content_hash"] == first["content_hash"]
    assert content.startswith(first["content"] + second["content"])
    reads.clear()
    monkeypatch.setattr(
        WorkspaceTools,
        "_list_files",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Intake must not list the repository")),
    )
    task = await call(
        "intake",
        source_id=source["id"],
        run_id="scan",
        proposal=dict(
            title="Useful proposal",
            brief="Act on observed evidence",
            proposal_key="one-issue",
            evidence_links=[first["link"]],
            evidence_hashes={first["link"]: first["content_hash"]},
        ),
        project_id=product_project["id"],
    )
    assert reads == [selected] and task["evidence"][0]["content_hash"] == first["content_hash"]
    assert "content" not in task["evidence"][0]


@pytest.mark.asyncio
async def test_routine_service_cannot_create_a_plain_task(heartbeat):
    from agno.company.routines import _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    _, _, call = heartbeat
    product = await call("create", name="Bounded proposals")
    product_project = await call("create_project", product_id=product["id"], name="Work")
    with authorization_scope(lambda: _RoutineAuthorization(None, "routine")):
        with pytest.raises(PermissionError, match="intake_product_source"):
            await call("create_task", product_id=product["id"], title="Plain task", project_id=product_project["id"])
    assert (await call("list_tasks", product_id=product["id"]))[1] == 0


@pytest.mark.asyncio
async def test_intake_preserves_proposed_executor_and_project(heartbeat, tmp_path):
    _, _, call = heartbeat
    path = tmp_path / "release.md"
    path.write_text("Document the API")
    product = await call("create", name="API")
    project = await call("create_project", product_id=product["id"], name="Guide")
    source = await call("create_source", product_id=product["id"], type="markdown", reference=str(path))
    observed = (await call("read_source", source["id"], "observation"))[0]
    proposal = dict(
        title="Document API",
        brief="Write guide",
        proposal_key="guide",
        evidence_links=[observed["link"]],
        evidence_hashes={observed["link"]: observed["content_hash"]},
    )
    task = await call(
        "intake",
        source_id=source["id"],
        run_id="scan",
        proposal=proposal,
        routine_id="reader-routine",
        executor_type="agent",
        executor_id="writer",
        project_id=project["id"],
    )
    assert task["status"] == "backlog"
    assert task["executor_type"] == "agent" and task["executor_id"] == "writer"
    assert task["project_id"] == project["id"]
    assert task["origin"] == "routine" and task["routine_id"] == "reader-routine"
    other = await call("create", name="Other")
    outside = await call("create_project", product_id=other["id"], name="Outside")
    with pytest.raises(ValueError, match="same Product"):
        await call("intake", source_id=source["id"], run_id="outside", proposal=proposal, project_id=outside["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [0, 14])
@pytest.mark.parametrize("legacy", [False, True])
async def test_summary_retention_preserves_delivery_state(heartbeat, monkeypatch, window, legacy):
    import time

    from agno.company.summary import _summary_state_filesystem

    db, _, call = heartbeat
    delivery = AsyncMock()
    monkeypatch.setattr("agno.company.summary.adeliver_summary", delivery)
    product = await call(
        "create",
        name="Durable reports",
        metadata={"archive_window_days": window, "summary": {"interface": "slack", "destination": "reports"}},
    )
    product_project = await call("create_project", product_id=product["id"], name="Work")
    await call("create_task", product_id=product["id"], title="Task A", project_id=product_project["id"])
    await call("summarize", product_id=product["id"], run_id="first", interfaces=[], narrative="Initial report")
    # Multiple receipts must all survive migration and adjacent-marker parsing.
    await call("summarize", product_id=product["id"], run_id="second", interfaces=[], narrative="Second report")
    if legacy:
        await _summary_state_filesystem(db, product["id"]).adelete("delivery.md")
    now = int(time.time())
    monkeypatch.setattr(time, "time", lambda: now + (window + 1) * 86400)
    refreshed = await call("refresh", product["id"])
    assert "summary.md" in refreshed["deleted_pages"]
    for run_id in ("first", "second"):
        assert (await call("summarize", product_id=product["id"], run_id=run_id, interfaces=[], narrative="Retry"))[
            "quiet"
        ]
    assert delivery.await_count == 2
    with pytest.raises(LookupError):
        await call("read_wiki", product["id"], "summary.md")
    await call("create_task", product_id=product["id"], title="Task B", project_id=product_project["id"])
    delivery.side_effect = RuntimeError("Transport unavailable")
    with pytest.raises(RuntimeError, match="Transport unavailable"):
        await call("summarize", product_id=product["id"], run_id="failed", interfaces=[], narrative="Not delivered")
    monkeypatch.setattr(time, "time", lambda: now + (window + 1) * 2 * 86400)
    assert "summary.md" in (await call("refresh", product["id"]))["deleted_pages"]
    delivery.side_effect = None
    await call("summarize", product_id=product["id"], run_id="recovered", interfaces=[], narrative="Recovered")
    report = delivery.await_args.args[-1]
    assert "Added Task B" in report and "Added Task A" not in report
    wiki = await call("get_wiki", product["id"])
    assert {page.path for page in await wiki.backend.filesystem.alist()} == {"brief.md", "status.md", "summary.md"}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["link", "enable"])
@pytest.mark.parametrize("auto_accept", [False, True])
async def test_routine_creation_recovers_after_storage_failure(heartbeat, monkeypatch, failure, auto_accept):
    import time

    from httpx import ASGITransport, AsyncClient

    from agno.company.execution import _call
    from agno.os import AgentOS, CompanyConfig

    db, _, call = heartbeat
    product = await call("create", name="Recovered routines")
    app = AgentOS(
        db=db, agents=[Agent(id="reader", telemetry=False)], company=CompanyConfig(), telemetry=False
    ).get_app()
    body = dict(
        product_id=product["id"],
        name="refresh",
        template="refresh",
        executor_type="agent",
        executor_id="reader",
        cron_expr="0 * * * *",
    )
    if auto_accept:
        body["auto_accept"] = {
            "executor_type": "agent",
            "executor_id": "reader",
            "limits": {"expires_at": int(time.time()) + 3600},
        }
    method = "add_product_routine" if failure == "link" else "update_schedule"
    original = getattr(db, method)

    def fail(*args, **kwargs):
        raise RuntimeError("Interrupted creation")

    monkeypatch.setattr(db, method, fail)
    async with AsyncClient(transport=ASGITransport(app, raise_app_exceptions=False), base_url="http://test") as client:
        assert (await client.post("/company/routines", json=body)).status_code == 500
        pending, total = await _call(db, "get_schedules")
        assert total == 1 and not pending[0]["enabled"]
        assert pending[0]["next_run_at"] is None
        assert (await _call(db, "get_schedules", enabled=True))[1] == 0
        monkeypatch.setattr(db, method, original)
        response = await client.post("/company/routines", json=body)
        assert response.status_code == 201, response.text
        assert response.json()["id"] == pending[0]["id"] and response.json()["enabled"] is True
        assert (await call("get", product["id"]))["metadata"]["routine_ids"] == [pending[0]["id"]]
        assert (await _call(db, "get_schedules"))[1] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("executor_type", ["agent", "team"])
async def test_agent_website_source_reuse_provenance_conflicts_and_archive(heartbeat, monkeypatch, executor_type):
    import json

    from agno.company.execution import _call
    from agno.knowledge.document import Document
    from agno.run.base import RunContext
    from agno.tools.company import CompanyTools

    db, _, call = heartbeat
    product = await call("create", name="Discovery", user_id="owner")
    toolkit = CompanyTools(db, user_isolation=True)
    agent = SimpleNamespace(id="discoverer")
    context = RunContext(run_id="discovery-run", session_id="session", user_id="owner")

    async def add(**overrides):
        args = dict(
            product_id=product["id"],
            reference="https://example.test/release",
            _agno_run_context=context,
        )
        args["_agno_" + executor_type] = agent
        args.update(overrides)
        if isinstance(db, AsyncBaseDb):
            return json.loads(await toolkit.aadd_product_source(**args))
        return json.loads(await asyncio.to_thread(toolkit.add_product_source, **args))

    first, second = await asyncio.gather(add(), add())
    assert first["id"] == second["id"]
    assert first["config"]["metadata"] == {executor_type + "_id": "discoverer", "run_id": "discovery-run"}
    context.run_id = "later-run"
    assert (await add())["config"]["metadata"]["run_id"] == "discovery-run"
    with pytest.raises(ValueError, match=first["id"]):
        await add(config={"paths": ["other"]})
    with pytest.raises(PermissionError, match="only website"):
        await call(
            "add_source",
            product_id=product["id"],
            type="git",
            reference="/private/repo",
            executor_id="discoverer",
            executor_type=executor_type,
            run_id="discovery-run",
        )
    # Another member's agent may add to the Product too; the same website reuses the Source.
    context.user_id = "other"
    assert (await add())["id"] == first["id"]
    context.user_id = "owner"
    with pytest.raises(ValueError, match="identity"):
        await add(**{"_agno_" + executor_type: None})
    monkeypatch.setattr(
        "agno.knowledge.reader.website_reader.WebsiteReader.read",
        lambda *args, **kwargs: [Document(content="A released capability needs documentation")],
    )
    observed = await call("read_source", first["id"], "observed")
    assert observed[0]["content_hash"]
    assert (await call("list_sources", product_id=product["id"]))[1] == 1
    await call("delete_source", first["id"], user_id="owner")
    with pytest.raises(ValueError, match=first["id"]):
        await add()
    assert (await call("list_sources", product_id=product["id"]))[1] == 0
    assert await _call(db, "get_source", first["id"], include_deleted=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledgment", ["backlog", "ready", "cancelled", "done", "archived"])
async def test_summary_omits_acknowledged_failures(heartbeat, monkeypatch, acknowledgment):
    from agno.company.execution import _call

    db, _, call = heartbeat
    delivery = AsyncMock()
    monkeypatch.setattr("agno.company.summary.adeliver_summary", delivery)
    product = await call(
        "create", name="Reports", metadata={"summary": {"interface": "slack", "destination": "reports"}}
    )
    product_project = await call("create_project", product_id=product["id"], name="Work")
    task = await call("create_task", product_id=product["id"], title="Recovered work", project_id=product_project["id"])
    await call(
        "transition_task",
        task_id=task["id"],
        target="ready",
        reason="Accepted",
        executor_type="agent",
        executor_id="reader",
    )
    task = await call("get_task", task["id"])
    started = await _call(db, "start_task_run", task["id"], 1, task["transitions"])
    await _call(
        db, "complete_task_run", task["id"], started["job_id"], {"status": "ERROR", "error": "Historical failure"}
    )
    await call("summarize", product_id=product["id"], run_id="failed", interfaces=[], narrative="Failure needs review")
    assert "Historical failure" in delivery.await_args.args[-1]
    if acknowledgment in {"done", "archived"}:
        await call("transition_task", task_id=task["id"], target="in_review", reason="Reviewed result")
        await call("transition_task", task_id=task["id"], target="done", reason="Accepted result")
        if acknowledgment == "archived":
            await call("delete_task", task["id"])
    else:
        if acknowledgment == "ready":
            await call("transition_task", task_id=task["id"], target="backlog", reason="Retry requested")
        kwargs = {"executor_type": "agent", "executor_id": "reader"} if acknowledgment == "ready" else {}
        await call("transition_task", task_id=task["id"], target=acknowledgment, reason="Acknowledged", **kwargs)
    await call(
        "summarize", product_id=product["id"], run_id="acknowledged", interfaces=[], narrative="The owner has acted"
    )
    report = delivery.await_args.args[-1]
    assert "No failed Tasks." in report and "Historical failure" not in report


@pytest.mark.asyncio
async def test_concurrent_summary_does_not_redeliver_the_same_delta(heartbeat, monkeypatch):
    import threading

    from agno.fs.errors import VersionConflictError

    db, manager, call = heartbeat
    entered, release = threading.Event(), threading.Event()
    delivered = []

    async def send(*args):
        delivered.append(args[-1])
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)

    monkeypatch.setattr("agno.company.summary.adeliver_summary", send)
    product = await call(
        "create", name="Reports", metadata={"summary": {"interface": "slack", "destination": "reports"}}
    )
    product_project = await call("create_project", product_id=product["id"], name="Work")
    await call("create_task", product_id=product["id"], title="One change", project_id=product_project["id"])
    first = asyncio.create_task(
        call("summarize", product_id=product["id"], run_id="first", interfaces=[], narrative="Changed")
    )
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        with pytest.raises((ValueError, VersionConflictError)):
            await call("summarize", product_id=product["id"], run_id="overlap", interfaces=[], narrative="Same change")
    finally:
        release.set()
        await first
    assert len(delivered) == 1
    await call("summarize", product_id=product["id"], run_id="later", interfaces=[], narrative="Quiet")
    assert "No Task changes since the last delivered summary" in delivered[-1]


@pytest.mark.asyncio
async def test_product_metadata_edits_keep_linked_routines(heartbeat):
    db, _, call = heartbeat
    product = await call("create", name="Docs", metadata={"team": "a"})
    link = db.add_product_routine(product["id"], "routine-1")
    if inspect.isawaitable(link):
        await link

    updated = await call("update", product["id"], metadata={"team": "b", "routine_ids": []})
    assert updated["metadata"]["team"] == "b"
    assert updated["metadata"]["routine_ids"] == ["routine-1"]
    cleared = await call("update", product["id"], metadata=None)
    assert cleared["metadata"]["routine_ids"] == ["routine-1"]
    renamed = await call("update", product["id"], name="Docs site")
    assert renamed["metadata"]["routine_ids"] == ["routine-1"]
