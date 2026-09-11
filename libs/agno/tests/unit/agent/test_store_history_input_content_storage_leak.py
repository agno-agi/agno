"""End-to-end storage evidence for the store_history_messages=False history leak (#9419).

The unit tests in test_store_history_input_content_leak.py prove the scrub function filters
`input.input_content`. This one proves the symptom the issue reported: after a real team
delegation and a real SqliteDb write, the member's opted-out history is not in the stored row
at `input.input_content`.

The assertion is on the JSON *path* the marker appears at, not on its mere presence: the same
marker legitimately survives elsewhere in the session (the member's own run-1 output and
messages, and the team's own copy of the delegate result), and only the member's history copy
is opted out. A whole-row substring search would fail for the wrong reason.
"""

import json
import sqlite3
from typing import Any, List

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.team.team import Team

MARKER = "MARKER-SECRET-IN-HISTORY"


class ScriptedModel(Model):
    """Replays a fixed script of turns: ("tool", name, args) or ("text", content)."""

    def __init__(self, script: List[tuple]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.instructions = None
        self._script = list(script)
        self._index = 0

    def _script_turn(self, assistant_message: Message, model_response: ModelResponse) -> None:
        assistant_message.metrics = assistant_message.metrics or MessageMetrics()
        step = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        if step[0] == "tool":
            assistant_message.tool_calls = [
                {
                    "id": f"call_{self._index}",
                    "type": "function",
                    "function": {"name": step[1], "arguments": json.dumps(step[2])},
                }
            ]
        else:
            assistant_message.content = step[1]
            model_response.content = step[1]

    def _process_model_response(self, messages, assistant_message, model_response, **kwargs) -> None:
        self._script_turn(assistant_message, model_response)

    async def _aprocess_model_response(self, messages, assistant_message, model_response, **kwargs) -> None:
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


def _marker_paths(db_file: str) -> List[str]:
    """JSON paths, inside the stored `runs` column, at which the marker appears."""
    found: List[str] = []
    connection = sqlite3.connect(db_file)
    try:
        for (runs,) in connection.execute("SELECT runs FROM agno_sessions"):
            if not runs:
                continue
            parsed = json.loads(runs)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)

            def walk(node: Any, path: str = "") -> None:
                if isinstance(node, dict):
                    for key, value in node.items():
                        walk(value, f"{path}.{key}")
                elif isinstance(node, list):
                    for index, value in enumerate(node):
                        walk(value, f"{path}[{index}]")
                elif isinstance(node, str) and MARKER in node:
                    found.append(path)

            walk(parsed)
    finally:
        connection.close()
    return found


def _delegate_twice(db_file: str, *, store_history_messages: bool) -> None:
    """Run a team twice so the member's second run receives its own history as input."""
    db = SqliteDb(db_file=db_file)
    member = Agent(
        id="researcher",
        name="researcher",
        model=ScriptedModel([("text", MARKER)]),
        db=db,
        add_history_to_context=True,
        store_history_messages=store_history_messages,
        telemetry=False,
    )
    team = Team(
        id="lead",
        name="lead",
        members=[member],
        db=db,
        model=ScriptedModel(
            [("tool", "delegate_task_to_member", {"member_id": "researcher", "task": "go"}), ("text", "ok")]
        ),
        telemetry=False,
    )
    team.run("first", session_id="shared-session")

    # Second turn: the member now has history, which the delegate path passes as its input.
    member.model = ScriptedModel([("text", "second answer")])
    team.model = ScriptedModel(
        [("tool", "delegate_task_to_member", {"member_id": "researcher", "task": "again"}), ("text", "ok2")]
    )
    team.run("second", session_id="shared-session")


def test_member_history_is_not_stored_on_input_content(tmp_path):
    """The reported symptom: the marker in the raw runs column at input.input_content."""
    db_file = str(tmp_path / "history.db")

    _delegate_twice(db_file, store_history_messages=False)

    paths = _marker_paths(db_file)
    leaked = [path for path in paths if ".input.input_content" in path]
    assert not leaked, f"history reached storage through input_content at {leaked}"


def test_the_delegation_actually_happened(tmp_path):
    """Guard against the leak test passing because nothing ran.

    The marker must still be present somewhere -- the member's own run-1 output is stored
    legitimately -- so an empty result set would mean the scenario never executed.
    """
    db_file = str(tmp_path / "sanity.db")

    _delegate_twice(db_file, store_history_messages=False)

    assert _marker_paths(db_file), "the scenario stored nothing; the leak test would be vacuous"


def test_history_is_stored_on_input_content_when_the_flag_is_on(tmp_path):
    """Control: with the flag on the history is kept, so the negative assertion has teeth."""
    db_file = str(tmp_path / "kept.db")

    _delegate_twice(db_file, store_history_messages=True)

    paths = _marker_paths(db_file)
    assert any(".input.input_content" in path for path in paths), (
        "with store_history_messages=True the history should still be persisted on input_content; "
        "if this fails, the leak test passes for the wrong reason"
    )
