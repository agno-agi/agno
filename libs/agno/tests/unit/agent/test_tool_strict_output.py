from unittest.mock import MagicMock

from pydantic import BaseModel

from agno.agent._tools import parse_tools
from agno.agent.agent import Agent
from agno.run.base import RunContext


class _Decision(BaseModel):
    action: str
    reason: str


def _mock_model(strict_output: bool):
    model = MagicMock()
    model.supports_native_structured_outputs = True
    model.strict_output = strict_output
    return model


def test_parse_tools_does_not_force_strict_schemas_when_model_guides_output():
    def choose(city: str) -> str:
        return city

    agent = Agent(tools=[choose])
    run_context = RunContext(run_id="run", session_id="session", output_schema=_Decision)

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model(strict_output=False), run_context=run_context)

    assert len(functions) == 1
    assert functions[0].strict is None
    assert "additionalProperties" not in functions[0].parameters


def test_parse_tools_keeps_strict_schemas_when_model_requires_strict_output():
    def choose(city: str) -> str:
        return city

    agent = Agent(tools=[choose])
    run_context = RunContext(run_id="run", session_id="session", output_schema=_Decision)

    functions = parse_tools(agent=agent, tools=agent.tools, model=_mock_model(strict_output=True), run_context=run_context)

    assert len(functions) == 1
    assert functions[0].strict is True
    assert functions[0].parameters["additionalProperties"] is False
