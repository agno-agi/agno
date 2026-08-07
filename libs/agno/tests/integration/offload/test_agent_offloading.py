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
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
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
            conn.execute(text('DROP TABLE IF EXISTS "fs".agno_fs'))


def _sid() -> str:
    return f"offload-{uuid.uuid4().hex[:10]}"


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
    assert len(tool_message.content) < 1500
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


def test_explicit_int_threshold_is_honoured(db):
    agent = Agent(model=ScriptedToolModel(), db=db, tools=[fetch_page], offload_tool_results=12_000)
    assert agent._result_store is None or agent._result_store.threshold == 12_000
    agent.initialize_agent()
    assert agent._result_store.threshold == 12_000


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
