"""When a framework produces a validated model (user built structured output into
their program/graph), the adapter must return the model untouched so a run-level
output_schema validates against it rather than a stringified repr.

These stub the framework objects, so they run without live model calls.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from agno.agents.dspy import DSPyAgent
from agno.agents.langgraph import LangGraphAgent


class Movie(BaseModel):
    title: str
    year: int


MOVIE = Movie(title="Inception", year=2010)


# The adapters import their framework at call time; gate each framework's tests
# on it being installed (the dev .venv lacks them — they live in .venvs/demo).
def _installed(mod: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(mod) is not None


dspy_only = pytest.mark.skipif(not _installed("dspy"), reason="dspy not installed")
langgraph_only = pytest.mark.skipif(
    not (_installed("langgraph") and _installed("langchain_core")),
    reason="langgraph/langchain not installed",
)


# --- DSPy ------------------------------------------------------------------


class _Prediction:
    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)


class _FakeDSPyProgram:
    """Stand-in DSPy program whose output field carries a model instance."""

    def __init__(self, output_value):
        self._output = output_value

    def __call__(self, **kwargs):
        return _Prediction(answer=self._output)


@dspy_only
@pytest.mark.asyncio
async def test_dspy_returns_model_instance_untouched():
    agent = DSPyAgent(name="d", program=_FakeDSPyProgram(MOVIE))
    result = await agent.arun("the movie Inception", output_schema=Movie)

    assert isinstance(result.content, Movie)
    assert result.content.title == "Inception"
    assert result.content_type == "Movie"


@dspy_only
@pytest.mark.asyncio
async def test_dspy_non_model_output_still_stringified():
    agent = DSPyAgent(name="d", program=_FakeDSPyProgram("plain answer"))
    result = await agent.arun("hi")

    assert result.content == "plain answer"
    assert result.content_type == "str"


# --- LangGraph -------------------------------------------------------------


class _FakeGraph:
    """Stand-in compiled graph returning a chosen state dict from ainvoke."""

    def __init__(self, state: dict):
        self._state = state

    async def ainvoke(self, graph_input: Any, config: Any = None):
        return self._state


@langgraph_only
@pytest.mark.asyncio
async def test_langgraph_returns_model_at_output_key():
    graph = _FakeGraph({"question": "q", "movie": MOVIE})
    agent = LangGraphAgent(name="lg", graph=graph, input_key="question", output_key="movie")
    result = await agent.arun("the movie Inception", output_schema=Movie)

    assert isinstance(result.content, Movie)
    assert result.content.title == "Inception"
    assert result.content_type == "Movie"


@langgraph_only
@pytest.mark.asyncio
async def test_langgraph_message_channel_still_works():
    """Default output_key='messages': the AIMessage path is unchanged."""
    from langchain_core.messages import AIMessage

    graph = _FakeGraph({"messages": [AIMessage(content="hello there")]})
    agent = LangGraphAgent(name="lg", graph=graph)
    result = await agent.arun("greet")

    assert result.content == "hello there"
    assert result.content_type == "str"
