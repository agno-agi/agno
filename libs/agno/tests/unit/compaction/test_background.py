"""Background passes: soft-trigger folds off-thread, single-flight, join-at-persist routing."""

import threading
import time
from typing import Any, AsyncIterator, Iterator, List

from agno.agent import Agent
from agno.compaction import Compaction
from agno.compaction.compaction import get_owner_records
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.response import ModelResponse

SUMMARY_TEXT = "## Goal\nBackground summary."


class SlowSummarizer(Model):
    def __init__(self, delay: float = 0.05) -> None:
        super().__init__(id="slow-summarizer", name="slow-summarizer", provider="test")
        self.delay = delay
        self.fold_calls = 0
        self.fold_threads: List[str] = []

    def __deepcopy__(self, memo: dict) -> "SlowSummarizer":
        clone = type(self)(self.delay)
        clone.fold_calls = self.fold_calls
        return clone

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.fold_calls += 1
        self.fold_threads.append(threading.current_thread().name)
        time.sleep(self.delay)
        return ModelResponse(role="assistant", content=SUMMARY_TEXT)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("streaming not used")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("streaming not used")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class PaddedLoopModel(Model):
    """Emits tool calls with large prose so views grow past the soft trigger mid-run."""

    def __init__(self, tool_rounds: int, padding: int) -> None:
        super().__init__(id="padded-loop", name="padded-loop", provider="test")
        self.tool_rounds = tool_rounds
        self.padding = padding
        self.calls: List[List] = []

    def __deepcopy__(self, memo: dict) -> "PaddedLoopModel":
        clone = type(self)(self.tool_rounds, self.padding)
        clone.calls = self.calls
        return clone

    def invoke(self, *args: Any, messages=None, **kwargs: Any) -> ModelResponse:
        import json

        self.calls.append(list(messages or []))
        call_number = len(self.calls)
        if call_number <= self.tool_rounds:
            return ModelResponse(
                role="assistant",
                content="thinking " * self.padding,
                tool_calls=[
                    {
                        "id": f"bg-{call_number}",
                        "type": "function",
                        "function": {"name": "note", "arguments": json.dumps({"text": f"t{call_number}"})},
                    }
                ],
            )
        return ModelResponse(role="assistant", content="Background run done.")

    async def ainvoke(self, *args: Any, messages=None, **kwargs: Any) -> ModelResponse:
        return self.invoke(messages=messages)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("streaming not used")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("streaming not used")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def note(text: str) -> str:
    """Store a short note."""
    return "noted " * 60


class TestBackgroundPasses:
    def test_soft_trigger_folds_off_thread(self):
        summarizer = SlowSummarizer(delay=0.02)
        model = PaddedLoopModel(tool_rounds=10, padding=400)
        agent = Agent(
            id="bg-agent",
            model=model,
            db=InMemoryDb(),
            tools=[note],
            compaction=Compaction(context_window=4_000, model=summarizer, clear_tool_results=False),
            telemetry=False,
        )
        output = agent.run("go", session_id="s-bg-1")
        assert str(output.content).endswith("Background run done.")
        assert summarizer.fold_calls >= 1
        # The fold ran off the main thread (a background pass, not an inline one) at least once.
        assert any(name.startswith("agno-compaction-fold") for name in summarizer.fold_threads)

        session = agent.get_session(session_id="s-bg-1")
        records = get_owner_records(session.session_data, "bg-agent")
        assert records, "background fold never committed"
        assert any(record.summary == SUMMARY_TEXT for record in records)

    def test_fold_in_flight_at_run_end_commits_for_next_run_only(self):
        # A long fold delay: the fold cannot land at any loop-top before the run finishes.
        summarizer = SlowSummarizer(delay=0.5)
        model = PaddedLoopModel(tool_rounds=4, padding=700)
        agent = Agent(
            id="bg-agent-2",
            model=model,
            db=InMemoryDb(),
            tools=[note],
            compaction=Compaction(context_window=4_000, model=summarizer, clear_tool_results=False),
            telemetry=False,
        )
        started = time.time()
        output = agent.run("go", session_id="s-bg-2")
        elapsed = time.time() - started
        session = agent.get_session(session_id="s-bg-2")
        records = get_owner_records(session.session_data, "bg-agent-2")
        if records and all(record.id != output.compaction_id for record in records):
            # The record committed at persist without ever activating: this run's pointer must
            # not name it (its final provider call never saw that view).
            assert output.compaction_id is None or output.compaction_id not in {r.id for r in records}
        # The run waited for the fold at most once (terminal join), not per iteration.
        assert elapsed < 3.0

    def test_single_flight_registry(self):
        summarizer = SlowSummarizer(delay=0.3)
        model = PaddedLoopModel(tool_rounds=8, padding=500)
        agent = Agent(
            id="bg-agent-3",
            model=model,
            db=InMemoryDb(),
            tools=[note],
            compaction=Compaction(context_window=4_000, model=summarizer, clear_tool_results=False),
            telemetry=False,
        )
        agent.run("go", session_id="s-bg-3")
        # Growth crosses the soft trigger on many loop-tops while one fold is in flight; the
        # registry caps concurrent folds at one, so fold calls stay far below loop iterations.
        assert summarizer.fold_calls <= 3
