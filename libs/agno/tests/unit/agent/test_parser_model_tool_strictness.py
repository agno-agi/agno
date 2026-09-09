"""Regression tests for strict tool mode vs. parser_model in parse_tools.

When a parser_model is set, the base model does not produce the structured output
(the tool-less parser_model does), so the base model's tools must not be marked strict.
Forcing strict tools makes providers compile a grammar over every tool schema, which can
exceed provider limits (e.g. Anthropic: "the compiled grammar is too large").
"""

from unittest.mock import MagicMock

from pydantic import BaseModel

from agno.agent._tools import parse_tools
from agno.agent.agent import Agent
from agno.run import RunContext


class _Output(BaseModel):
    summary: str


def _native_structured_model():
    model = MagicMock()
    model.supports_native_structured_outputs = True
    return model


def _sample_tool(query: str) -> str:
    """A sample tool."""
    return "ok"


def _run_context() -> RunContext:
    return RunContext(run_id="test-run", session_id="test-session", output_schema=_Output)


def test_tools_strict_with_output_schema_and_no_parser_model():
    """Base model owns the structured output, so its tools are marked strict."""
    agent = Agent(tools=[_sample_tool], output_schema=_Output)

    functions = parse_tools(
        agent=agent,
        tools=agent.tools,
        model=_native_structured_model(),
        run_context=_run_context(),
    )

    assert len(functions) == 1
    assert functions[0].strict is True


def test_tools_not_strict_when_parser_model_is_set():
    """parser_model owns the structured output, so base model tools must not be strict."""
    agent = Agent(tools=[_sample_tool], output_schema=_Output)
    agent.parser_model = _native_structured_model()

    functions = parse_tools(
        agent=agent,
        tools=agent.tools,
        model=_native_structured_model(),
        run_context=_run_context(),
    )

    assert len(functions) == 1
    assert not functions[0].strict
