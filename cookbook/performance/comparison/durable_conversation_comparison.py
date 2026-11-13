"""
Durable Conversation Comparison Benchmark
=========================================

One twenty-five-turn conversation persisted to a SQLite database every
turn: Agno with SqliteDb, LangGraph with SqliteSaver. Both frameworks pay
real serialization and real database writes per turn, so this is the
matched-durability counterpart of the in-memory conversation benchmarks.

PydanticAI is not included (it ships no persistence layer; history is
passed explicitly by the caller) and neither is CrewAI (no conversation
primitive; its memory feature requires an embedding provider). Each
included variant uses a fresh database file per conversation so
per-iteration work is constant, and asserts after the final turn that
history actually accumulated.

Both adapters run SQLite's WAL journal mode (SqliteSaver configures it
on its connection; SqliteDb enables it on every new connection), so the
row compares frameworks rather than journal configurations. Agno still
measures modestly slower here; the result is published as measured and
the per-turn serialization of growing session state is the known
optimization target.
"""

import itertools
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

from _compare import MockModel, ensure_completed, iterations, run_benchmarks
from agno.agent import Agent as AgnoAgent
from agno.db.sqlite import SqliteDb
from agno.eval.performance import PerformanceEval

TURNS = ["This is conversation turn number " + str(i) + "." for i in range(25)]
SYSTEM_PROMPT = "Be concise, reply with one sentence."
WORKDIR = Path(tempfile.mkdtemp(prefix="agno-durable-bench-"))


# ---------------------------------------------------------------------------
# Agno
# ---------------------------------------------------------------------------
agno_agent = AgnoAgent(
    model=MockModel(),
    add_history_to_context=True,
    num_history_runs=30,
    system_message=SYSTEM_PROMPT,
    telemetry=False,
)


def durable_conversation_compare_agno():
    db_file = WORKDIR / (str(uuid4()) + ".db")
    agno_agent.db = SqliteDb(db_file=str(db_file))
    last = None
    for turn in TURNS:
        last = ensure_completed(
            agno_agent.run(turn, session_id="conversation"), expected_content="ok"
        )
    if last is None or len(last.messages) < 2 * len(TURNS):
        raise RuntimeError(
            "history did not accumulate: " + str(last and len(last.messages))
        )
    db_file.unlink(missing_ok=True)
    return last


# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402


def _fresh_ok_messages():
    # The message reducer dedupes by message id, so every turn needs a NEW
    # AIMessage object; a cycled shared instance silently drops responses.
    while True:
        yield AIMessage(content="ok")


_thread_counter = itertools.count()


def durable_conversation_compare_langgraph():
    # The checkpointer binds at graph compile, so a fresh database file per
    # conversation includes one graph compile in the figure (about a
    # millisecond of the total)
    db_file = WORKDIR / (str(uuid4()) + ".db")
    connection = sqlite3.connect(str(db_file), check_same_thread=False)
    agent = create_react_agent(
        model=GenericFakeChatModel(messages=_fresh_ok_messages()),
        tools=[],
        checkpointer=SqliteSaver(connection),
    )
    config = {"configurable": {"thread_id": str(next(_thread_counter))}}
    out = None
    for turn in TURNS:
        out = agent.invoke({"messages": [("user", turn)]}, config)
    if out is None or len(out["messages"]) < 2 * len(TURNS):
        raise RuntimeError(
            "history did not accumulate: " + str(out and len(out["messages"]))
        )
    connection.close()
    db_file.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------------------
# Create Evaluations
# ---------------------------------------------------------------------------
BENCHMARKS = [
    PerformanceEval(
        name="durable_conversation_compare_agno",
        func=durable_conversation_compare_agno,
        num_iterations=iterations(15),
        telemetry=False,
    ),
    PerformanceEval(
        name="durable_conversation_compare_langgraph",
        func=durable_conversation_compare_langgraph,
        num_iterations=iterations(15),
        telemetry=False,
    ),
]

# ---------------------------------------------------------------------------
# Run Evaluations
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmarks(BENCHMARKS, group="comparison_durable_conversation")
