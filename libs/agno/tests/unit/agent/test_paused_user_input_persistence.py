"""Regression tests for issue #11144.

``UserInputField.to_dict()`` read ``field_type.__name__``, which a PEP 604
annotation such as ``int | None`` does not have (``types.UnionType``). The user
input schema is serialized while a paused run is written to the database, so the
upsert raised, was caught and logged as a warning, and the run was never stored:
the caller saw a healthy paused run that no other process could resume.

The unit-level serialization case lives in ``tests/unit/tools/test_functions.py``.
These tests cover the failure the user actually hit, with SQLite as a real DB so
the write happens end-to-end:

1. the paused run is readable back from the runs table, and
2. ``continue_run(run_id=...)`` finds it instead of raising ``RunNotFoundError``.

Both the sync and async run paths are covered, since each persists separately.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, List, Optional, Tuple

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.tools.decorator import tool
from agno.tools.function import UserInputField

_ORDERED: List[str] = []


@tool(requires_user_input=True, user_input_fields=["quantity"])
def place_order(item: str, quantity: int | None = None) -> str:
    """Place an order.

    Args:
        item (str): What to order.
        quantity (int | None): How many to order, supplied by the human.
    """
    _ORDERED.append(f"{quantity} x {item}")
    return f"Ordered {quantity} x {item}"


class ScriptedModel(Model):
    """Offline model replaying a fixed script of tool calls and messages."""

    def __init__(self, script: List[Tuple[str, Any]]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self._script = script
        self._turn = 0

    def _next(self) -> ModelResponse:
        step = self._script[min(self._turn, len(self._script) - 1)]
        self._turn += 1
        response = ModelResponse(role="assistant")
        if step[0] == "tool":
            _, name, arguments, call_id = step
            response.tool_calls = [
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
            ]
        else:
            response.content = step[1]
        response.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        return response

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def parse_args(self, *args, **kwargs) -> dict:
        return {}

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._next()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._next()


def _build_agent(db_file: str) -> Tuple[Agent, SqliteDb]:
    db = SqliteDb(db_file=db_file)
    agent = Agent(
        model=ScriptedModel([("tool", "place_order", {"item": "widget"}, "call-1"), ("text", "Order placed.")]),
        tools=[place_order],
        db=db,
        telemetry=False,
    )
    return agent, db


def _answer(run_output, value: int) -> None:
    """Fill every pending user input field, as a caller or UI would."""
    for requirement in run_output.active_requirements or []:
        if requirement.needs_user_input:
            for field in requirement.user_input_schema or []:
                if field.value is None:
                    field.value = value


def test_paused_union_annotated_run_persists_and_resumes():
    _ORDERED.clear()
    with tempfile.TemporaryDirectory() as directory:
        agent, db = _build_agent(str(Path(directory) / "orders.db"))

        paused = agent.run("Order a widget.", session_id="orders")
        assert paused.status == RunStatus.paused

        # 1. The paused run has to reach the runs table; the upsert failure was
        #    swallowed as a warning, so only a read-back exposes it.
        assert db.get_run(paused.run_id) is not None, "the paused run was not persisted"

        # 2. Resuming by run_id is what a separate request or process does.
        _answer(paused, 3)
        resumed = agent.continue_run(run_id=paused.run_id, session_id="orders", requirements=paused.requirements)

        assert resumed.status == RunStatus.completed
        assert _ORDERED == ["3 x widget"]
        db.close()


@pytest.mark.asyncio
async def test_paused_union_annotated_run_persists_and_resumes_async():
    _ORDERED.clear()
    with tempfile.TemporaryDirectory() as directory:
        agent, db = _build_agent(str(Path(directory) / "orders.db"))

        paused = await agent.arun("Order a widget.", session_id="orders")
        assert paused.status == RunStatus.paused
        assert db.get_run(paused.run_id) is not None, "the paused run was not persisted"

        _answer(paused, 3)
        resumed = await agent.acontinue_run(run_id=paused.run_id, session_id="orders", requirements=paused.requirements)

        assert resumed.status == RunStatus.completed
        assert _ORDERED == ["3 x widget"]
        db.close()


@pytest.mark.parametrize(
    "annotation,serialized",
    [
        (int, "int"),
        (int | None, "int | None"),
        (Optional[int], "typing.Optional[int]"),
        # Parameterized generics now carry their argument. This is a change from
        # the bare "list"/"List" the old __name__ read produced; field_type is
        # descriptive only -- no coercion or validation reads it back -- so the
        # string is pinned here rather than kept stable.
        (list[str], "list[str]"),
        (List[str], "typing.List[str]"),
    ],
)
def test_field_type_serializes_for_every_annotation_form(annotation, serialized):
    assert UserInputField(name="quantity", field_type=annotation).to_dict()["field_type"] == serialized
