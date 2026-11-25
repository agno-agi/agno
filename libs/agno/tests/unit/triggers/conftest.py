"""Databases for the trigger tests: SQLite always, PostgreSQL when the server is up."""

import asyncio
import uuid
from typing import Any

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
PG_ASYNC_URL = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"


def postgres_reachable() -> bool:
    # A raw probe, not an adapter call: adapter methods catch and log connection errors.
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return False
    try:
        engine = create_engine(PG_URL)
    except Exception:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


async def call(db: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Call a storage method on a sync or an async adapter."""
    result = getattr(db, method)(*args, **kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


def _drop_schema(schema: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(PG_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        engine.dispose()


@pytest.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def db(request, tmp_path):
    """Each storage test runs on all four SQL adapters. The PostgreSQL lanes skip without a server:
    CI's unit job starts one on localhost:5532."""
    kind = request.param
    if kind == "sqlite":
        yield SqliteDb(db_file=str(tmp_path / "triggers.db"))
        return
    if kind == "async_sqlite":
        async_sqlite = AsyncSqliteDb(db_file=str(tmp_path / "triggers_async.db"))
        yield async_sqlite
        # Closed with the loop that opened it, so no connection thread outlives the test.
        await async_sqlite.db_engine.dispose()
        return
    if not postgres_reachable():
        pytest.skip(f"PostgreSQL is not reachable at {PG_URL}")
    schema = f"triggers_{uuid.uuid4().hex[:8]}"
    if kind == "postgres":
        from agno.db.postgres import PostgresDb

        database: Any = PostgresDb(db_url=PG_URL, db_schema=schema)
    else:
        from agno.db.postgres import AsyncPostgresDb

        database = AsyncPostgresDb(db_url=PG_ASYNC_URL, db_schema=schema)
    yield database
    if kind == "async_postgres":
        await database.db_engine.dispose()
    _drop_schema(schema)


# --- End to end: a signed delivery, through AgentOS, to a run -------------------------------------

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import AsyncIterator, Callable, Dict, Iterator, List, Optional  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.base import AsyncBaseDb  # noqa: E402
from agno.models.base import Model  # noqa: E402
from agno.models.message import MessageMetrics  # noqa: E402
from agno.models.response import ModelResponse  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.interfaces.github import GitHub  # noqa: E402
from agno.triggers.runtime import adeclare_triggers  # noqa: E402

SECRET = "github-webhook-secret"
REPOSITORY = "agno-agi/agno"


class RecordingModel(Model):
    """An offline model that records what each call was given and answers with a canned reply.

    ``fail_first`` makes the first calls raise, and ``gate`` holds every call until it is set, so a
    test can look at a run while it is in flight.
    """

    def __init__(self, reply: str = "done", fail_first: int = 0):
        super().__init__(id="recording-model", name="recording-model", provider="test")
        self.reply = reply
        self.fail_first = fail_first
        self.gate: Optional[asyncio.Event] = None
        # The text of the newest user message of each call, in call order.
        self.inputs: List[str] = []
        # Every user message each call could see, newest last: shows whether a session was continued.
        self.histories: List[List[str]] = []
        self.running = 0
        self.most_at_once = 0

    def _record(self, args: Any, kwargs: Any) -> None:
        messages = kwargs.get("messages") or (args[0] if args else [])
        seen = [str(message.content) for message in messages if getattr(message, "role", None) == "user"]
        self.histories.append(seen)
        self.inputs.append(seen[-1] if seen else "")

    def _resp(self) -> ModelResponse:
        return ModelResponse(content=self.reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._record(args, kwargs)
        return self._resp()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.running += 1
        self.most_at_once = max(self.most_at_once, self.running)
        try:
            self._record(args, kwargs)
            if self.gate is not None:
                await self.gate.wait()
            # Yield, so two runs that were allowed to overlap would be seen overlapping.
            await asyncio.sleep(0.02)
            if len(self.inputs) <= self.fail_first:
                raise RuntimeError("the model is down")
            return self._resp()
        finally:
            self.running -= 1

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield await self.ainvoke(*args, **kwargs)

    def parse_args(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return self._resp()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._resp()


def issue_payload(number: int = 7, association: str = "MEMBER", sender: str = "alice", **overrides: Any) -> Dict:
    payload: Dict[str, Any] = {
        "action": "opened",
        "repository": {"full_name": REPOSITORY},
        "sender": {"login": sender, "type": "User"},
        "installation": {"id": 4242},
        "issue": {
            "number": number,
            "title": "Export fails",
            "body": "Steps to reproduce: click Export.",
            "html_url": f"https://github.com/{REPOSITORY}/issues/{number}",
            "state": "open",
            "user": {"login": sender},
            "author_association": association,
            "labels": [],
        },
    }
    payload.update(overrides)
    return payload


def comment_payload(
    number: int = 7,
    association: str = "MEMBER",
    sender: str = "bob",
    body: str = "Any update?",
    issue_association: str = "MEMBER",
    **overrides: Any,
) -> Dict:
    payload = issue_payload(number=number, association=issue_association, sender="alice")
    payload.update(
        {
            "action": "created",
            "sender": {"login": sender, "type": "User"},
            "comment": {
                "id": 900 + number,
                "body": body,
                "html_url": f"https://github.com/{REPOSITORY}/issues/{number}#issuecomment-1",
                "user": {"login": sender},
                "author_association": association,
            },
        }
    )
    payload.update(overrides)
    return payload


async def age_claim(db: Any, event_id: str, seconds: int) -> None:
    """Move an event's claim into the past, as if its worker had stopped renewing it."""
    table = await call(db, "_get_table", table_type="trigger_events")
    statement = text(f"UPDATE {table.fullname} SET claimed_at = claimed_at - :seconds WHERE id = :id")
    if isinstance(db, AsyncBaseDb):
        async with db.async_session_factory() as sess, sess.begin():
            await sess.execute(statement, {"seconds": seconds, "id": event_id})
    else:
        with db.Session() as sess, sess.begin():
            sess.execute(statement, {"seconds": seconds, "id": event_id})


class FailingReads(httpx.AsyncBaseTransport):
    """The executor's way to the app, with the first reads of a run's status answered by a failure."""

    def __init__(self, app: Any, times: int, status_code: int = 503):
        self.inner = httpx.ASGITransport(app=app)
        self.left = times
        self.status_code = status_code
        self.requests: List[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and "/runs/" in request.url.path and self.left > 0:
            self.left -= 1
            return httpx.Response(self.status_code, json={"detail": "unavailable"})
        return await self.inner.handle_async_request(request)


@dataclass
class Harness:
    """One AgentOS with a GitHub source, driven in process: deliveries in, events run on demand."""

    agent_os: AgentOS
    app: Any
    db: Any
    github: GitHub
    model: RecordingModel
    client: httpx.AsyncClient
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def runtime(self) -> Any:
        return self.agent_os._trigger_runtime

    @property
    def token(self) -> str:
        return self.agent_os._internal_service_token  # type: ignore[return-value]

    async def deliver(
        self,
        payload: Dict,
        event: str = "issues",
        delivery: str = "d-1",
        secret: str = SECRET,
        signature: Optional[str] = None,
    ) -> httpx.Response:
        body = json.dumps(payload).encode()
        if signature is None:
            signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        }
        return await self.client.post(f"{self.github.prefix}/events", content=body, headers=headers)

    async def run_events(self) -> None:
        """Run every stored event that may run, until none is waiting or in flight."""
        await self.runtime.poller.drain()

    async def events(self, **filters: Any) -> List[Dict]:
        rows, _ = await call(self.db, "get_trigger_events", limit=100, **filters)
        # Oldest first, the order they were received.
        return sorted(rows, key=lambda row: row["id"])

    async def run(self, row: Dict, target: str = "agents/engineer") -> Dict:
        """The stored run an event started."""
        response = await self.client.get(
            f"/{target}/runs/{row['run_id']}",
            params={"session_id": row["session_id"]},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def start(self) -> None:
        """What a start of this AgentOS does to stored triggers, before its poller runs."""
        await adeclare_triggers(self.db, self.agent_os.triggers, os_id=self.agent_os._trigger_os_id)

    def fail_reads(self, times: int, status_code: int = 503) -> FailingReads:
        """Make the executor's next reads of a run's status fail."""
        transport = FailingReads(self.app, times, status_code)
        self.runtime.executor._client = httpx.AsyncClient(transport=transport, timeout=30)
        return transport

    async def lose_claim(self, event_id: str) -> None:
        """Hold an event as if its worker stopped after the run ended and before it recorded the result."""
        await call(self.db, "update_trigger_event", event_id, status="running", output=None, completed_at=None)
        await age_claim(self.db, event_id, 121)

    async def close(self) -> None:
        await self.runtime.executor.close()
        await self.client.aclose()


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    """A factory of adapters on one database, so two AgentOS instances can share it.

    The PostgreSQL lane skips without a server: CI's unit job starts one on localhost:5532.
    """
    if request.param == "sqlite":
        path = str(tmp_path / "triggers_e2e.db")
        yield lambda: SqliteDb(db_file=path)
        return
    if not postgres_reachable():
        pytest.skip(f"PostgreSQL is not reachable at {PG_URL}")
    from agno.db.postgres import PostgresDb

    schema = f"triggers_{uuid.uuid4().hex[:8]}"
    yield lambda: PostgresDb(db_url=PG_URL, db_schema=schema)
    _drop_schema(schema)


@pytest.fixture
async def make_os(database):
    """Build an AgentOS around a GitHub source and the triggers a test declares for it."""
    built: List[Harness] = []

    async def build(
        declare: Callable[[GitHub, Agent], List[Any]],
        model: Optional[RecordingModel] = None,
        declare_now: bool = True,
        os_options: Optional[Dict[str, Any]] = None,
        **github_options: Any,
    ) -> Harness:
        db = database()
        github = GitHub(repositories=REPOSITORY, webhook_secret=SECRET, **github_options)
        model = model or RecordingModel()
        agent = Agent(id="engineer", name="engineer", model=model, add_history_to_context=True)
        triggers = declare(github, agent)
        agent_os = AgentOS(
            agents=[agent],
            # A team or workflow a trigger runs is served by the same AgentOS.
            teams=[trigger.target for trigger in triggers if trigger.target_type == "team"] or None,
            workflows=[trigger.target for trigger in triggers if trigger.target_type == "workflow"] or None,
            db=db,
            interfaces=[github],
            triggers=triggers,
            telemetry=False,
            **(os_options or {}),
        )
        app = agent_os.get_app()
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        executor = agent_os._trigger_runtime.executor
        # The executor reaches the run endpoints of this same app, in process.
        executor._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), timeout=30)
        executor.poll_interval = 0.02
        # Short waits, so a test of a failed read or of a run that does not stop takes no real time.
        executor.read_backoff = 0.01
        executor.stop_grace_seconds = 0.2
        executor.sender_check_backoff = 0.01
        harness = Harness(agent_os=agent_os, app=app, db=db, github=github, model=model, client=client)
        built.append(harness)
        if declare_now:
            await harness.start()
        return harness

    yield build
    for harness in built:
        # Let a run a failed test left waiting finish, so nothing is still running when the loop closes.
        if harness.model.gate is not None:
            harness.model.gate.set()
        await harness.runtime.poller.stop()
        await harness.close()
