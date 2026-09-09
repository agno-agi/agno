"""
Tool-Call Run Comparison Benchmark
==================================

One single-turn run containing one real tool execution per framework: the
mocked model requests a tool call, the framework dispatches and executes
the actual function, and a second model turn produces the final answer.
This is the benchmark where Agno's deferred tool-schema extraction is paid
(it happens at run time, not construction), so it complements the
construction benchmark rather than repeating its story.

CrewAI is not included: with a custom model its tool use goes through a
text-based action protocol whose exact format is internal to the framework
version, so a mock would be testing the mock rather than the framework.

Every variant asserts the tool actually executed.
"""

import itertools

from _compare import (
    MockToolModel,
    add_numbers,
    ensure_completed,
    iterations,
    run_benchmarks,
)
from agno.agent import Agent as AgnoAgent
from agno.eval.performance import PerformanceEval

# ---------------------------------------------------------------------------
# Agno
# ---------------------------------------------------------------------------
agno_agent = AgnoAgent(model=MockToolModel(), tools=[add_numbers], telemetry=False)


def tool_run_compare_agno():
    return ensure_completed(
        agno_agent.run("Add 1 and 2."),
        expected_content="done",
        expect_tool_success=True,
    )


# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.tools import tool as lc_tool  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402


@lc_tool
def add_numbers_lc(a: int, b: int) -> int:
    """Add two numbers and return the result."""
    return a + b


_call_ids = itertools.count()


def _tool_then_answer():
    # Fresh message objects every turn: the message reducer dedupes by id
    while True:
        yield AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "add_numbers_lc",
                    "args": {"a": 1, "b": 2},
                    "id": "call_" + str(next(_call_ids)),
                }
            ],
        )
        yield AIMessage(content="done")


class ToolFakeChatModel(GenericFakeChatModel):
    # The scripted responses already contain the tool calls; binding is a no-op
    def bind_tools(self, tools, **kwargs):
        return self


langgraph_agent = create_react_agent(
    model=ToolFakeChatModel(messages=_tool_then_answer()), tools=[add_numbers_lc]
)


def tool_run_compare_langgraph():
    out = langgraph_agent.invoke({"messages": [("user", "Add 1 and 2.")]})
    messages = out["messages"]
    executed = any(type(m).__name__ == "ToolMessage" for m in messages)
    if not executed or messages[-1].content != "done":
        raise RuntimeError(
            "tool loop did not execute: " + str([type(m).__name__ for m in messages])
        )
    return out


# ---------------------------------------------------------------------------
# PydanticAI
# ---------------------------------------------------------------------------
from pydantic_ai import Agent as PydanticAgent  # noqa: E402
from pydantic_ai.models.test import TestModel  # noqa: E402

# TestModel calls every registered tool once, then produces the final output
pydantic_agent = PydanticAgent(
    TestModel(custom_output_text="done"), tools=[add_numbers]
)


def tool_run_compare_pydantic_ai():
    result = pydantic_agent.run_sync("Add 1 and 2.")
    executed = any(
        type(part).__name__ == "ToolReturnPart"
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
    )
    if not executed or result.output != "done":
        raise RuntimeError("tool loop did not execute")
    return result


# ---------------------------------------------------------------------------
# Create Evaluations
# ---------------------------------------------------------------------------
BENCHMARKS = [
    PerformanceEval(
        name="tool_run_compare_agno",
        func=tool_run_compare_agno,
        num_iterations=iterations(200),
        telemetry=False,
    ),
    PerformanceEval(
        name="tool_run_compare_langgraph",
        func=tool_run_compare_langgraph,
        num_iterations=iterations(100),
        telemetry=False,
    ),
    PerformanceEval(
        name="tool_run_compare_pydantic_ai",
        func=tool_run_compare_pydantic_ai,
        num_iterations=iterations(50),
        telemetry=False,
    ),
]

# ---------------------------------------------------------------------------
# Run Evaluations
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks(BENCHMARKS, group="comparison_tool_run")
