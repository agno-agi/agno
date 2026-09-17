"""Agent-level result offloading against SQLite and PostgreSQL.

The load-bearing assertion is on the persisted session row, not just the
message: substitution happens before the tool message (and the ToolExecution
built from it) exists, which is what keeps session rows small.
"""

import json
import os
import uuid
from typing import Any, AsyncIterator, Iterator, List, Optional

import pytest
from sqlalchemy import create_engine, text

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse, ToolExecution
from agno.offload import ResultStore
from agno.tools.function import ToolResult

pytestmark = pytest.mark.integration

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
PG_SCHEMA = f"offload_test_{os.getpid()}"

BIG = "\n".join(f"row {i}: " + "d" * 60 for i in range(1, 3001))


class ScriptedToolModel(Model):
    """Calls one tool once, then answers."""

    def __init__(self, tool_name: str = "fetch_page", tool_args: Optional[dict] = None):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.tool_name = tool_name
        self.tool_args = tool_args or {}
        self.calls = 0
        # The agent does not retain the resolved tool list, so capture what it
        # hands the model.
        self.seen_functions: dict = {}

    def response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._capture(kwargs)
        return super().response(*args, **kwargs)

    async def aresponse(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._capture(kwargs)
        return await super().aresponse(*args, **kwargs)

    def _capture(self, kwargs: dict) -> None:
        for tool in kwargs.get("tools") or []:
            name = getattr(tool, "name", None)
            if name:
                self.seen_functions[name] = tool

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": self.tool_name, "arguments": json.dumps(self.tool_args)},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="done", response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def fetch_page() -> str:
    """Fetch a large page.

    Returns:
        str: the page body.
    """
    return BIG


def fetch_small() -> str:
    """Fetch a small page.

    Returns:
        str: the page body.
    """
    return "small body"


def failing_tool() -> str:
    """Always fails.

    Returns:
        str: never returns.
    """
    raise ValueError("upstream 500: " + "e" * 6000)


def fetch_with_image() -> ToolResult:
    """Fetch a page and a screenshot.

    Returns:
        ToolResult: text plus one image.
    """
    return ToolResult(content=BIG, images=[Image(url="https://example.com/shot.png", id="img-1")])


@pytest.fixture(scope="session")
def pg_engine():
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{PG_SCHEMA}"'))
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{PG_SCHEMA}" CASCADE'))
        # Payloads live in the shared fs schema, which other lanes use too.
        # Remove this module's rows by namespace rather than the table, and
        # only when a test in this session created the table at all.
        if conn.execute(text("SELECT to_regclass('fs.agno_fs')")).scalar() is not None:
            conn.execute(text("DELETE FROM fs.agno_fs WHERE namespace LIKE 'tool-results/offload-agent-%'"))
    engine.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def db(request, tmp_path):
    if request.param == "sqlite":
        yield SqliteDb(db_file=str(tmp_path / "agent.db"))
    else:
        from agno.db.postgres import PostgresDb

        request.getfixturevalue("pg_engine")
        pg_db = PostgresDb(db_url=PG_URL, db_schema=PG_SCHEMA)
        yield pg_db
        with pg_db.db_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{PG_SCHEMA}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{PG_SCHEMA}"'))


def _sid() -> str:
    return f"offload-agent-{uuid.uuid4().hex[:10]}"


def _tool_messages(run_output) -> List[Any]:
    return [m for m in (run_output.messages or []) if m.role == "tool"]


# ------------------------------------------------------------------
# Round trip and the substitution point
# ------------------------------------------------------------------


def test_large_result_is_replaced_by_a_small_envelope(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    tool_message = _tool_messages(output)[0]
    # Head, an omitted marker, and a tail: still under 2% of the payload.
    assert len(tool_message.content) < 2600
    assert "lines omitted ...]" in tool_message.content
    assert tool_message.content.startswith('<result id="res_')
    assert "read_result(" in tool_message.content


def test_the_persisted_session_row_carries_the_envelope_not_the_payload(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    agent.run("go", session_id=session_id)
    stored = db.get_session(session_id=session_id, deserialize=False)
    blob = json.dumps(stored, default=str)
    assert BIG not in blob, "the full payload reached the persisted session row"
    assert "res_" in blob
    assert len(blob) < 200_000


def test_read_result_returns_the_stored_payload(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    store = agent._result_store
    page = store.read(result_id, 1, 3)
    assert page.text.startswith("row 1: ")
    assert page.line_count == 3000
    assert store._read_payload(store.get_row(result_id)) == BIG


def test_explicit_threshold_is_honoured(db):
    settings = ResultStore(threshold_chars=12_000)
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=settings)
    agent.initialize_agent()
    assert agent._result_store.threshold_chars == 12_000
    # The settings object the caller passed is bound as a copy, never modified.
    assert agent._result_store is not settings
    assert settings.db is None
    assert agent.offload_tool_results is settings


def test_an_int_setting_is_refused_with_a_clear_message(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=12_000)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="threshold_chars"):
        agent.initialize_agent()


# ------------------------------------------------------------------
# The never-offloaded set
# ------------------------------------------------------------------


def test_sub_threshold_result_stays_inline(db):
    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_small"), db=db, tools=[fetch_small], offload_tool_results=True
    )
    output = agent.run("go", session_id=_sid())
    assert _tool_messages(output)[0].content == "small body"


def test_failed_tool_call_keeps_its_error_text_verbatim(db):
    agent = Agent(
        model=ScriptedToolModel(tool_name="failing_tool"), db=db, tools=[failing_tool], offload_tool_results=True
    )
    output = agent.run("go", session_id=_sid())
    tool_message = _tool_messages(output)[0]
    assert tool_message.tool_call_error is True
    assert "<result id=" not in str(tool_message.content)
    assert "upstream 500" in str(tool_message.content)


def test_media_is_untouched_while_the_text_is_offloaded(db):
    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_with_image"),
        db=db,
        tools=[fetch_with_image],
        offload_tool_results=True,
    )
    output = agent.run("go", session_id=_sid())
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    # _handle_function_call_media lifts images off the tool message into a
    # follow-up user message; either way the image must survive offloading.
    media_messages = [m for m in output.messages if m.images]
    assert media_messages, "the image did not survive offloading"
    assert media_messages[0].images[0].id == "img-1"


