"""End-to-end storage evidence for the store_tool_messages=False tool-result leak (#9426).

The unit tests in test_store_tool_result_scrub_leak.py prove the scrub function blanks the
stored results. This one proves the thing the issue actually reported: after a real run
through the real tool loop and a real SqliteDb write, the tool's return value is not in the
session row.

The model is scripted at the provider seam (`_process_model_response`) so the framework's own
tool loop still runs, executes the tool and populates `run_response.tools` — the leak has to
reach storage the same way it does in production, not be planted by the test.
"""

from typing import Any

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse

SECRET = "SSN-000-11-2222-BASELINE"


def peek() -> str:
    """Return a sensitive value the caller does not want persisted."""
    return SECRET


class ScriptedToolCallModel(Model):
    """Calls `peek` once, then answers. No network, real tool loop."""

    def __init__(self):
        super().__init__(id="scripted-model", name="scripted-model", provider="test")
        self.instructions = None
        self._turn = 0

    def _script_turn(self, assistant_message: Message, model_response: ModelResponse) -> None:
        assistant_message.metrics = assistant_message.metrics or MessageMetrics()
        if self._turn == 0:
            self._turn += 1
            assistant_message.tool_calls = [
                {"id": "call_1", "type": "function", "function": {"name": "peek", "arguments": "{}"}}
            ]
        else:
            assistant_message.content = "done"
            model_response.content = "done"

    def _process_model_response(
        self,
        messages,
        assistant_message: Message,
        model_response: ModelResponse,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
        compress_tool_results: bool = False,
    ) -> None:
        self._script_turn(assistant_message, model_response)

    async def _aprocess_model_response(
        self,
        messages,
        assistant_message: Message,
        model_response: ModelResponse,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
        compress_tool_results: bool = False,
    ) -> None:
        self._script_turn(assistant_message, model_response)

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> Any:
        return ModelResponse()

    async def ainvoke(self, *args, **kwargs) -> Any:
        return ModelResponse()

    def invoke_stream(self, *args, **kwargs):
        yield ModelResponse()

    async def ainvoke_stream(self, *args, **kwargs):
        yield ModelResponse()
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse()


def _stored_bytes(db_file: str) -> str:
    """Every row of every table, stringified — the row as it actually landed on disk."""
    import sqlite3

    connection = sqlite3.connect(db_file)
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        dumped = []
        for table in tables:
            for row in connection.execute(f"SELECT * FROM {table}").fetchall():  # noqa: S608
                dumped.append(str(row))
        return "\n".join(dumped)
    finally:
        connection.close()


def _run_agent(db_file: str, *, store_tool_messages: bool) -> Agent:
    agent = Agent(
        model=ScriptedToolCallModel(),
        tools=[peek],
        db=SqliteDb(db_file=db_file),
        store_tool_messages=store_tool_messages,
        session_id="leak-session",
        telemetry=False,
    )
    agent.run("go")
    return agent


def test_tool_result_is_not_in_the_session_row_when_flag_is_off(tmp_path):
    """The reported symptom: `sensitive paths: ['$[0].tools[0].result']` in the stored row."""
    db_file = str(tmp_path / "leak.db")

    agent = _run_agent(db_file, store_tool_messages=False)

    # The tool really did run and really did return the secret on this run.
    last_run = agent.get_last_run_output()
    assert last_run is not None
    assert any(tool.tool_name == "peek" for tool in last_run.tools or []), (
        "the scripted model must actually drive the tool loop, or this test proves nothing"
    )

    assert SECRET not in _stored_bytes(db_file), "the tool result must not reach the database"


def test_tool_result_is_in_the_session_row_when_flag_is_on(tmp_path):
    """Control: with the flag on the value is stored, so the test above is not vacuous."""
    db_file = str(tmp_path / "kept.db")

    _run_agent(db_file, store_tool_messages=True)

    assert SECRET in _stored_bytes(db_file), (
        "with store_tool_messages=True the result should still be persisted; if this fails the "
        "other test passes for the wrong reason"
    )


@pytest.mark.asyncio
async def test_tool_result_is_not_in_the_session_row_on_the_async_path(tmp_path):
    """arun writes through the same scrub; both variants are covered."""
    db_file = str(tmp_path / "leak_async.db")

    agent = Agent(
        model=ScriptedToolCallModel(),
        tools=[peek],
        db=SqliteDb(db_file=db_file),
        store_tool_messages=False,
        session_id="leak-session-async",
        telemetry=False,
    )
    await agent.arun("go")

    last_run = agent.get_last_run_output()
    assert last_run is not None
    assert any(tool.tool_name == "peek" for tool in last_run.tools or []), (
        "the async path must actually drive the tool loop, or this test proves nothing"
    )

    assert SECRET not in _stored_bytes(db_file)
