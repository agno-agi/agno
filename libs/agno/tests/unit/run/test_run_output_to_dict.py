"""Unit tests for RunOutput.to_dict() / TeamRunOutput.to_dict().

These pin the observable contract of the serialization head, which is what the
session row is built from on every save:

  * the same keys and values as before, for every field that survives the
    skip set;
  * a dataclass-valued ``content`` is still converted to a plain dict;
  * the kept dict fields are still copies, so mutating the serialized result
    cannot reach back into the RunOutput.
"""

from dataclasses import dataclass

from pydantic import BaseModel

from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput


@dataclass
class _DataclassContent:
    a: int
    b: str


class _ModelContent(BaseModel):
    a: int
    b: str


def _run_output(**overrides) -> RunOutput:
    kwargs = dict(
        run_id="run-1",
        agent_id="agent-1",
        agent_name="agent",
        session_id="session-1",
        user_id="user-1",
        content="hello",
        content_type="str",
        model="test-model",
        model_provider="test",
        messages=[Message(role="user", content="hi")],
        tools=[ToolExecution(tool_name="t", tool_call_id="c", result="r")],
        status=RunStatus.completed,
        created_at=1750000000,
    )
    kwargs.update(overrides)
    return RunOutput(**kwargs)


def test_to_dict_keeps_scalar_fields_and_rebuilds_the_rest():
    run = _run_output(metadata={"tag": "x"})
    d = run.to_dict()

    assert d["run_id"] == "run-1"
    assert d["agent_id"] == "agent-1"
    assert d["session_id"] == "session-1"
    assert d["model"] == "test-model"
    assert d["content"] == "hello"
    assert d["status"] == RunStatus.completed.value
    assert d["created_at"] == 1750000000

    # the expensive fields are rebuilt through their own serializers
    assert d["messages"] == [m.to_dict() for m in run.messages]
    assert d["tools"] == [t.to_dict() for t in run.tools]
    assert d["metadata"] == {"tag": "x"}


def test_to_dict_omits_none_valued_fields():
    d = _run_output(reasoning_content=None).to_dict()
    assert "reasoning_content" not in d
    assert "parent_run_id" not in d


def test_to_dict_converts_a_dataclass_content_to_a_dict():
    d = _run_output(content=_DataclassContent(a=1, b="x")).to_dict()
    assert d["content"] == {"a": 1, "b": "x"}


def test_to_dict_handles_a_pydantic_content():
    d = _run_output(content=_ModelContent(a=1, b="x")).to_dict()
    assert d["content"] == {"a": 1, "b": "x"}


def test_to_dict_does_not_alias_the_kept_dict_fields():
    """Mutating the serialized result must not reach back into the RunOutput."""
    state = {"k": [1, 2, 3]}
    provider_data = {"raw": {"nested": 1}}
    run = _run_output(session_state=state, model_provider_data=provider_data)

    d = run.to_dict()
    d["session_state"]["injected"] = True
    d["session_state"]["k"].append(99)
    d["model_provider_data"]["injected"] = True

    assert state == {"k": [1, 2, 3]}
    assert provider_data == {"raw": {"nested": 1}}
    assert run.session_state == {"k": [1, 2, 3]}


def test_team_run_output_to_dict_matches_the_same_contract():
    run = TeamRunOutput(
        run_id="run-1",
        team_id="team-1",
        team_name="team",
        session_id="session-1",
        content="hello",
        content_type="str",
        model="test-model",
        model_provider="test",
        messages=[Message(role="user", content="hi")],
        status=RunStatus.completed,
        created_at=1750000000,
    )
    d = run.to_dict()

    assert d["run_id"] == "run-1"
    assert d["team_id"] == "team-1"
    assert d["content"] == "hello"
    assert d["status"] == RunStatus.completed.value
    assert d["messages"] == [m.to_dict() for m in run.messages]
    assert "metrics" not in d


def test_team_run_output_to_dict_does_not_alias_kept_dicts():
    provider_data = {"raw": {"nested": 1}}
    run = TeamRunOutput(
        run_id="run-1",
        team_id="team-1",
        session_id="session-1",
        content="hello",
        model_provider_data=provider_data,
        messages=[Message(role="user", content="hi")],
        status=RunStatus.completed,
        created_at=1750000000,
    )
    run.to_dict()["model_provider_data"]["injected"] = True
    assert provider_data == {"raw": {"nested": 1}}