def test_offloading_off_leaves_everything_inline(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page])
    output = agent.run("go", session_id=_sid())
    assert _tool_messages(output)[0].content == BIG
    assert agent._result_store is None


def test_no_read_back_tools_registered_when_disabled(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page])
    agent.run("go", session_id=_sid())
    names = set(agent.model.seen_functions)
    assert "read_result" not in names
    assert "search_result" not in names


def test_read_back_tools_registered_when_enabled(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    agent.run("go", session_id=_sid())
    names = set(agent.model.seen_functions)
    assert "read_result" in names
    assert "search_result" in names


def test_system_message_gains_the_instruction_line(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    output = agent.run("go", session_id=_sid())
    system = [m for m in output.messages if m.role == "system"][0]
    assert "Large tool results are stored as files" in system.content
    assert "do not answer from the preview when the preview was truncated" in system.content


# ------------------------------------------------------------------
# Access control
# ------------------------------------------------------------------


def test_read_result_refuses_a_result_from_another_session(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    other_session = _sid()
    output = agent.run("go", session_id=other_session)
    foreign_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]

    agent.model = ScriptedToolModel()
    agent.run("go", session_id=_sid())
    read_tool = agent.model.seen_functions["read_result"]
    reply = read_tool.entrypoint(result_id=foreign_id)
    assert reply.startswith("Error:")
    assert "different session" in reply


def test_read_result_of_an_unknown_id_is_an_error_string(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    agent.run("go", session_id=_sid())
    read_tool = agent.model.seen_functions["read_result"]
    assert read_tool.entrypoint(result_id="res_0000000000").startswith("Error: unknown result id")


def test_search_result_with_an_invalid_regex_returns_a_message(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    search_tool = agent.model.seen_functions["search_result"]
    reply = search_tool.entrypoint(result_id=result_id, pattern="[unclosed")
    assert reply.startswith("Error: invalid regular expression")


def test_read_and_search_tools_render_usable_output(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    read_tool = agent.model.seen_functions["read_result"]
    search_tool = agent.model.seen_functions["search_result"]
    read_reply = read_tool.entrypoint(result_id=result_id, start_line=1, end_line=2)
    assert "lines 1-2 of 3000" in read_reply
    assert "row 1: " in read_reply
    search_reply = search_tool.entrypoint(result_id=result_id, pattern=r"^row 7: ")
    assert "1 match(es)" in search_reply
    assert "7: row 7: " in search_reply


# ------------------------------------------------------------------
# Async parity
# ------------------------------------------------------------------


async def test_async_run_offloads_through_the_async_store_path(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = await agent.arun("go", session_id=session_id)
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    result_id = tool_message.content.split('id="')[1].split('"')[0]
    page = await agent._result_store.aread(result_id, 1, 2)
    assert page.text.startswith("row 1: ")


async def test_async_read_back_tools_are_the_async_entrypoints(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = await agent.arun("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    read_tool = agent.model.seen_functions["read_result"]
    reply = await read_tool.entrypoint(result_id=result_id, start_line=1, end_line=1)
    assert "row 1: " in reply


# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------


def test_delete_session_removes_index_rows_and_agno_fs_rows(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    store = agent._result_store
    row = store.get_row(result_id)
    assert row is not None
    assert store._fs_for_namespace(row["namespace"]).read(row["path"]) is not None

    db.delete_session(session_id=session_id)
    assert store.get_row(result_id) is None
    assert store._fs_for_namespace(row["namespace"]).read(row["path"]) is None


def test_delete_sessions_cascades_for_every_session(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    ids = []
    sessions = []
    for _ in range(2):
        session_id = _sid()
        agent.model = ScriptedToolModel()
        output = agent.run("go", session_id=session_id)
        ids.append(_tool_messages(output)[0].content.split('id="')[1].split('"')[0])
        sessions.append(session_id)
    store = agent._result_store
    db.delete_sessions(session_ids=sessions)
    assert all(store.get_row(result_id) is None for result_id in ids)


def test_delete_sessions_for_another_user_leaves_payloads_intact(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True, user_id="bob")
    session_id = _sid()
    output = agent.run("go", session_id=session_id, user_id="bob")
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    store = agent._result_store

    # A delete scoped to a different user must not touch bob's session or its payloads.
    db.delete_sessions(session_ids=[session_id], user_id="alice")
    assert db.get_session(session_id=session_id, session_type=SessionType.AGENT) is not None
    row = store.get_row(result_id)
    assert row is not None
    assert store.read(result_id).text.startswith("row 1:")

    db.delete_sessions(session_ids=[session_id], user_id="bob")
    assert db.get_session(session_id=session_id, session_type=SessionType.AGENT) is None
    assert store.get_row(result_id) is None


def test_the_index_table_is_created_with_the_rest_of_the_schema(db):
    db._create_all_tables()
    assert db._get_table(table_type="tool_results") is not None


# ------------------------------------------------------------------
# Continue-run paths: confirmation and external execution
# ------------------------------------------------------------------
def test_a_tool_resumed_after_confirmation_is_offloaded(db):
    from agno.tools.decorator import tool

    @tool(requires_confirmation=True)
    def fetch_gated_page() -> str:
        """Fetch a large page behind a confirmation.

        Returns:
            str: the page body.
        """
        return BIG

    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_gated_page"),
        db=db,
        tools=[fetch_gated_page],
        offload_tool_results=True,
    )
    session_id = _sid()
    paused = agent.run("go", session_id=session_id)
    assert paused.is_paused
    paused.tools[0].confirmed = True

    output = agent.continue_run(paused, session_id=session_id)
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content
    assert BIG not in (output.tools[0].result or "")


async def test_a_tool_resumed_after_confirmation_is_offloaded_async(db):
    from agno.tools.decorator import tool

    @tool(requires_confirmation=True)
    def fetch_gated_page_async() -> str:
        """Fetch a large page behind a confirmation.

        Returns:
            str: the page body.
        """
        return BIG

    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_gated_page_async"),
        db=db,
        tools=[fetch_gated_page_async],
        offload_tool_results=True,
    )
    session_id = _sid()
    paused = await agent.arun("go", session_id=session_id)
    assert paused.is_paused
    paused.tools[0].confirmed = True

    output = await agent.acontinue_run(paused, session_id=session_id)
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content


def test_an_externally_executed_result_is_offloaded(db):
    from agno.tools.decorator import tool

    @tool(external_execution=True)
    def fetch_on_client() -> str:
        """Fetch a large page on the client side.

        Returns:
            str: the page body.
        """
        return "never runs here"

    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_on_client"),
        db=db,
        tools=[fetch_on_client],
        offload_tool_results=True,
    )
    session_id = _sid()
    paused = agent.run("go", session_id=session_id)
    assert paused.is_paused
    assert paused.tools[0].external_execution_required
    paused.tools[0].result = BIG

    output = agent.continue_run(paused, session_id=session_id)
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content
    assert BIG not in (output.tools[0].result or "")

    # The payload is recoverable through the read-back tool.
    result_id = tool_message.content.split('id="')[1].split('"')[0]
    assert agent._result_store.read(result_id).text.startswith("row 1:")


async def test_an_externally_executed_result_is_offloaded_async(db):
    from agno.tools.decorator import tool

    @tool(external_execution=True)
    def fetch_on_client_async() -> str:
        """Fetch a large page on the client side.

        Returns:
            str: the page body.
        """
        return "never runs here"

    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_on_client_async"),
        db=db,
        tools=[fetch_on_client_async],
        offload_tool_results=True,
    )
    session_id = _sid()
    paused = await agent.arun("go", session_id=session_id)
    assert paused.is_paused
    paused.tools[0].result = BIG

    output = await agent.acontinue_run(paused, session_id=session_id)
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content


def test_a_small_externally_executed_result_stays_inline(db):
    from agno.tools.decorator import tool

    @tool(external_execution=True)
    def fetch_small_on_client() -> str:
        """Fetch a small value on the client side.

        Returns:
            str: the value.
        """
        return "never runs here"

    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_small_on_client"),
        db=db,
        tools=[fetch_small_on_client],
        offload_tool_results=True,
    )
    session_id = _sid()
    paused = agent.run("go", session_id=session_id)
    paused.tools[0].result = "tiny"

    output = agent.continue_run(paused, session_id=session_id)
    assert _tool_messages(output)[0].content == "tiny"


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
def test_offload_settings_survive_the_config_round_trip(db):
    settings = ResultStore(threshold_chars=12000, ttl_seconds=3600)
    agent = Agent(model=ScriptedToolModel(), db=db, offload_tool_results=settings)
    config = agent.to_dict()
    assert config["offload_tool_results"] == {"threshold_chars": 12000, "ttl_seconds": 3600}

    config.pop("model", None)
    restored = Agent.from_dict(config)
    assert isinstance(restored.offload_tool_results, ResultStore)
    assert restored.offload_tool_results.threshold_chars == 12000
    assert restored.offload_tool_results.ttl_seconds == 3600

    simple = Agent(model=ScriptedToolModel(), db=db, offload_tool_results=True).to_dict()
    assert simple["offload_tool_results"] is True
    plain = Agent(model=ScriptedToolModel(), db=db).to_dict()
    assert "offload_tool_results" not in plain


def test_async_db_degrades_to_off_with_a_warning(tmp_path, monkeypatch):
    from agno.db.sqlite import AsyncSqliteDb
    from agno.offload import setup

    warnings: List[str] = []
    monkeypatch.setattr(setup, "log_warning", warnings.append)
    agent = Agent(
        model=ScriptedToolModel(),
        db=AsyncSqliteDb(db_file=str(tmp_path / "async.db")),
        tools=[fetch_page],
        offload_tool_results=True,
    )
    agent.initialize_agent()
    agent.initialize_agent()
    assert agent._result_store is None
    # The declared setting is kept; only the runtime store is off.
    assert agent.offload_tool_results is True
    # The warning names the backend and the ones that work, not an internal filesystem error, once.
    assert len(warnings) == 1
    assert warnings[0].startswith("Result offloading is not available on AsyncSqliteDb")
    assert "SqliteDb or PostgresDb" in warnings[0]

    # A per-request copy of the same agent stays quiet.
    agent.deep_copy().initialize_agent()
    assert len(warnings) == 1


def test_a_degraded_agent_still_saves_its_declared_settings(tmp_path, monkeypatch):
    from agno.offload import setup

    monkeypatch.setattr(setup, "log_warning", lambda *_: None)
    settings = ResultStore(threshold_chars=12000, ttl_seconds=3600)
    agent = Agent(model=ScriptedToolModel(), tools=[fetch_page], offload_tool_results=settings)
    output = agent.run("go", session_id=_sid())
    # No db: the payload stays inline and the run completes.
    assert BIG in _tool_messages(output)[0].content
    config = agent.to_dict()
    assert config["offload_tool_results"] == {"threshold_chars": 12000, "ttl_seconds": 3600}


def test_an_agent_that_gains_a_db_starts_offloading(tmp_path, monkeypatch, db):
    from agno.offload import setup

    monkeypatch.setattr(setup, "log_warning", lambda *_: None)
    agent = Agent(model=ScriptedToolModel(), tools=[fetch_page], offload_tool_results=True)
    assert BIG in _tool_messages(agent.run("go", session_id=_sid()))[0].content
    agent.db = db
    agent.model = ScriptedToolModel()
    assert _tool_messages(agent.run("go", session_id=_sid()))[0].content.startswith('<result id="res_')


def test_long_and_unusual_session_ids_offload_and_clean_up(db):
    ids = ["s" * 119, "s" * 120, "x" * 200, "my session", "sesi\u00f3n-\u00fc {braces}", "MiXeD/Case:Id"]
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    for session_id in ids:
        agent.model = ScriptedToolModel()
        output = agent.run("go", session_id=session_id)
        content = _tool_messages(output)[0].content
        assert content.startswith('<result id="res_'), session_id
        result_id = content.split('id="')[1].split('"')[0]
        store = agent._result_store
        row = store.get_row(result_id)
        assert store.read(result_id).text.startswith("row 1:"), session_id
        db.delete_sessions(session_ids=[session_id])
        assert store.get_row(result_id) is None, session_id
        # The payload bytes are gone too, not just the index row.
        assert store._fs_for_namespace(row["namespace"]).read(row["path"]) is None, session_id


def test_unscoped_delete_cleans_up_after_a_missing_session_row(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    store = agent._result_store

    # Remove only the session row, as a partial earlier cleanup would.
    sessions_table = db._get_table(table_type="sessions")
    with db.Session() as sess, sess.begin():
        sess.execute(sessions_table.delete().where(sessions_table.c.session_id == session_id))

    db.delete_sessions(session_ids=[session_id])
    assert store.get_row(result_id) is None
    runs_table = db._get_table(table_type="runs")
    with db.Session() as sess:
        from sqlalchemy import select as sa_select

        assert sess.execute(sa_select(runs_table).where(runs_table.c.session_id == session_id)).first() is None


def test_a_paused_run_continued_twice_keeps_both_payloads(db):
    import json

    from agno.run.requirement import RunRequirement
    from agno.tools.decorator import tool

    @tool(requires_confirmation=True)
    def fetch_gated_twice() -> str:
        """Fetch a large page behind a confirmation.

        Returns:
            str: the page body.
        """
        return BIG

    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_gated_twice"),
        db=db,
        tools=[fetch_gated_twice],
        offload_tool_results=True,
    )
    session_id = _sid()
    paused = agent.run("go", session_id=session_id)
    paused_tool = paused.tools[0].to_dict()

    def approve():
        tool_execution = ToolExecution.from_dict(json.loads(json.dumps(paused_tool)))
        tool_execution.confirmed = True
        return [RunRequirement(tool_execution=tool_execution)]

    agent.model = ScriptedToolModel(tool_name="fetch_gated_twice")
    first = agent.continue_run(run_id=paused.run_id, session_id=session_id, requirements=approve())
    first_id = _tool_messages(first)[0].content.split('id="')[1].split('"')[0]

    agent.model = ScriptedToolModel(tool_name="fetch_gated_twice")
    second = agent.continue_run(run_id=paused.run_id, session_id=session_id, fork=True, requirements=approve())
    # The fork replays the first continue's tool message; the new execution is the last one.
    second_id = _tool_messages(second)[-1].content.split('id="')[1].split('"')[0]

    assert first_id != second_id
    store = agent._result_store
    assert store.read(first_id).text.startswith("row 1:")
    assert store.read(second_id).text.startswith("row 1:")
    assert store.get_row(first_id)["path"] != store.get_row(second_id)["path"]


def test_a_large_user_input_value_is_offloaded(db):
    from agno.tools.user_control_flow import UserControlFlowTools

    model = ScriptedToolModel(
        tool_name="get_user_input",
        tool_args={"user_input_fields": [{"field_name": "doc", "field_type": "str", "field_description": "a doc"}]},
    )
    agent = Agent(model=model, db=db, tools=[UserControlFlowTools()], offload_tool_results=True)
    session_id = _sid()
    paused = agent.run("go", session_id=session_id)
    assert paused.is_paused
    for field in paused.tools[0].user_input_schema or []:
        field.value = BIG

    output = agent.continue_run(paused, session_id=session_id)
    tool_message = _tool_messages(output)[0]
    assert tool_message.content.startswith('<result id="res_')
    assert BIG not in tool_message.content
    result_id = tool_message.content.split('id="')[1].split('"')[0]
    assert "User inputs retrieved" in agent._result_store.read(result_id, 1, 1).text


async def test_a_large_user_input_value_is_offloaded_async(db):
    from agno.tools.user_control_flow import UserControlFlowTools

    model = ScriptedToolModel(
        tool_name="get_user_input",
        tool_args={"user_input_fields": [{"field_name": "doc", "field_type": "str", "field_description": "a doc"}]},
    )
    agent = Agent(model=model, db=db, tools=[UserControlFlowTools()], offload_tool_results=True)
    session_id = _sid()
    paused = await agent.arun("go", session_id=session_id)
    for field in paused.tools[0].user_input_schema or []:
        field.value = BIG

    output = await agent.acontinue_run(paused, session_id=session_id)
    assert _tool_messages(output)[0].content.startswith('<result id="res_')


def test_small_user_input_stays_inline(db):
    from agno.tools.user_control_flow import UserControlFlowTools

    model = ScriptedToolModel(
        tool_name="get_user_input",
        tool_args={"user_input_fields": [{"field_name": "doc", "field_type": "str", "field_description": "a doc"}]},
    )
    agent = Agent(model=model, db=db, tools=[UserControlFlowTools()], offload_tool_results=True)
    session_id = _sid()
    paused = agent.run("go", session_id=session_id)
    for field in paused.tools[0].user_input_schema or []:
        field.value = "short"

    output = agent.continue_run(paused, session_id=session_id)
    assert _tool_messages(output)[0].content.startswith("User inputs retrieved")


def test_scoped_delete_removes_only_the_callers_runs_in_a_shared_session(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    bob = agent.run("go", session_id=session_id, user_id="bob")
    bob_id = _tool_messages(bob)[0].content.split('id="')[1].split('"')[0]
    agent.model = ScriptedToolModel()
    alice = agent.run("go", session_id=session_id, user_id="alice")
    store = agent._result_store

    db.delete_sessions(session_ids=[session_id], user_id="alice")
    # Bob owns the session: it and his payload survive. Alice's own run is gone.
    assert db.get_session(session_id=session_id, session_type=SessionType.AGENT) is not None
    assert store.read(bob_id).text.startswith("row 1:")
    runs_table = db._get_table(table_type="runs")
    with db.Session() as sess:
        from sqlalchemy import select as sa_select

        remaining = [
            row[0] for row in sess.execute(sa_select(runs_table.c.run_id).where(runs_table.c.session_id == session_id))
        ]
    assert bob.run_id in remaining
    assert alice.run_id not in remaining


def test_an_external_result_that_ends_the_run_stays_inline(db):
    from agno.tools.decorator import tool

    @tool(external_execution=True)
    def fetch_final_on_client() -> str:
        """Fetch the final answer on the client side.

        Returns:
            str: the answer.
        """
        return "never runs here"

    agent = Agent(
        model=ScriptedToolModel(tool_name="fetch_final_on_client"),
        db=db,
        tools=[fetch_final_on_client],
        offload_tool_results=True,
    )
    session_id = _sid()
    paused = agent.run("go", session_id=session_id)
    # The client marks the posted execution as the run's final answer.
    paused.tools[0].result = BIG
    paused.tools[0].stop_after_tool_call = True

    output = agent.continue_run(paused, session_id=session_id)
    assert _tool_messages(output)[0].content == BIG


def test_read_result_refuses_a_result_belonging_to_another_user(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id, user_id="bob")
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]

    from agno.offload.tools import get_read_result_function
    from agno.run import RunContext

    as_alice = RunContext(session_id=session_id, run_id="r1", user_id="alice")
    reply = get_read_result_function(agent, run_context=as_alice).entrypoint(result_id=result_id)
    assert reply.startswith("Error: result ")
    assert "different user" in reply


def test_the_read_back_tools_do_not_spend_the_tool_call_limit(db):
    agent = Agent(
        model=ScriptedToolModel(),
        db=db,
        tools=[fetch_page],
        offload_tool_results=True,
        tool_call_limit=1,
    )
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]

    read_tool = agent.model.seen_functions["read_result"]
    call = agent.model.get_function_call_to_run_from_tool_execution(
        ToolExecution(tool_call_id="call-2", tool_name="read_result", tool_args={"result_id": result_id}),
        {"read_result": read_tool},
    )
    # The delegation already spent the budget; the read-back must still run.
    results: List[Any] = []
    list(
        agent.model.run_function_calls(
            [call],
            results,
            current_function_call_count=1,
            function_call_limit=1,
            result_store=agent._result_store,
        )
    )
    assert "Tool call limit" not in str(results[0].content)
    assert "row 1: " in str(results[0].content)


class ScriptedSequenceModel(ScriptedToolModel):
    """Calls one tool per turn from a script, then answers."""

    def __init__(self, script):
        super().__init__()
        self.script = script

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls <= len(self.script):
            name, args = self.script[self.calls - 1]
            if callable(args):
                args = args(self)
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": f"call-{self.calls}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="done", response_usage=MessageMetrics())


def _last_result_id(model: Model) -> dict:
    for message in reversed(getattr(model, "seen_messages", [])):
        if message.role == "tool" and 'id="res_' in str(message.content):
            return {"result_id": str(message.content).split('id="')[1].split('"')[0]}
    raise AssertionError("no offloaded result in the transcript yet")


class _SeesMessages(ScriptedSequenceModel):
    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.seen_messages = kwargs.get("messages") or (args[0] if args else [])
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.seen_messages = kwargs.get("messages") or (args[0] if args else [])
        return self._next()


def test_read_back_calls_do_not_spend_the_limit_across_turns(db):
    model = _SeesMessages([("fetch_page", {}), ("read_result", _last_result_id), ("fetch_page", {})])
    agent = Agent(model=model, db=db, tools=[fetch_page], offload_tool_results=True, tool_call_limit=2)
    output = agent.run("go", session_id=_sid())
    tool_messages = _tool_messages(output)
    assert len(tool_messages) == 3
    # Two fetches fit the limit of two; the read_result between them is free.
    assert "Tool call limit" not in str(tool_messages[2].content)
    assert str(tool_messages[2].content).startswith('<result id="res_')


async def test_read_back_calls_do_not_spend_the_limit_across_turns_async(db):
    model = _SeesMessages([("fetch_page", {}), ("read_result", _last_result_id), ("fetch_page", {})])
    agent = Agent(model=model, db=db, tools=[fetch_page], offload_tool_results=True, tool_call_limit=2)
    output = await agent.arun("go", session_id=_sid())
    tool_messages = _tool_messages(output)
    assert len(tool_messages) == 3
    assert "Tool call limit" not in str(tool_messages[2].content)


def test_the_limit_still_applies_to_ordinary_tools_with_offloading_on(db):
    model = _SeesMessages([("fetch_page", {}), ("fetch_page", {}), ("fetch_page", {})])
    agent = Agent(model=model, db=db, tools=[fetch_page], offload_tool_results=True, tool_call_limit=2)
    output = agent.run("go", session_id=_sid())
    tool_messages = _tool_messages(output)
    assert "Tool call limit" in str(tool_messages[2].content)


def test_search_result_renders_context_blocks_with_their_own_line_numbers(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    search = agent.model.seen_functions["search_result"]
    rendered = search.entrypoint(result_id=result_id, pattern=r"^row 10:", context_lines=1)
    assert "match at line 10 (char 0):" in rendered
    assert "9: row 9:" in rendered and "10: row 10:" in rendered and "11: row 11:" in rendered

    capped = search.entrypoint(result_id=result_id, pattern=r"^row")
    assert capped.startswith("First 20 matches in")


def test_turning_offloading_off_after_a_run_takes_effect(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    assert _tool_messages(agent.run("go", session_id=_sid()))[0].content.startswith('<result id="res_')
    agent.offload_tool_results = False
    agent.model = ScriptedToolModel()
    assert BIG in _tool_messages(agent.run("go", session_id=_sid()))[0].content
    assert agent.result_store is None


def test_a_changed_db_rebinds_the_store(db, tmp_path):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True)
    agent.run("go", session_id=_sid())
    other = SqliteDb(db_file=str(tmp_path / "other.db"))
    agent.db = other
    agent.model = ScriptedToolModel()
    output = agent.run("go", session_id=_sid())
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    assert agent.result_store.db is other
    assert other.get_tool_result(result_id) is not None


# ------------------------------------------------------------------
# Session delete reaches the payloads wherever a store put them
# ------------------------------------------------------------------
def test_session_delete_cleans_up_a_custom_filesystem(db, tmp_path):
    from agno.fs import FileSystem
    from agno.fs.local import LocalFileSystem

    payload_dir = tmp_path / "payloads"
    settings = ResultStore(fs=FileSystem(backend=LocalFileSystem(root=payload_dir), namespace="tool-results"))
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=settings)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    store = agent.result_store
    assert store.read(result_id).text.startswith("row 1:")
    files_before = [p for p in payload_dir.rglob("*") if p.is_file()]
    assert files_before, "the payload went to the custom filesystem"

    db.delete_sessions(session_ids=[session_id])
    assert store.get_row(result_id) is None
    assert [p for p in payload_dir.rglob("*") if p.is_file()] == []


def test_two_postgres_schemas_do_not_share_or_delete_each_others_payloads(db):
    from agno.db.postgres import PostgresDb

    if not isinstance(db, PostgresDb):
        pytest.skip("PostgreSQL only: every schema shares one payload table")
    schema_a, schema_b = f"{PG_SCHEMA}_a", f"{PG_SCHEMA}_b"
    db_a = PostgresDb(db_url=PG_URL, db_schema=schema_a)
    db_b = PostgresDb(db_url=PG_URL, db_schema=schema_b)
    try:
        session_id = "offload-agent-shared-session-id"
        ids = {}
        for key, tenant_db in (("a", db_a), ("b", db_b)):
            agent = Agent(model=ScriptedToolModel(), db=tenant_db, tools=[fetch_page], offload_tool_results=True)
            # The same session, run and call ids in both schemas: the worst
            # case for a payload table every schema shares.
            output = agent.run("go", session_id=session_id, run_id="shared-run-id")
            ids[key] = (agent, _tool_messages(output)[0].content.split('id="')[1].split('"')[0])
        agent_a, rid_a = ids["a"]
        agent_b, rid_b = ids["b"]
        assert agent_a.result_store.read(rid_a).text.startswith("row 1:")
        assert agent_b.result_store.read(rid_b).text.startswith("row 1:")

        # A fresh db object, as a new process would have: no store registered,
        # so the cascade falls back to the default payload table.
        PostgresDb(db_url=PG_URL, db_schema=schema_a).delete_session(session_id=session_id)
        # Tenant B's payload and index row survive tenant A's delete.
        assert agent_b.result_store.get_row(rid_b) is not None
        assert agent_b.result_store.read(rid_b).text.startswith("row 1:")
        assert agent_a.result_store.get_row(rid_a) is None
    finally:
        with db_a.db_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_a}" CASCADE'))
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_b}" CASCADE'))


async def test_an_async_db_cascades_payloads_written_by_a_sync_store(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    path = str(tmp_path / "shared.db")
    sync_db = SqliteDb(db_file=path)
    agent = Agent(model=ScriptedToolModel(), db=sync_db, tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    store = agent.result_store
    row = store.get_row(result_id)

    async_db = AsyncSqliteDb(db_file=path)
    await async_db.delete_sessions(session_ids=[session_id])
    assert store.get_row(result_id) is None
    assert store._fs_for_namespace(row["namespace"]).read(row["path"]) is None


def test_an_explicit_false_round_trips_and_unset_is_omitted(db):
    explicit = Agent(model=ScriptedToolModel(), db=db, offload_tool_results=False).to_dict()
    assert explicit["offload_tool_results"] is False
    explicit.pop("model", None)
    assert Agent.from_dict(explicit).offload_tool_results is False
    unset = Agent(model=ScriptedToolModel(), db=db).to_dict()
    assert "offload_tool_results" not in unset
    unset.pop("model", None)
    assert Agent.from_dict(unset).offload_tool_results is None


def test_the_filesystem_registry_holds_one_entry_per_storage(db):
    for _ in range(25):
        Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=True).initialize_agent()
    assert len(db.tool_result_filesystems) == 1


def test_a_fresh_process_still_removes_default_table_payloads(tmp_path):
    path = str(tmp_path / "fresh.db")
    agent = Agent(model=ScriptedToolModel(), db=SqliteDb(db_file=path), tools=[fetch_page], offload_tool_results=True)
    session_id = _sid()
    output = agent.run("go", session_id=session_id)
    result_id = _tool_messages(output)[0].content.split('id="')[1].split('"')[0]
    row = agent.result_store.get_row(result_id)

    # A db object with no store registered, as a new process would have.
    fresh = SqliteDb(db_file=path)
    assert getattr(fresh, "tool_result_filesystems", None) is None
    fresh.delete_session(session_id=session_id)
    assert agent.result_store.get_row(result_id) is None
    assert agent.result_store._fs_for_namespace(row["namespace"]).read(row["path"]) is None


def test_a_payload_this_process_cannot_reach_is_reported(tmp_path, monkeypatch):
    from agno.db.sqlite import sqlite as sqlite_module
    from agno.fs import FileSystem
    from agno.fs.local import LocalFileSystem

    path = str(tmp_path / "custom.db")
    payload_dir = tmp_path / "payloads"
    settings = ResultStore(fs=FileSystem(backend=LocalFileSystem(root=payload_dir), namespace="tool-results"))
    agent = Agent(
        model=ScriptedToolModel(), db=SqliteDb(db_file=path), tools=[fetch_page], offload_tool_results=settings
    )
    session_id = _sid()
    agent.run("go", session_id=session_id)

    warnings: List[str] = []
    monkeypatch.setattr(sqlite_module, "log_warning", warnings.append)
    # A fresh db object knows nothing about the custom filesystem: the index
    # rows go, the payload stays on disk, and the gap is reported.
    SqliteDb(db_file=path).delete_session(session_id=session_id)
    assert any("no store for" in w for w in warnings), warnings
    assert [p for p in payload_dir.rglob("*") if p.is_file()]
