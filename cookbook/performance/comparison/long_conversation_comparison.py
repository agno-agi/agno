"""
Long Conversation Comparison Benchmark
======================================

One twenty-five-turn conversation per iteration, with history carried by
each framework's native mechanism (the same mechanisms and guards as the
five-turn benchmark). Per-turn costs that grow with history length dominate
here, so this benchmark exposes each framework's scaling behavior rather
than its fixed per-turn overhead.

This is a benchmark Agno does not currently win: its per-turn session
persistence re-serializes the whole conversation each turn, so its cost
grows quadratically with conversation length, while LangGraph's in-memory
checkpointer stores state by reference. The number is published as
measured; the growth term is a known optimization target.
"""

import itertools
from uuid import uuid4

from _compare import MockModel, ensure_completed, iterations, run_benchmarks
from agno.agent import Agent as AgnoAgent
from agno.db.in_memory import InMemoryDb
from agno.eval.performance import PerformanceEval

TURNS = ["This is conversation turn number " + str(i) + "." for i in range(25)]
SYSTEM_PROMPT = "Be concise, reply with one sentence."


# ---------------------------------------------------------------------------
# Agno
# ---------------------------------------------------------------------------
# cache_session matches the in-memory semantics of the other frameworks'
# history stores (LangGraph's saver holds state in process); the durable
# benchmark measures the uncached, persisted configuration instead.
agno_agent = AgnoAgent(
    model=MockModel(),
    cache_session=True,
    add_history_to_context=True,
    num_history_runs=30,
    system_message=SYSTEM_PROMPT,
    telemetry=False,
)


def long_conversation_compare_agno():
    agno_agent.db = InMemoryDb()
    conversation_id = str(uuid4())
    last = None
    for turn in TURNS:
        last = ensure_completed(
            agno_agent.run(turn, session_id=conversation_id), expected_content="ok"
        )
    if last is None or len(last.messages) < 2 * len(TURNS):
        raise RuntimeError(
            "history did not accumulate: " + str(last and len(last.messages))
        )
    return last


# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402


def _fresh_ok_messages():
    # The message reducer dedupes by message id, so every turn needs a NEW
    # AIMessage object; a cycled shared instance silently drops responses.
    while True:
        yield AIMessage(content="ok")


langgraph_agent = create_react_agent(
    model=GenericFakeChatModel(messages=_fresh_ok_messages()),
    tools=[],
    checkpointer=InMemorySaver(),
)
_thread_counter = itertools.count()


def long_conversation_compare_langgraph():
    config = {"configurable": {"thread_id": str(next(_thread_counter))}}
    out = None
    for turn in TURNS:
        out = langgraph_agent.invoke({"messages": [("user", turn)]}, config)
    if out is None or len(out["messages"]) < 2 * len(TURNS):
        raise RuntimeError(
            "history did not accumulate: " + str(out and len(out["messages"]))
        )
    return out


# ---------------------------------------------------------------------------
# PydanticAI
# ---------------------------------------------------------------------------
from pydantic_ai import Agent as PydanticAgent  # noqa: E402
from pydantic_ai.models.test import TestModel  # noqa: E402

pydantic_agent = PydanticAgent(
    TestModel(custom_output_text="ok"), system_prompt=SYSTEM_PROMPT
)


def long_conversation_compare_pydantic_ai():
    history = None
    result = None
    for turn in TURNS:
        result = pydantic_agent.run_sync(turn, message_history=history)
        history = result.all_messages()
    if result is None or len(history) < 2 * len(TURNS):
        raise RuntimeError(
            "history did not accumulate: " + str(history and len(history))
        )
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


def long_conversation_compare_crewai():
    tasks = []
    for turn in TURNS:
        tasks.append(
            Task(
                description=turn,
                expected_output="One sentence.",
                agent=crew_agent,
                context=list(tasks),
            )
        )
    out = Crew(agents=[crew_agent], tasks=tasks, verbose=False).kickoff()
    if len(out.tasks_output) != len(TURNS):
        raise RuntimeError("not all tasks executed: " + str(len(out.tasks_output)))
    return out


# ---------------------------------------------------------------------------
# Create Evaluations
# ---------------------------------------------------------------------------
BENCHMARKS = [
    PerformanceEval(
        name="long_conversation_compare_agno",
        func=long_conversation_compare_agno,
        num_iterations=iterations(20),
        telemetry=False,
    ),
    PerformanceEval(
        name="long_conversation_compare_langgraph",
        func=long_conversation_compare_langgraph,
        num_iterations=iterations(20),
        telemetry=False,
    ),
    PerformanceEval(
        name="long_conversation_compare_pydantic_ai",
        func=long_conversation_compare_pydantic_ai,
        num_iterations=iterations(10),
        telemetry=False,
    ),
    PerformanceEval(
        name="long_conversation_compare_crewai",
        func=long_conversation_compare_crewai,
        num_iterations=iterations(5),
        telemetry=False,
    ),
]

# ---------------------------------------------------------------------------
# Run Evaluations
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks(BENCHMARKS, group="comparison_long_conversation")
