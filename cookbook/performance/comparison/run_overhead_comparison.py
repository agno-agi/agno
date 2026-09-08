"""
Run Overhead Comparison Benchmark
=================================

One mocked single-turn run per framework: a short system prompt, one user
message, no tools, the model replaced by each framework's own testing or
custom-model interface returning a canned reply. No network. The number is
the framework's per-request orchestration overhead.

Where each mock cuts in (each replaces the provider at the framework's own
model boundary, so numbers are per-framework floors):
- Agno: Model subclass returning a canned ModelResponse (drives the full loop)
- LangGraph: langchain's GenericFakeChatModel
- PydanticAI: the library's public TestModel
- CrewAI: a BaseLLM subclass returning a canned string; a fresh Task and
  Crew are built per run because a Crew kickoff is CrewAI's unit of request
  execution (its Agent is reused, matching the other frameworks)
"""

import itertools

from _compare import MockModel, ensure_completed, iterations, run_benchmarks
from agno.agent import Agent as AgnoAgent
from agno.eval.performance import PerformanceEval

SYSTEM_PROMPT = "Be concise, reply with one sentence."
USER_MESSAGE = "What is the capital of France?"


# ---------------------------------------------------------------------------
# Agno
# ---------------------------------------------------------------------------
agno_agent = AgnoAgent(model=MockModel(), system_message=SYSTEM_PROMPT, telemetry=False)


def run_compare_agno():
    return ensure_completed(agno_agent.run(USER_MESSAGE), expected_content="ok")


# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402

langgraph_agent = create_react_agent(
    model=GenericFakeChatModel(messages=itertools.cycle([AIMessage(content="ok")])),
    tools=[],
)


def run_compare_langgraph():
    out = langgraph_agent.invoke(
        {"messages": [("system", SYSTEM_PROMPT), ("user", USER_MESSAGE)]}
    )
    if out["messages"][-1].content != "ok":
        raise RuntimeError("langgraph run returned unexpected content")
    return out


# ---------------------------------------------------------------------------
# PydanticAI
# ---------------------------------------------------------------------------
from pydantic_ai import Agent as PydanticAgent  # noqa: E402
from pydantic_ai.models.test import TestModel  # noqa: E402

pydantic_agent = PydanticAgent(
    TestModel(custom_output_text="ok"), system_prompt=SYSTEM_PROMPT
)


def run_compare_pydantic_ai():
    result = pydantic_agent.run_sync(USER_MESSAGE)
    if result.output != "ok":
        raise RuntimeError("pydantic_ai run returned unexpected content")
    return result


# ---------------------------------------------------------------------------
# CrewAI
# ---------------------------------------------------------------------------
from crewai import Agent as CrewAgent  # noqa: E402
from crewai import BaseLLM, Crew, Task  # noqa: E402


class CrewMockLLM(BaseLLM):
    def __init__(self):
        super().__init__(model="mock-model")

    def call(
        self, messages, tools=None, callbacks=None, available_functions=None, **kwargs
    ):
        return "ok"

    def supports_function_calling(self):
        return False


crew_agent = CrewAgent(
    role="Assistant",
    goal="Answer questions",
    backstory=SYSTEM_PROMPT,
    llm=CrewMockLLM(),
)


def run_compare_crewai():
    task = Task(
        description=USER_MESSAGE, expected_output="One sentence.", agent=crew_agent
    )
    out = Crew(agents=[crew_agent], tasks=[task], verbose=False).kickoff()
    if str(out) != "ok":
        raise RuntimeError("crewai run returned unexpected content")
    return out


# ---------------------------------------------------------------------------
# Create Evaluations
# ---------------------------------------------------------------------------
BENCHMARKS = [
    PerformanceEval(
        name="run_compare_agno",
        func=run_compare_agno,
        num_iterations=iterations(300),
        telemetry=False,
    ),
    PerformanceEval(
        name="run_compare_langgraph",
        func=run_compare_langgraph,
        num_iterations=iterations(200),
        telemetry=False,
    ),
    PerformanceEval(
        name="run_compare_pydantic_ai",
        func=run_compare_pydantic_ai,
        num_iterations=iterations(100),
        telemetry=False,
    ),
    PerformanceEval(
        name="run_compare_crewai",
        func=run_compare_crewai,
        num_iterations=iterations(30),
        telemetry=False,
    ),
]

# ---------------------------------------------------------------------------
# Run Evaluations
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks(BENCHMARKS, group="comparison_run")
