"""Serve all Company cookbook features in one persistent AgentOS.

Run from the SDK root:
    .venv/bin/python cookbook/05_agent_os/30_company/10_company_playground.py

Requires PostgreSQL. Model calls need OPENAI_API_KEY; browsing and the local
workflow do not. Use --check for isolated checks, --automation for automatic Task
pickup, and --sandbox for Claude/Codex engineers.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agno.agent import Agent
from agno.company import CompanyManager, Product, Routine, Source
from agno.company.bootstrap import rehydrate_product
from agno.company.routines import load_routine_skills
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, MCPConfig, OSManager
from agno.registry import Registry
from agno.team import Team
from agno.tools.company import CompanyTools
from agno.workflow import Step, StepInput, StepOutput, Workflow

DEFAULT_DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
OS_ID = "company-playground"


async def draft_task(step_input: StepInput) -> StepOutput:
    """A real queued executor with predictable output and no provider calls."""
    try:
        context = json.loads(str(step_input.input))
    except (ValueError, TypeError):
        context = {"brief": str(step_input.input)}
    brief = (
        context.get("brief", str(context))
        if isinstance(context, dict)
        else str(context)
    )
    await asyncio.sleep(1)
    if "[fail]" in brief:
        raise ValueError("Intentional Company playground failure")
    if "[slow]" in brief:
        await asyncio.sleep(20)
    return StepOutput(
        content=f"# Draft ready for human review\n\n{brief}\n\nVerified locally; no model was called."
    )


def sandbox_agents(db: PostgresDb, directory: Path) -> list:
    from agno.agents.claude import ClaudeAgent
    from agno.agents.codex import CodexAgent
    from agno.sandbox import Repository
    from agno.sandbox.checkpoint import FileCheckpointStore
    from agno.sandbox.docker import DockerSandbox

    repository = Repository("https://github.com/octocat/Hello-World", branch="master")
    checkpoints = FileCheckpointStore(directory / "checkpoints")
    image = os.getenv("SANDBOX_IMAGE", "agno-sandbox:local")
    instructions = "Inspect README in the checked-out repository and summarize it. Do not push or publish."
    return [
        ClaudeAgent(
            id="company-claude",
            db=db,
            repository=repository,
            system_prompt=instructions,
            sandbox=DockerSandbox(
                image,
                namespace="company-playground-claude",
                network="isolated",
                workspace_mb=2048,
                execution_timeout=1800,
                checkpoints=checkpoints,
            ),
        ),
        CodexAgent(
            id="company-codex",
            db=db,
            repository=repository,
            instructions=instructions,
            sandbox_mode="workspace-write",
            sandbox=DockerSandbox(
                image,
                namespace="company-playground-codex",
                network="isolated",
                workspace_mb=2048,
                execution_timeout=1800,
                checkpoints=checkpoints,
            ),
        ),
    ]


def seed(agent_os: AgentOS, directory: Path) -> None:
    """Create the sample once; never reset edited, archived, or completed work."""
    db = agent_os.db
    manager = CompanyManager(db, registry=agent_os.registry)
    prefix = db.db_schema
    directory.mkdir(parents=True, exist_ok=True)
    release = directory / "release.md"
    if not release.exists():
        release.write_text(
            "# SDK release\n\nDocument Task retries and shared review sessions.\n"
        )

    declarations = [
        Product(
            id=f"{prefix}-sdk",
            name="SDK",
            user_id="alice",
            purpose="Build and review reliable agent features",
            sources=[
                Source(id=f"{prefix}-release", type="markdown", reference=str(release)),
                Source(
                    id=f"{prefix}-docs-site",
                    type="website",
                    reference="https://docs.agno.com/",
                ),
            ],
            routines=[
                Routine(
                    name="intake",
                    template="intake",
                    executor_type="agent",
                    executor_id="company-reader",
                ),
                Routine(
                    name="refresh",
                    template="refresh",
                    executor_type="agent",
                    executor_id="company-reader",
                ),
                Routine(
                    name="custom-watch",
                    executor_type="agent",
                    executor_id="company-reader",
                    instructions="Read the configured release Source. Propose evidence-backed documentation work only for actionable changes.",
                ),
            ],
        ),
        Product(
            id=f"{prefix}-docs",
            name="Documentation",
            user_id="bob",
            purpose="Keep guides accurate and readable",
        ),
        Product(
            id=f"{prefix}-archive",
            name="Archive and restore sandbox",
            user_id="alice",
            purpose="Test cascading archive without touching the SDK Product",
        ),
        Product(
            id=f"{prefix}-engineering",
            name="Sandbox engineering",
            user_id="alice",
            sources=[
                Source(
                    id=f"{prefix}-repo",
                    type="git",
                    reference="https://github.com/octocat/Hello-World",
                    config={"branch": "master"},
                )
            ],
        ),
    ]
    for product in declarations:
        rehydrate_product(db, product, registry=agent_os.registry)

    # Optional executors can be enabled after the initial seed was created.
    if agent_os.registry.get_agent("company-claude") is not None:
        projects, _ = manager.list_projects(
            product_id=f"{prefix}-engineering", include_deleted=True
        )
        engineering = next(
            (p for p in projects if p["name"] == "Inspect the public repository"), None
        )
        if engineering is None:
            engineering = manager.create_project(
                product_id=f"{prefix}-engineering",
                name="Inspect the public repository",
                user_id="alice",
            )
        tasks, _ = manager.list_tasks(
            project_id=engineering["id"], include_deleted=True
        )
        for executor_id in ("company-claude", "company-codex"):
            title = f"Inspect README with {executor_id}"
            if not any(t["title"] == title for t in tasks):
                manager.create_task(
                    product_id=f"{prefix}-engineering",
                    project_id=engineering["id"],
                    title=title,
                    brief="Read README and summarize its contents. Do not push.",
                    user_id="alice",
                    executor_type="agent",
                    executor_id=executor_id,
                )

    product = manager.get(f"{prefix}-sdk", include_deleted=True)
    if (product.get("metadata") or {}).get("playground_seeded"):
        return

    def project(product_id, name, status="proposed", owner="alice"):
        rows, _ = manager.list_projects(
            product_id=product_id, include_deleted=True, limit=100
        )
        row = next((r for r in rows if r["name"] == name), None)
        if row is not None:
            return row
        row = manager.create_project(
            product_id=product_id,
            name=name,
            user_id=owner,
            outcome="A reviewed, documented result",
        )
        if status != "proposed":
            row = manager.transition_project(
                project_id=row["id"], target="active", reason="Demo scope agreed"
            )
        if status in {"done", "cancelled"}:
            row = manager.transition_project(
                project_id=row["id"], target=status, reason="Seeded lifecycle example"
            )
        return row

    def task(
        parent,
        title,
        brief,
        status="backlog",
        executor_type="workflow",
        executor_id="company-draft",
        owner="alice",
    ):
        rows, _ = manager.list_tasks(
            project_id=parent["id"], include_deleted=True, limit=100
        )
        row = next((r for r in rows if r["title"] == title), None)
        if row is not None:
            return row
        row = manager.create_task(
            product_id=parent["product_id"],
            project_id=parent["id"],
            title=title,
            brief=brief,
            user_id=owner,
            executor_type=executor_type,
            executor_id=executor_id,
        )
        targets = {
            "backlog": [],
            "ready": ["ready"],
            "in_progress": ["ready", "in_progress"],
            "in_review": ["ready", "in_progress", "in_review"],
            "done": ["ready", "in_progress", "in_review", "done"],
            "cancelled": ["cancelled"],
        }
        for target in targets[status]:
            kwargs = (
                {"executor_type": executor_type, "executor_id": executor_id}
                if target == "ready"
                else {}
            )
            row = manager.transition_task(
                task_id=row["id"],
                target=target,
                reason="Seeded lifecycle example; no execution yet",
                accepted_by=owner,
                **kwargs,
            )
        return row

    active = project(f"{prefix}-sdk", "Ship the next SDK release", "active")
    project(f"{prefix}-sdk", "Investigate next quarter")
    project(f"{prefix}-docs", "Completed migration guide", "done", "bob")
    project(f"{prefix}-docs", "Retired guide", "cancelled", "bob")
    docs = project(f"{prefix}-docs", "Documentation improvements", "active", "bob")
    archives = project(f"{prefix}-archive", "Restorable project", "active")
    project(f"{prefix}-engineering", "Inspect the public repository", "active")

    task(
        active,
        "Draft release notes locally",
        "Summarize the Task retry and review flow.",
    )
    task(active, "Ready local execution", "Draft a short testing checklist.", "ready")
    task(
        active,
        "Inspect the in-progress state",
        "Display fixture: no live run was started.",
        "in_progress",
    )
    task(
        active,
        "Inspect the review state",
        "Display fixture: review or request a real revision.",
        "in_review",
    )
    task(
        active,
        "Previously reviewed checklist",
        "Display fixture: completed lifecycle history.",
        "done",
    )
    task(
        active,
        "Cancelled duplicate work",
        "Display fixture: cancelled proposal.",
        "cancelled",
    )
    task(
        active,
        "Exercise failure and retry",
        "[fail] Return an intentional failure; re-scope to remove this marker before retrying.",
    )
    task(
        active,
        "Exercise cancellation",
        "[slow] Draft slowly so the run can be cancelled.",
    )
    task(
        docs,
        "Agent-written guide",
        "Write a concise guide to reviewing Company Tasks.",
        executor_type="agent",
        executor_id="company-writer",
        owner="bob",
    )
    task(
        docs,
        "Team-reviewed guide",
        "Write and review a guide to release readiness.",
        executor_type="team",
        executor_id="company-docs-team",
        owner="bob",
    )
    task(
        archives,
        "Child restored with its parent",
        "Archive and restore the parent to test the cascade.",
    )
    old = task(
        archives,
        "Independently archived child",
        "This child must stay archived when its parent is restored.",
    )
    if not old.get("deleted_at"):
        manager.delete_task(old["id"])
    for product_id in (f"{prefix}-sdk", f"{prefix}-docs"):
        page = manager.read_wiki(product_id, "status.md")
        if page.metadata.version == 1:
            manager.write_wiki(
                product_id=product_id,
                path="status.md",
                expected_version=1,
                content="# Status\n\nSample work is ready for review in the Company playground.\n",
            )
    for path, content in {
        "review-policy.md": "# Review policy\n\nHumans accept scope and approve completed Tasks.\n",
        "playground-guide.md": "# Playground\n\nUse company-draft for execution without a model.\n",
    }.items():
        try:
            manager.read_wiki(None, f"{prefix}/{path}")
        except LookupError:
            manager.write_wiki(
                product_id=None,
                path=f"{prefix}/{path}",
                content=content,
                expected_version=0,
            )
    if not manager.list_decisions(query="Playground review policy")[1]:
        manager.log_decision(
            decision="Playground review policy",
            reasoning="Keep human approval before completion.",
            user_id="alice",
        )

    evidence = manager.read_source(f"{prefix}-release", "playground-seed")
    intake = db.get_schedule_by_name(f"{prefix}-sdk.intake", user_id="alice")
    manager.intake(
        source_id=f"{prefix}-release",
        run_id="playground-seed",
        project_id=active["id"],
        routine_id=intake["id"],
        executor_type="workflow",
        executor_id="company-draft",
        proposal={
            "title": "Explain Task retries",
            "brief": "Document revision attempts and their shared session.",
            "proposal_key": "task-retry-guide",
            "evidence_links": [e["link"] for e in evidence],
            "evidence_hashes": {e["link"]: e["content_hash"] for e in evidence},
        },
    )
    manager.update(
        f"{prefix}-sdk",
        metadata={**(product.get("metadata") or {}), "playground_seeded": True},
    )


def build_os(
    db_url: str,
    schema: str,
    directory: Path,
    port: int = 7777,
    automation: bool = False,
    sandbox: bool = False,
    standalone_manager: bool = False,
):
    db = PostgresDb(id=f"company-playground-{schema}", db_url=db_url, db_schema=schema)
    model_id = os.getenv("COMPANY_MODEL", "gpt-5.6-luna")
    tools = CompanyTools(db, summary_tools=False)
    writer = Agent(
        id="company-writer",
        name="Company Writer",
        db=db,
        model=OpenAIResponses(id=model_id),
        instructions="Draft concise documentation from the accepted Task context. Return the result for human review.",
        telemetry=False,
    )
    reviewer = Agent(
        id="company-reviewer",
        name="Company Reviewer",
        db=db,
        model=OpenAIResponses(id=model_id),
        instructions="Review documentation for accuracy and clarity. Give concrete corrections.",
        telemetry=False,
    )
    reader = Agent(
        id="company-reader",
        name="Company Source Reader",
        db=db,
        model=OpenAIResponses(id=model_id),
        tools=[tools],
        skills=load_routine_skills(),
        telemetry=False,
        instructions=[
            "Inspect Company Sources and follow the requested Routine. Propose evidence-backed work; never claim it has been accepted or executed.",
            "List Company wiki pages first, then read the returned paths with the same product_id. Default pages are brief.md and status.md.",
        ],
    )
    team = Team(
        id="company-docs-team",
        name="Documentation Team",
        members=[writer, reviewer],
        db=db,
        model=OpenAIResponses(id=model_id),
        delegate_to_all_members=True,
        store_member_responses=True,
        instructions="Draft and review the accepted Task, then return a concise final result.",
        telemetry=False,
    )
    from agno.workflow.types import HumanReview, OnError

    workflow = Workflow(
        id="company-draft",
        name="Local Company Draft",
        db=db,
        telemetry=False,
        steps=[
            Step(
                name="Draft",
                executor=draft_task,
                max_retries=0,
                human_review=HumanReview(on_error=OnError.fail),
            )
        ],
    )
    agents = [writer, reviewer, reader]
    if sandbox:
        agents.extend(sandbox_agents(db, directory))
    agent_os = AgentOS(
        id=OS_ID,
        name="Company Playground",
        db=db,
        agents=agents,
        teams=[team],
        workflows=[workflow],
        registry=Registry(models=[OpenAIResponses(id=model_id)]),
        company=CompanyConfig(automation_history_retention_days=30),
        manager=None if standalone_manager else OSManager(access_docs=False),
        mcp=MCPConfig(tools=[CompanyTools(db, summary_tools=False)]),
        queue=QueueConfig(
            durable=True,
            db=db,
            poll_interval=0.2,
            max_concurrency=2,
            redis=os.getenv("REDIS_URL", "redis://localhost:6379/0")
            if sandbox
            else None,
        ),
        scheduler=True,
        scheduler_poll_interval=1,
        scheduler_base_url=f"http://127.0.0.1:{port}",
        telemetry=False,
    )
    seed(agent_os, directory)
    app = agent_os.get_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        from agno.company.routines import _ensure_automation_schedule

        # Pause before the poller starts, including when reopening an old schema.
        schedule = await _ensure_automation_schedule(db)
        db.update_schedule(schedule["id"], enabled=automation, disabled_reason=None)
        async with original_lifespan(application):
            yield

    app.router.lifespan_context = lifespan
    return agent_os, app


def check_server(db_url: str) -> None:
    """Check the combined configuration in its own disposable schema."""
    from agno.fs.db import DbFileSystem
    from fastapi.testclient import TestClient
    from sqlalchemy import and_, delete, inspect, or_
    from sqlalchemy.schema import DropSchema

    schema = "company_playground_check_" + uuid4().hex
    cleanup_db = PostgresDb(db_url=db_url, db_schema=schema)
    db = None
    with TemporaryDirectory(prefix="company-playground-") as directory:
        try:
            agent_os, app = build_os(db_url, schema, Path(directory))
            db = agent_os.db
            manager = CompanyManager(db, registry=agent_os.registry)
            before = (
                manager.list()[1],
                manager.list_projects()[1],
                manager.list_tasks()[1],
                manager.list_decisions()[1],
            )
            seed(agent_os, Path(directory))
            assert before == (
                manager.list()[1],
                manager.list_projects()[1],
                manager.list_tasks()[1],
                manager.list_decisions()[1],
            )
            with TestClient(app) as client:
                assert not db.get_schedule_by_name("Company automation")["enabled"]
                for path in (
                    "/config",
                    "/company/products",
                    "/company/projects",
                    "/company/tasks",
                    "/company/wiki",
                    "/company/decisions",
                    "/company/sources",
                    "/company/routines",
                    "/company/attention",
                ):
                    result = client.get(path)
                    assert result.status_code == 200, (path, result.text)
                rows = client.get("/company/tasks", params={"limit": 100}).json()[
                    "data"
                ]
                task = next(t for t in rows if t["title"] == "Ready local execution")
                path = f"/company/tasks/{task['id']}"
                first = client.post(path + "/runs", json={"attempt": 1})
                assert first.status_code == 202, first.text
                again = client.post(path + "/runs", json={"attempt": 1})
                assert again.json()["run_id"] == first.json()["run_id"], again.text
                for attempt in (1, 2):
                    if attempt == 2:
                        started = client.post(path + "/runs", json={"attempt": attempt})
                        assert started.status_code == 202, started.text
                        assert (
                            started.json()["session_id"] == first.json()["session_id"]
                        )
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        task = client.get(path).json()
                        if task["status"] == "in_review":
                            break
                        time.sleep(0.1)
                    assert task["status"] == "in_review", task
                assert client.get(path + "/runs").json()["meta"]["total_count"] == 2
                completed = client.post(
                    path + "/transitions",
                    json={"target": "done", "reason": "Test reviewed both attempts"},
                )
                assert completed.status_code == 200, completed.text
                routine = client.get("/company/routines").json()["data"][0]
                route = "/company/routines/" + routine["id"]
                assert client.post(route + "/pause").status_code == 200
                assert client.post(route + "/trigger").status_code == 409
                assert client.post(route + "/resume").status_code == 200
                scheduled = client.patch(route, json={"cron_expr": "0 9 * * 1-5"})
                assert (
                    scheduled.status_code == 200
                    and scheduled.json()["schedule_type"] == "scheduled"
                ), scheduled.text
                assert (
                    client.patch(route, json={"cron_expr": None}).json()[
                        "schedule_type"
                    ]
                    == "on_demand"
                )
            print(
                "PASS combined server: persistent seed, routes, queue, duplicate starts, revisions, review and Routine controls"
            )
        finally:
            filesystem = DbFileSystem(cleanup_db)
            with cleanup_db.db_engine.begin() as connection:
                if inspect(connection).has_table(
                    filesystem.table_name, schema=filesystem.db_schema
                ):
                    table = filesystem.table
                    connection.execute(
                        delete(table).where(
                            or_(
                                table.c.namespace.in_(
                                    [
                                        f"company/products/{schema}-{name}/wiki"
                                        for name in (
                                            "sdk",
                                            "docs",
                                            "archive",
                                            "engineering",
                                        )
                                    ]
                                ),
                                and_(
                                    table.c.namespace == "company/wiki",
                                    table.c.path.startswith(
                                        schema + "/", autoescape=True
                                    ),
                                ),
                            )
                        )
                    )
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            cleanup_db.close()
            if db is not None:
                db.close()


def run_checks(examples: Path, db_url: str) -> None:
    """Run the focused examples so sync/async checks stay current."""
    check_server(db_url)
    cases = [
        ("01_manage_products.py", [], {}),
        ("02_manage_projects.py", [], {}),
        ("03_manage_tasks.py", [], {}),
        ("04_manage_playbook.py", [], {}),
        ("05_product_manager.py", [], {}),
        ("06_execute_tasks.py", [], {}),
        (
            "06_execute_tasks.py",
            [],
            {"COMPANY_DB": "postgres", "COMPANY_AUTOMATION": "1"},
        ),
        ("07_cascading_archive.py", [], {}),
        ("07_heartbeat.py", [], {}),
        ("08_custom_routines.py", [], {}),
        ("09_task_session_ownership.py", [], {}),
        ("09_task_session_ownership.py", [], {"COMPANY_DB": "postgres"}),
        ("09_sandboxed_engineers.py", ["--config-only"], {}),
    ]
    # Each original example owns its temporary data/schema. Never run sandbox
    # execution or a model call implicitly as part of these checks.
    env = {
        **os.environ,
        "AGNO_TELEMETRY": "false",
        "COMPANY_QUEUE_DB_URL": db_url,
        "DATABASE_URL": db_url,
        "COMPANY_DB": "sqlite",
        "COMPANY_AUTOMATION": "0",
    }
    failures = []
    for filename, flags, overrides in cases:
        result = subprocess.run(
            [sys.executable, str(examples / filename), *flags],
            env={**env, **overrides},
            capture_output=True,
            text=True,
            timeout=180,
        )
        label = filename + (" " + str(overrides) if overrides else "")
        if result.returncode:
            failures.append(label)
            print(
                f"FAIL {label}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}",
                flush=True,
            )
        else:
            print(f"PASS {label}", flush=True)
    if failures:
        raise RuntimeError("Cookbook checks failed: " + ", ".join(failures))
    print(
        "All Company cookbook checks passed. Live model, sandbox execution and external delivery were not run."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--db-url", default=os.getenv("COMPANY_DB_URL", DEFAULT_DB_URL))
    parser.add_argument("--schema", default="company_playground")
    parser.add_argument("--data-dir", type=Path, default=Path("tmp/company_playground"))
    parser.add_argument(
        "--automation",
        action="store_true",
        help="Enable automatic Task pickup and bounded acceptance.",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Include Claude and Codex; requires Redis, Docker and a sandbox image.",
    )
    parser.add_argument(
        "--standalone-manager",
        action="store_true",
        help="Expose Product Manager directly instead of through OS Manager.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run combined-server and individual cookbook checks without models.",
    )
    args = parser.parse_args()
    if args.check:
        run_checks(Path(__file__).resolve().parent, args.db_url)
    else:
        agent_os, app = build_os(
            args.db_url,
            args.schema,
            args.data_dir.resolve(),
            args.port,
            args.automation,
            args.sandbox,
            args.standalone_manager,
        )
        print(f"Connect AgentOS UI to http://localhost:{args.port}")
        print(
            "Use Local Company Draft for runs without model calls; model executors require OPENAI_API_KEY."
        )
        agent_os.serve(app=app, port=args.port)
