import logging
import tempfile
from pathlib import Path

import pytest

from agno.compaction import Compaction, CompactionRecord, CompactionStatus
from agno.compaction.archive import render_messages
from agno.models.message import Message


def _transcript(runs: int = 3) -> list:
    """A transcript of ``runs`` user/assistant exchanges, one with a tool batch."""
    messages = []
    for i in range(runs):
        messages.append(Message(role="user", content=f"question {i}"))
        if i == 1:
            messages.append(
                Message(
                    role="assistant",
                    content=None,
                    tool_calls=[{"id": f"call_{i}", "function": {"name": "search", "arguments": "{}"}}],
                )
            )
            messages.append(Message(role="tool", tool_call_id=f"call_{i}", tool_name="search", content="data"))
        messages.append(Message(role="assistant", content=f"answer {i}"))
    return messages


class _StubModel:
    """A summarizer that records what it was asked to summarize."""

    id = "stub"
    seen = ""

    def response(self, messages, **kwargs):
        from agno.models.response import ModelResponse

        self.seen = messages[-1].content
        return ModelResponse(content="SUMMARY")


def _record(messages, boundary_index, summary="s", **kwargs):
    """A record anchored on messages[boundary_index] - the first message kept verbatim."""
    return CompactionRecord(
        messages_compacted=boundary_index,
        summary=summary,
        first_kept_message_id=messages[boundary_index].id if boundary_index < len(messages) else None,
        **kwargs,
    )


def _db():
    return __import__("agno.db.sqlite", fromlist=["SqliteDb"]).SqliteDb(
        db_file=str(Path(tempfile.mkdtemp()) / "test.db")
    )


# --- configuration -------------------------------------------------------


def test_no_token_threshold_is_legal():
    """compact_at_tokens=None disables the automatic trigger.

    Manual-only is a coherent way to run compaction - agent.compact() at a moment of the
    caller's choosing - so this must not raise.
    """
    c = Compaction(compact_at_tokens=None)
    assert c.compact_at_tokens is None
    assert c.should_compact(_transcript(runs=50)) is False


def test_rejects_non_positive_threshold():
    with pytest.raises(ValueError, match="compact_at_tokens"):
        Compaction(compact_at_tokens=0)


# --- triggers ------------------------------------------------------------


def test_size_is_the_only_automatic_trigger():
    """A run or message count says nothing about how much context is in play.

    Twenty short exchanges and twenty research turns differ by orders of magnitude, so counting
    them fires on conversations far too small to fold and stays quiet on ones that overflow.
    """
    c = Compaction(compact_at_tokens=1_000)
    assert c.should_compact(_transcript(runs=50), context_tokens=200) is False
    assert c.should_compact(_transcript(runs=2), context_tokens=5_000) is True


def test_compaction_threshold_uses_context_size_not_previous_run_billing_total():
    """RunMetrics.input_tokens accumulates tool-loop calls; it is not a context size.

    Four calls of a 20k context bill 80k, so a threshold read off billing telemetry fires on a
    request that never came close to it. The trigger takes the size of the view being sent, and
    has no way to be handed a billing total by mistake - the parameter simply does not exist.
    """
    import inspect

    assert "last_input_tokens" not in inspect.signature(Compaction.should_compact).parameters

    c = Compaction(compact_at_tokens=25_000)
    # The billing total for a four-call tool loop, none of which exceeded 21,200.
    assert c.should_compact([], context_tokens=21_200, model=None) is False
    assert c.should_compact([], context_tokens=26_000, model=None) is True


def test_tool_loop_context_is_measured_once_not_summed_per_call():
    """The estimator sizes the request, where billing telemetry sums every call in the loop.

    A tool loop re-sends the whole conversation each iteration, so the provider bills it once
    per call. Summing that is the right number for cost and the wrong one for "will this fit" -
    it grows with tool use while the context barely moves. This walks the real estimator over a
    real four-call transcript rather than asserting on a hand-supplied number, so the wiring
    that produces the figure is what is under test.
    """
    from agno.agent import Agent
    from agno.agent._messages import _estimated_context_tokens

    messages = [
        Message(role="system", content="sys " * 100),
        Message(role="user", content="q " * 200),
    ]
    for i in range(4):
        messages.append(
            Message(
                role="assistant",
                content="",
                tool_calls=[{"id": f"c{i}", "function": {"name": "search", "arguments": "{}"}}],
            )
        )
        messages.append(Message(role="tool", tool_call_id=f"c{i}", tool_name="search", content="result " * 300))

    agent = Agent()
    context = _estimated_context_tokens(agent, messages)

    # What billing telemetry would have reported: every intermediate request, summed.
    billed = sum(_estimated_context_tokens(agent, messages[: 2 + 2 * (i + 1)]) for i in range(4))

    assert context is not None
    assert billed > context * 2, (billed, context)

    # The gap is the bug: a threshold between the two fires on a request that never reached it.
    threshold = (context + billed) // 2
    compaction = Compaction(compact_at_tokens=threshold)
    assert compaction.should_compact(messages, context_tokens=context, model=None) is False


def test_context_estimate_counts_more_than_history():
    """System text and tool schemas ride in every request, so they count toward the threshold.

    A request can be oversized because of instructions or tool definitions rather than history.
    Measuring history alone would leave the trigger blind to that.
    """
    from agno.agent import Agent
    from agno.agent._messages import _estimated_context_tokens

    history = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    with_system = [Message(role="system", content="instructions " * 500)] + history

    agent = Agent()

    assert _estimated_context_tokens(agent, with_system) > _estimated_context_tokens(agent, history)


def test_context_size_is_estimated_locally_when_not_supplied():
    """The fallback is local token counting, not provider count_tokens."""

    class ExplodingModel:
        id = "x"

        def count_tokens(self, *args, **kwargs):
            raise AssertionError("provider count_tokens must not be called")

    c = Compaction(compact_at_tokens=1)
    assert c.should_compact(_transcript(), model=ExplodingModel()) is True


def test_a_threshold_without_replayed_history_is_warned_about(caplog):
    """Compaction folds replayed history; with none, compact_at_tokens never fires."""
    from agno.agent import Agent, _init

    def warnings_for(**kwargs):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="agno"):
            _init.set_compaction(Agent(**kwargs))
        return [r.message for r in caplog.records if "add_history_to_context" in r.message]

    assert warnings_for(add_history_to_context=False, compaction=Compaction())
    # Overflow recovery still acts within a run, so threshold-free compaction is not a mistake.
    assert not warnings_for(add_history_to_context=False, compaction=True)
    assert not warnings_for(add_history_to_context=True, compaction=Compaction())


def test_compaction_alongside_session_summaries_is_warned_about(caplog):
    """Both put a summary of the same history into the context."""
    from agno.agent import Agent, _init

    def warnings_for(**kwargs):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="agno"):
            _init.set_compaction(Agent(add_history_to_context=True, compaction=Compaction(), **kwargs))
        return [r.message for r in caplog.records if "session summaries" in r.message]

    assert warnings_for(add_session_summary_to_context=True)
    assert not warnings_for()


def test_a_small_replay_window_is_not_a_misconfiguration(caplog):
    """num_history_runs bounds only what a run sends; compaction reads its own window. A window at
    or below the kept tail overrides nothing, so there is nothing to warn about."""
    from agno.agent import Agent, _init

    for window, keep in ((2, 5), (5, 5), (20, 5)):
        caplog.clear()
        agent = Agent(num_history_runs=window, compaction=Compaction(uncompacted_runs=keep))
        with caplog.at_level(logging.WARNING, logger="agno"):
            _init.set_compaction(agent)
        assert not [r for r in caplog.records if "num_history_runs" in r.message], (window, keep)
        assert agent.num_history_runs == window


def test_an_agentos_copy_plans_over_the_same_window(caplog):
    """AgentOS deep-copies the agent per request, passing num_history_runs=3 back as if the user had
    set it. Nothing depends on telling the default from a choice, so the copy behaves the same."""
    from agno.agent import Agent, _init
    from agno.agent._messages import _compaction_history_runs

    original = Agent(compaction=Compaction())
    copy = original.deep_copy()

    with caplog.at_level(logging.WARNING, logger="agno"):
        _init.set_compaction(copy)

    assert _compaction_history_runs(copy) == _compaction_history_runs(original) == 500
    assert not [r for r in caplog.records if "num_history_runs" in r.message]


def test_compaction_is_not_starved_by_the_default_history_window():
    """num_history_runs defaults to 3, which would leave compaction nothing to fold.

    Compaction folds what sits in FRONT of the kept tail. A 3-run window with uncompacted_runs=5
    has no front, so compaction could never fire under the one-flag setup - and an anchor
    outside the window cannot resolve, dropping the summary along with the turns it replaced.
    """
    from agno.agent import Agent
    from agno.agent._messages import _compaction_history_runs

    agent = Agent(compaction=Compaction(uncompacted_runs=5))

    assert agent.num_history_runs == 3  # the replay default is unchanged
    assert _compaction_history_runs(agent) > 5  # but the planner sees past it


def test_compaction_reads_past_any_replay_window():
    """The planner's read is never narrower than what a run sends - those messages are selected from
    it - and otherwise reads wide, whether the window is the default or the user's choice."""
    from agno.agent import Agent
    from agno.agent._messages import _compaction_history_runs

    for window in (2, 3, 50):
        assert _compaction_history_runs(Agent(num_history_runs=window, compaction=Compaction())) == 500
    assert _compaction_history_runs(Agent(num_history_runs=1_000, compaction=Compaction())) == 1_000
    assert _compaction_history_runs(Agent(num_history_runs=2)) == 2  # no compaction, no widening


class _RecordingModel:
    """Builds an offline model that records every request it is sent."""

    @staticmethod
    def build():
        from agno.metrics import MessageMetrics
        from agno.models.base import Model
        from agno.models.response import ModelResponse

        class Recording(Model):
            def __init__(self):
                super().__init__(id="test-model", name="test-model", provider="test")
                self.requests: list = []

            def _reply(self):
                return ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

            def get_instructions_for_model(self, *args, **kwargs):
                return None

            def get_system_message_for_model(self, *args, **kwargs):
                return None

            async def aget_instructions_for_model(self, *args, **kwargs):
                return None

            async def aget_system_message_for_model(self, *args, **kwargs):
                return None

            def parse_args(self, *args, **kwargs):
                return {}

            def invoke(self, *args, **kwargs):
                self.requests.append(list(kwargs.get("messages") or []))
                return self._reply()

            async def ainvoke(self, *args, **kwargs):
                return self.invoke(*args, **kwargs)

            def invoke_stream(self, *args, **kwargs):
                self.requests.append(list(kwargs.get("messages") or []))
                yield self._reply()

            async def ainvoke_stream(self, *args, **kwargs):
                self.requests.append(list(kwargs.get("messages") or []))
                yield self._reply()

            def _parse_provider_response(self, response, **kwargs):
                return self._reply()

            def _parse_provider_response_delta(self, response):
                return self._reply()

        return Recording()


def _requests_over(runs, **agent_kwargs):
    from agno.agent import Agent

    model = _RecordingModel.build()
    agent = Agent(model=model, db=_db(), session_id="s", add_history_to_context=True, **agent_kwargs)
    for i in range(runs):
        agent.run(f"question number {i}")
    return model.requests


@pytest.mark.parametrize(
    "agent_kwargs",
    [
        {"compaction": True},
        {"compaction": Compaction()},
        {"compaction": True, "num_history_runs": 3},
    ],
)
def test_compaction_does_not_widen_what_a_run_replays(agent_kwargs):
    """The planner reads past num_history_runs; the model must not.

    Replaying the planner's window would send the whole session every run until something folds -
    and with compaction=True nothing folds until the provider rejects a request.
    """
    baseline = [len(r) for r in _requests_over(10)]
    with_compaction = [len(r) for r in _requests_over(10, **agent_kwargs)]

    assert with_compaction == baseline
    assert with_compaction[-1] == with_compaction[-4]  # bounded, not growing


def test_async_runs_do_not_widen_what_a_run_replays():
    import asyncio

    from agno.agent import Agent

    async def requests_over(runs, **agent_kwargs):
        model = _RecordingModel.build()
        agent = Agent(model=model, db=_db(), session_id="s", add_history_to_context=True, **agent_kwargs)
        for i in range(runs):
            await agent.arun(f"question number {i}")
        return [len(r) for r in model.requests]

    assert asyncio.run(requests_over(10, compaction=True)) == asyncio.run(requests_over(10))


def test_a_fold_replays_its_summary_and_everything_from_the_anchor():
    """Once a fold exists the anchor has to be replayed, even when it is older than the window -
    dropping it would drop the summary along with the turns it replaced."""
    from agno.agent import Agent

    model = _RecordingModel.build()
    agent = Agent(
        model=model,
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        num_history_runs=2,
        compaction=Compaction(
            compact_at_tokens=None,
            uncompacted_runs=3,
            min_fold_ratio=0,
            search_compacted_messages=False,
            model=_StubModel(),
        ),
    )
    for i in range(6):
        agent.run(f"question number {i}")
    assert agent.compact(session_id="s").compacted  # keeps runs 3-5, a tail wider than the 2-run window

    agent.run("question number 6")
    last = [m.content for m in model.requests[-1] if m.role != "system"]

    assert last[0].startswith("Summary of earlier conversation")
    assert [c for c in last if c.startswith("question")] == [f"question number {i}" for i in range(3, 7)]


@pytest.mark.parametrize(
    "window, tail",
    [
        ({"num_history_runs": 4}, {"uncompacted_runs": 1}),
        ({"num_history_runs": 4}, {"uncompacted_tokens": 8}),
        ({"num_history_messages": 8}, {"uncompacted_runs": 1}),
    ],
)
def test_the_summary_survives_its_anchor_leaving_the_window(window, tail):
    """A fixed replay window - counted in runs or in messages - slides past a fold's anchor within a
    few runs. The anchor must still be read and replayed, or the summary is dropped along with the
    turns it replaced - with compaction=True, where folds are rare, that would be the normal case."""
    from agno.agent import Agent

    model = _RecordingModel.build()
    agent = Agent(
        model=model,
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(
            compact_at_tokens=None, min_fold_ratio=0, search_compacted_messages=False, model=_StubModel(), **tail
        ),
        **window,
    )
    for i in range(4):
        agent.run(f"question number {i}")
    assert agent.compact(session_id="s").compacted

    for i in range(4, 11):
        agent.run(f"question number {i}")
    sent = [m.content for m in model.requests[-1] if m.role != "system"]
    asked = [int(c.split()[-1]) for c in sent if c.startswith("question")]

    assert sent[0].startswith("Summary of earlier conversation")
    # Everything from the anchor onward, which reaches back past the 4-run window.
    assert asked == list(range(asked[0], 11)) and asked[0] <= 4


def test_num_history_messages_still_bounds_what_is_sent_before_a_fold():
    """Compaction reads past the message limit; the model does not, until a fold exists."""
    baseline = [len(r) for r in _requests_over(8, num_history_messages=4)]
    with_compaction = [len(r) for r in _requests_over(8, num_history_messages=4, compaction=True)]

    assert with_compaction == baseline


def test_async_dbs_declare_no_compaction_contract():
    """Only the sync BaseDb declares the record methods. Async stubs would return unawaited
    coroutines to a sync archive instead of saying they are unsupported."""
    from agno.db.base import AsyncBaseDb, BaseDb

    for name in ("upsert_compaction", "get_compactions_for_session", "search_compactions"):
        assert hasattr(BaseDb, name)
        assert not hasattr(AsyncBaseDb, name)


@pytest.mark.parametrize("compaction", [True, "object"])
def test_the_unsupported_db_warning_comes_when_the_agent_is_built(compaction, caplog):
    """The warning comes at construction, not at the first run - so it shows even when the first
    call fails for another reason, such as a sync method on an async db."""
    from agno.agent import Agent
    from agno.db.in_memory import InMemoryDb

    with caplog.at_level(logging.WARNING, logger="agno"):
        agent = Agent(db=InMemoryDb(), compaction=Compaction() if compaction == "object" else True)

    assert agent.compaction is None
    assert any("only supported with SqliteDb and PostgresDb" in r.message for r in caplog.records)
    # A db that stores records keeps compaction on, silently.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="agno"):
        assert Agent(db=_db(), compaction=True).compaction is True
    assert not caplog.records


@pytest.mark.parametrize("db_kind", ["async sqlite", "in memory"])
def test_compaction_is_turned_off_on_a_db_that_cannot_store_records(db_kind, caplog):
    """Only SqliteDb and PostgresDb store compaction records. Without one a fold lasts a single run:
    the next starts from the full history and pays for another summary of all of it. So on any
    other db compaction is turned off at setup, with a warning naming the dbs that work."""
    import asyncio

    from agno.agent import Agent
    from agno.db.in_memory import InMemoryDb
    from agno.db.sqlite import AsyncSqliteDb

    class _CountingStub(_StubModel):
        calls = 0

        def response(self, messages, **kwargs):
            _CountingStub.calls += 1
            return super().response(messages, **kwargs)

        async def aresponse(self, messages, **kwargs):
            return self.response(messages)

    db = AsyncSqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "a.db")) if db_kind == "async sqlite" else InMemoryDb()
    agent = Agent(
        model=_RecordingModel.build(),
        db=db,
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=5, uncompacted_runs=1, model=_CountingStub()),
    )

    async def runs():
        return [await agent.arun(f"question number {i}") for i in range(3)]

    with caplog.at_level(logging.WARNING, logger="agno"):
        results = asyncio.run(runs())

    assert all(r.status.value == "COMPLETED" for r in results)
    assert all(r.compaction is None for r in results)
    assert _CountingStub.calls == 0
    assert agent.compaction is None
    warnings = [r.message for r in caplog.records if "only supported with SqliteDb and PostgresDb" in r.message]
    assert len(warnings) == 1 and type(db).__name__ in warnings[0]


def test_history_window_untouched_without_compaction():
    """The widening is compaction's business only."""
    from agno.agent import Agent
    from agno.agent._messages import _compaction_history_runs

    assert _compaction_history_runs(Agent()) == 3


def test_manual_compact_folds_without_the_size_trigger():
    """agent.compact() folds now, whatever the context size.

    The explicit counterpart to the automatic path: a caller asking to compact has supplied the
    judgement compact_at_tokens exists to make, so only that threshold is bypassed.
    """
    from agno.agent import Agent
    from agno.agent._messages import _history_for_compaction, compact_now
    from agno.run.agent import RunOutput
    from agno.session.agent import AgentSession

    runs = []
    for i in range(12):
        run = RunOutput(run_id=f"r{i}", session_id="s1", content=f"a{i}")
        run.messages = [
            Message(role="user", content=f"question {i} " * 40, id=f"u{i}"),
            Message(role="assistant", content=f"answer {i} " * 400, id=f"a{i}"),
        ]
        runs.append(run)
    session = AgentSession(session_id="s1", runs=runs)

    # compact_at_tokens far above this conversation: the automatic path would never fire.
    compaction = Compaction(
        compact_at_tokens=10_000_000, uncompacted_runs=3, store_compacted_messages=False, model=_StubModel()
    )
    agent = Agent(compaction=compaction)

    result = compact_now(agent, session, _history_for_compaction(agent, session))

    assert result.compacted
    assert result.record is not None
    assert result.record.tokens_after < result.record.tokens_before
    # The anchor is the first message of the kept tail - 3 runs back.
    assert result.record.first_kept_message_id == "u9"


def test_manual_compact_still_honours_the_ratio_guard():
    """Only the size trigger is bypassed.

    The ratio answers a different question - whether a summary can pay for itself at all - so
    an explicit call must not override it: doing so would make the context bigger. The decline
    is reported as a status a caller can show, not raised and not silent.
    """
    from agno.agent import Agent
    from agno.agent._messages import compact_now
    from agno.session.agent import AgentSession

    # Enough turns that a boundary exists - otherwise this declines as NOTHING_TO_FOLD and
    # never reaches the ratio check it is meant to exercise. Short turns, so the fold is small.
    history = [
        m
        for i in range(4)
        for m in (
            Message(role="user", content=f"q{i}", id=f"u{i}"),
            Message(role="assistant", content=f"a{i}", id=f"a{i}"),
        )
    ]
    compaction = Compaction(
        enforce_min_fold_ratio=True, uncompacted_runs=2, store_compacted_messages=False, model=_StubModel()
    )
    agent = Agent(compaction=compaction)

    result = compact_now(agent, AgentSession(session_id="s1", runs=[]), history)

    assert not result.compacted
    assert result.record is None
    assert result.status is CompactionStatus.NOT_WORTH_IT
    assert "would not shrink" in result.message or "reclaims" in result.message


def test_the_fold_ratio_guard_is_opt_in():
    """The guard is Agno's own idea, so it is off unless asked for: by default every fold the
    threshold or a manual compact asks for happens, even one the ratio would decline."""
    from agno.agent import Agent

    def compact_with(**kwargs):
        agent = Agent(
            model=_RecordingModel.build(),
            db=_db(),
            session_id="s",
            add_history_to_context=True,
            compaction=Compaction(uncompacted_runs=2, store_compacted_messages=False, model=_StubModel(), **kwargs),
        )
        for i in range(3):
            agent.run(f"question number {i}")
        return agent.compact(session_id="s")

    assert Compaction().enforce_min_fold_ratio is False
    assert compact_with().status is CompactionStatus.COMPACTED
    assert compact_with(enforce_min_fold_ratio=True).status is CompactionStatus.NOT_WORTH_IT


def test_not_worth_it_message_carries_the_numbers():
    """The verdict alone is not actionable.

    "not worth it" with no figures leaves a caller unable to tell a fold that missed by a
    hair from one that was never close - and the ratio is what says which lever to reach for.
    """
    from agno.agent import Agent
    from agno.agent._messages import compact_now
    from agno.session.agent import AgentSession

    # 4 turns with uncompacted_runs=2 puts the fold and the tail at the same size: ratio 1.00.
    history = [
        m
        for i in range(4)
        for m in (
            Message(role="user", content="q " * 15, id=f"u{i}"),
            Message(role="assistant", content="a " * 600, id=f"a{i}"),
        )
    ]
    agent = Agent(
        compaction=Compaction(
            enforce_min_fold_ratio=True, uncompacted_runs=2, store_compacted_messages=False, model=_StubModel()
        )
    )

    result = compact_now(agent, AgentSession(session_id="s1", runs=[]), history)

    assert result.status is CompactionStatus.NOT_WORTH_IT
    assert "ratio 1.00" in result.message
    assert "needs 2.0" in result.message
    # The usual fix is more conversation, so it is named before the config knobs.
    assert result.message.index("Continue") < result.message.index("uncompacted_runs")


def test_compaction_result_serializes_for_an_api():
    """The route returns result.to_dict() verbatim, so this IS the API contract."""
    from agno.compaction.types import CompactionResult, CompactionStatus

    declined = CompactionResult(status=CompactionStatus.NOT_WORTH_IT, message="too small").to_dict()

    assert declined == {
        "status": "not_worth_it",
        "message": "too small",
        "compacted": False,
        "record": None,
        "metrics": None,
    }


def test_declines_are_reported_not_raised():
    """A decline is a normal outcome an API returns 200 for, with a reason to display.

    Raising would make a legitimate "folding would not help here" indistinguishable from a
    failure, and force every caller to catch it.
    """
    from agno.agent import Agent
    from agno.agent._messages import compact_now
    from agno.session.agent import AgentSession

    agent = Agent(
        compaction=Compaction(
            enforce_min_fold_ratio=True, uncompacted_runs=2, store_compacted_messages=False, model=_StubModel()
        )
    )
    session = AgentSession(session_id="s1", runs=[])

    for history, expected in (
        ([], CompactionStatus.NO_HISTORY),
        (
            [
                m
                for i in range(4)
                for m in (
                    Message(role="user", content=f"q{i}", id=f"u{i}"),
                    Message(role="assistant", content=f"a{i}", id=f"a{i}"),
                )
            ],
            CompactionStatus.NOT_WORTH_IT,
        ),
    ):
        result = compact_now(agent, session, history)
        assert result.status is expected
        assert result.message  # always something a UI can show
        assert not result.compacted


def test_compaction_not_enabled_is_a_status_not_a_crash():
    from agno.agent import Agent
    from agno.agent._messages import compact_now
    from agno.session.agent import AgentSession

    result = compact_now(Agent(), AgentSession(session_id="s1", runs=[]), [Message(role="user", content="x")])

    assert result.status is CompactionStatus.NOT_ENABLED
    assert not result.compacted


def test_uncompacted_tokens_bounds_a_tail_that_runs_cannot():
    """A run count says how many turns survive, not how large they are.

    Compaction only folds what sits in FRONT of the tail, so a handful of verbose turns
    produces a tail it can never bring back down. A token budget bounds the tail itself.
    """
    from agno.compaction._tokens import estimate_tokens

    messages = []
    for i in range(8):
        messages.append(Message(role="user", content=f"q{i} " * 20, id=f"u{i}"))
        messages.append(Message(role="assistant", content=("f " * 15000 if i >= 5 else f"a{i} " * 200), id=f"a{i}"))
    total = estimate_tokens(messages)

    by_runs = Compaction(uncompacted_runs=3).boundary_for(messages)
    by_tokens = Compaction(uncompacted_tokens=5_000).boundary_for(messages)

    assert estimate_tokens(messages[by_runs:]) > total * 0.9  # runs cannot help here
    assert estimate_tokens(messages[by_tokens:]) < total * 0.5


def test_the_kept_tail_tracks_the_token_budget():
    """A larger budget keeps more, a smaller one keeps less."""
    from agno.compaction._tokens import estimate_tokens

    messages = [
        m
        for i in range(10)
        for m in (
            Message(role="user", content=f"q{i} " * 20, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 500, id=f"a{i}"),
        )
    ]

    tails = []
    for budget in (2_000, 5_000, 10_000):
        boundary = Compaction(uncompacted_tokens=budget).boundary_for(messages)
        tails.append(estimate_tokens(messages[boundary:]))

    assert tails == sorted(tails)


def _runs_of(n, answer_words=450):
    """n runs of roughly 500 tokens each."""
    return [
        m
        for i in range(n)
        for m in (
            Message(role="user", content=f"question {i} " + "word " * 40, id=f"u{i}"),
            Message(role="assistant", content="detail " * answer_words, id=f"a{i}"),
        )
    ]


def test_the_tail_limit_follows_the_threshold_and_ratio():
    """compact_at_tokens / (1 + min_fold_ratio) is the largest tail a fold can pass the ratio against
    at the moment the threshold fires. Without a threshold there is nothing to derive it from."""
    # Without an enforced ratio, the only limit is the threshold itself.
    assert Compaction(compact_at_tokens=3_000)._tail_limit == 3_000
    assert Compaction(enforce_min_fold_ratio=True, compact_at_tokens=3_000)._tail_limit == 1_000
    assert Compaction(enforce_min_fold_ratio=True, compact_at_tokens=3_000, min_fold_ratio=0.5)._tail_limit == 2_000
    assert Compaction(compact_at_tokens=None)._tail_limit is None
    assert Compaction(on_context_overflow=True)._tail_limit is None


def test_a_token_tail_as_large_as_the_threshold_is_rejected():
    with pytest.raises(ValueError, match="must be smaller than compact_at_tokens"):
        Compaction(compact_at_tokens=2_000, uncompacted_tokens=2_000)
    Compaction(compact_at_tokens=None, uncompacted_tokens=50_000)  # no threshold, nothing to compare


def test_a_token_tail_that_delays_the_first_fold_is_warned_about(caplog):
    """Above the limit the threshold fires and the ratio declines, run after run, until the context
    reaches the tail times (1 + min_fold_ratio). An explicit size is the user's call, so it is kept."""
    with caplog.at_level(logging.WARNING, logger="agno"):
        compaction = Compaction(enforce_min_fold_ratio=True, compact_at_tokens=2_000, uncompacted_tokens=1_500)
    text = " ".join(r.message for r in caplog.records)
    assert "at most 666" in text and "4500" in text
    assert compaction.uncompacted_tokens == 1_500

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="agno"):
        Compaction(enforce_min_fold_ratio=True, compact_at_tokens=2_000, uncompacted_tokens=400)
    assert not caplog.records


def test_a_run_count_tail_past_the_limit_folds_when_the_threshold_fires():
    """Five runs of ~500 tokens are a 2,500-token tail against a 2,000-token threshold: the ratio
    would decline every run until run 15. Cut by tokens at the limit, the fold happens at once."""
    from agno.compaction._tokens import estimate_tokens

    messages = _runs_of(5)
    compaction = Compaction(compact_at_tokens=2_000)

    boundary, status, _ = compaction.plan_with_reason(messages)

    assert status == CompactionStatus.COMPACTED
    assert estimate_tokens(messages[boundary:]) <= compaction._tail_limit
    assert messages[boundary].role == "user"


def test_the_tail_limit_never_cuts_into_the_newest_exchange():
    """An oversized newest answer keeps its question: the model must not reply to a summary of what
    it was just asked. The ratio may then decline; overflow recovery covers a request that is too long."""
    messages = (
        _runs_of(4)
        + _runs_of(1, answer_words=3_000)[:1]
        + [Message(role="assistant", content="detail " * 3_000, id="big")]
    )
    messages[-2].id = "newest"

    boundary = Compaction(compact_at_tokens=2_000).boundary_for(messages)

    assert messages[boundary].id == "newest"


def test_cutting_a_chosen_run_count_is_logged_at_info(caplog):
    """An explicit uncompacted_runs is being overridden, so say it where it will be seen; the default
    is nobody's choice, so it stays at debug."""
    messages = _runs_of(5)

    with caplog.at_level(logging.DEBUG, logger="agno"):
        Compaction(
            enforce_min_fold_ratio=True,
            compact_at_tokens=2_000,
            uncompacted_runs=4,
            model=_StubModel(),
            store_compacted_messages=False,
        ).compact(messages, session_id="s")
    chosen = [r for r in caplog.records if "tail limit" in r.message]
    assert chosen and chosen[0].levelno == logging.INFO

    # log_debug only emits in debug mode, so the default leaves nothing at info level or above.
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="agno"):
        Compaction(
            enforce_min_fold_ratio=True, compact_at_tokens=2_000, model=_StubModel(), store_compacted_messages=False
        ).compact(messages, session_id="s")
    assert not [r for r in caplog.records if "tail limit" in r.message and r.levelno >= logging.INFO]


def test_a_fold_that_leaves_the_context_over_the_threshold_warns(caplog):
    """When the system prompt and tools alone sit near the threshold, every fold is followed by another
    on the next run - a summarizer call each time. The fold measures its result, so it can say so."""
    messages = _runs_of(5)
    huge_system_prompt = [Message(role="system", content="rule " * 3_000)]

    with caplog.at_level(logging.WARNING, logger="agno"):
        record = Compaction(compact_at_tokens=2_000, model=_StubModel(), store_compacted_messages=False).compact(
            messages, session_id="s", context_prefix=huge_system_prompt
        )

    assert record is not None
    assert any("will fold again" in r.message for r in caplog.records)


def test_instructions_add_to_the_default_prompt():
    """instructions is guidance on top of the default prompt, as everywhere else in Agno. Replacing
    the prompt with it dropped the structure that carries earlier summaries and identifiers
    forward, so a one-line "keep ticket ids" cost far more than it asked for."""
    from agno.compaction.prompts import DEFAULT_COMPACTION_PROMPT, LENGTH_RULE_COMPACT

    system = Compaction(instructions="Keep every ticket id.")._summary_messages(_transcript(), previous=None)[0].content

    assert system.startswith(DEFAULT_COMPACTION_PROMPT.format(length_rule=LENGTH_RULE_COMPACT))
    assert system.endswith("Additional instructions:\nKeep every ticket id.")


@pytest.mark.parametrize("num_history_runs", [1, 3])
def test_a_fork_and_its_source_are_replayed_as_without_compaction(num_history_runs):
    """A continue_run fork copies its source run's messages with the same ids. With only the fork
    in the window, filtering by id let the source's copies in too and sent those turns twice; with
    both in the window, both are history and both are sent. Either way, as without compaction."""

    def sent_after_a_fork(compaction):
        from agno.agent import Agent

        model = _RecordingModel.build()
        agent = Agent(
            model=model,
            db=_db(),
            session_id="s",
            add_history_to_context=True,
            num_history_runs=num_history_runs,
            compaction=compaction,
        )
        agent.run("q0")
        source = agent.run("q1 source")
        agent.continue_run(run_id=source.run_id, session_id="s", fork=True, input="q1 follow-up")
        agent.run("q2")
        return [str(m.content) for m in model.requests[-1] if m.role != "system"]

    plain = sent_after_a_fork(None)
    with_compaction = sent_after_a_fork(Compaction(compact_at_tokens=None, model=_StubModel()))

    assert with_compaction == plain
    assert plain.count("q1 source") == (1 if num_history_runs == 1 else 2)


# --- continue_run ----------------------------------------------------------------


@pytest.mark.parametrize("use_async", [False, True])
def test_continuing_a_paused_run_from_the_db_replays_the_fold(use_async):
    """A run resumed by run_id rebuilds its history from the session, since stored runs drop their
    history copies. That rebuild must replay the fold, not the plain window of folded turns."""
    import asyncio

    from agno.agent import Agent
    from agno.metrics import MessageMetrics
    from agno.models.response import ModelResponse
    from agno.tools import tool

    @tool(requires_confirmation=True)
    def deploy() -> str:
        """Deploy."""
        return "deployed"

    model = _RecordingModel.build()
    reply = model._reply
    pause = {"next": False}

    def reply_or_pause():
        if not pause["next"]:
            return reply()
        pause["next"] = False
        call = {"id": "call_1", "type": "function", "function": {"name": "deploy", "arguments": "{}"}}
        return ModelResponse(role="assistant", content=None, tool_calls=[call], response_usage=MessageMetrics())

    model._reply = reply_or_pause
    agent = Agent(
        model=model,
        db=_db(),
        session_id="s",
        tools=[deploy],
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=None, uncompacted_runs=1, min_fold_ratio=0, model=_StubModel()),
    )
    for i in range(4):
        agent.run(f"question number {i}")
    assert agent.compact(session_id="s").compacted

    pause["next"] = True
    paused = agent.run("please deploy")
    assert paused.is_paused
    sent_by_the_run = [m.content for m in model.requests[-1]]
    for requirement in paused.active_requirements:
        requirement.confirm()

    if use_async:
        asyncio.run(agent.acontinue_run(run_id=paused.run_id, requirements=paused.requirements, session_id="s"))
    else:
        agent.continue_run(run_id=paused.run_id, requirements=paused.requirements, session_id="s")

    sent = [str(m.content) for m in model.requests[-1]]
    assert any("SUMMARY" in text for text in sent)
    assert not any(text in ("question number 1", "question number 2") for text in sent)
    # The resumed request carries the same history the paused run did, then the run itself.
    assert [m.content for m in model.requests[-1]][: len(sent_by_the_run)] == sent_by_the_run


# --- session deletion -------------------------------------------------------------


def _folded_session(db, session_id: str, user_id: str):
    """An agent whose session has one stored fold."""
    from agno.agent import Agent

    agent = Agent(
        model=_RecordingModel.build(),
        db=db,
        session_id=session_id,
        user_id=user_id,
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=None, uncompacted_runs=1, min_fold_ratio=0, model=_StubModel()),
    )
    for i in range(4):
        agent.run(f"question number {i}")
    assert agent.compact(session_id=session_id, user_id=user_id).compacted
    return agent


def test_compaction_records_store_the_session_user():
    db = _db()
    _folded_session(db, "s1", "alice")

    assert [row["user_id"] for row in db.get_compactions_for_session("s1")] == ["alice"]


def test_deleting_a_session_deletes_its_compaction_records():
    """The records hold the folded transcript verbatim; a deleted conversation must not survive in them."""
    db = _db()
    agent = _folded_session(db, "s1", "alice")

    agent.delete_session(session_id="s1", user_id="alice")

    assert db.get_compactions_for_session("s1") == []


def test_a_session_recreated_under_the_same_id_inherits_nothing():
    """Records are found by session id. Left behind, they gave the new session the old fold and a
    search tool over the deleted conversation."""
    from agno.agent._messages import _stored_compaction
    from agno.session import AgentSession

    db = _db()
    agent = _folded_session(db, "s1", "alice")
    agent.delete_session(session_id="s1", user_id="alice")

    fresh = AgentSession(session_id="s1", user_id="alice", runs=[])
    assert _stored_compaction(agent, fresh) is None
    assert agent.compaction.tools_for("s1", db) is None


def test_a_user_scoped_bulk_delete_leaves_other_users_records_alone():
    db = _db()
    _folded_session(db, "alice-session", "alice")
    _folded_session(db, "bob-session", "bob")

    db.delete_sessions(["alice-session", "bob-session"], user_id="alice")

    assert db.get_compactions_for_session("alice-session") == []
    assert len(db.get_compactions_for_session("bob-session")) == 1


# --- token_counter -------------------------------------------------------------


def test_token_counter_decides_the_threshold():
    """compact_at_tokens is measured with the configured counter, not the local estimate."""
    from agno.agent import Agent
    from agno.agent._messages import _estimated_context_tokens

    seen = {}

    def counter(messages, tools):
        seen["messages"], seen["tools"] = len(messages), tools
        return 12_345

    agent = Agent(compaction=Compaction(token_counter=counter))
    tools = [{"type": "function", "function": {"name": "t"}}]

    assert _estimated_context_tokens(agent, _transcript(), tools) == 12_345
    assert seen == {"messages": len(_transcript()), "tools": tools}


def test_a_failing_token_counter_falls_back_to_the_local_estimate(caplog):
    """A counter is often a network call or third-party code; it must never fail a run."""
    from agno.agent import Agent
    from agno.agent._messages import _estimated_context_tokens

    def broken(messages, tools):
        raise ConnectionError("count endpoint down")

    local = _estimated_context_tokens(Agent(compaction=Compaction()), _transcript())
    with caplog.at_level(logging.WARNING, logger="agno"):
        counted = _estimated_context_tokens(Agent(compaction=Compaction(token_counter=broken)), _transcript())

    assert counted == local
    assert any("token_counter failed" in r.message for r in caplog.records)


def test_token_counter_must_be_a_function():
    with pytest.raises(TypeError, match="token_counter"):
        Compaction(token_counter=1_000)  # type: ignore[arg-type]


def test_a_models_own_count_tokens_is_a_valid_counter():
    """Model.count_tokens already takes (messages, tools), so no adapter or provider mapping is needed."""
    from agno.agent import Agent
    from agno.agent._messages import _estimated_context_tokens
    from agno.models.openai import OpenAIResponses

    class _Counting(OpenAIResponses):
        def count_tokens(self, messages, tools=None, output_schema=None):
            return 777

    agent = Agent(compaction=Compaction(token_counter=_Counting(id="gpt-5-mini").count_tokens))

    assert _estimated_context_tokens(agent, _transcript()) == 777


def test_async_runs_count_with_the_token_counter_off_the_event_loop():
    import asyncio
    import threading

    from agno.agent import Agent
    from agno.agent._messages import _acompaction_inputs

    threads = []

    def counter(messages, tools):
        threads.append(threading.current_thread())
        return 42

    agent = Agent(compaction=Compaction(token_counter=counter))
    inputs = asyncio.run(_acompaction_inputs(agent, _transcript()))

    assert inputs["context_tokens"] == 42
    assert threads and threads[0] is not threading.main_thread()


def test_overflow_recovery_sizes_the_request_with_the_token_counter(caplog):
    """The before/after sizes in the recovery log come from the same counter as the threshold."""
    from agno.agent import Agent
    from agno.agent._messages import _recompact_after_overflow
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    messages = [Message(role="system", content="sys", id="s0")]
    messages += [
        m
        for i in range(30)
        for m in (
            Message(role="user", content=f"q{i} " * 30, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 800, id=f"a{i}"),
        )
    ]
    run_messages = _RunMessages(messages)
    agent = Agent(
        num_history_runs=50,
        compaction=Compaction(
            uncompacted_runs=5,
            store_compacted_messages=False,
            model=_StubModel(),
            on_context_overflow=True,
            token_counter=lambda msgs, tools: 1_000 * len(msgs),
        ),
    )

    with caplog.at_level(logging.INFO, logger="agno"):
        assert _recompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None)
    assert any(f"(61000 -> {1_000 * len(run_messages.messages)} tokens)" in r.message for r in caplog.records)


def test_async_overflow_recovery_counts_with_the_token_counter_off_the_event_loop(caplog):
    """The async recovery sizes the request with the same counter, run in a worker thread - a
    counter is usually a network call, and the event loop must not wait on it."""
    import asyncio
    import threading

    from agno.agent import Agent
    from agno.agent._messages import _arecompact_after_overflow
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    class _AsyncStub(_StubModel):
        async def aresponse(self, messages, **kwargs):
            return self.response(messages)

    counted_on = []

    def counter(msgs, tools):
        counted_on.append(threading.current_thread())
        return 1_000 * len(msgs)

    messages = [Message(role="system", content="sys", id="s0")]
    messages += [
        m
        for i in range(30)
        for m in (
            Message(role="user", content=f"q{i} " * 30, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 800, id=f"a{i}"),
        )
    ]
    run_messages = _RunMessages(messages)
    agent = Agent(
        num_history_runs=50,
        compaction=Compaction(
            uncompacted_runs=5,
            store_compacted_messages=False,
            model=_AsyncStub(),
            on_context_overflow=True,
            token_counter=counter,
        ),
    )

    async def recover():
        return await _arecompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None)

    with caplog.at_level(logging.INFO, logger="agno"):
        assert asyncio.run(recover())
    assert any(f"(61000 -> {1_000 * len(run_messages.messages)} tokens)" in r.message for r in caplog.records)
    assert counted_on and all(thread is not threading.main_thread() for thread in counted_on)


@pytest.mark.parametrize("use_async", [False, True])
def test_the_token_counter_is_only_called_when_its_count_is_used(use_async):
    """A token_counter is usually a network call. Without compact_at_tokens the trigger has nothing
    to compare against, and a manual compact sizes its record with measure(), so neither may call
    it - both used to, and threw the count away."""
    import asyncio

    from agno.agent import Agent

    class _AsyncStub(_StubModel):
        async def aresponse(self, messages, **kwargs):
            return self.response(messages)

    calls = []

    def counter(messages, tools):
        calls.append(len(messages))
        return 10 * len(messages)

    agent = Agent(
        model=_RecordingModel.build(),
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(
            compact_at_tokens=None, uncompacted_runs=1, min_fold_ratio=0, token_counter=counter, model=_AsyncStub()
        ),
    )

    async def scenario():
        for i in range(4):
            await agent.arun(f"question number {i}")
        return await agent.acompact(session_id="s")

    if use_async:
        result = asyncio.run(scenario())
    else:
        for i in range(4):
            agent.run(f"question number {i}")
        result = agent.compact(session_id="s")

    assert result.compacted
    assert result.record.tokens_before  # still sized, by measure()
    assert calls == []


def _model_that_counts(calls):
    """A recording model whose own token counts are recorded, sync and async separately."""
    import threading

    model = _RecordingModel.build()

    def count_tokens(messages, tools=None, output_schema=None):
        calls.append(("sync", threading.current_thread()))
        return 10 * len(messages)

    async def acount_tokens(messages, tools=None, output_schema=None):
        calls.append(("async", threading.current_thread()))
        return 10 * len(messages)

    model.count_tokens = count_tokens  # type: ignore[method-assign]
    model.acount_tokens = acount_tokens  # type: ignore[method-assign]
    return model


def _agent_counting_with_its_model(calls):
    from agno.agent import Agent

    return Agent(
        model=_model_that_counts(calls),
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=10_000, use_model_token_count=True, model=_StubModel()),
    )


def test_use_model_token_count_counts_with_count_tokens_in_sync_runs():
    """The model the request goes to counts it - users never pass, or need to know, count_tokens."""
    calls = []
    agent = _agent_counting_with_its_model(calls)
    for i in range(3):
        agent.run(f"question number {i}")

    assert [kind for kind, _ in calls] == ["sync", "sync"]  # every run with history to measure


def test_use_model_token_count_awaits_acount_tokens_in_async_runs():
    """Async runs await the model's async count on the event loop: no worker thread, and never the
    sync count_tokens, which would block the loop for a network call."""
    import asyncio
    import threading

    calls = []
    agent = _agent_counting_with_its_model(calls)

    async def scenario():
        for i in range(3):
            await agent.arun(f"question number {i}")

    asyncio.run(scenario())

    assert [kind for kind, _ in calls] == ["async", "async"]
    assert all(thread is threading.main_thread() for _, thread in calls)


def test_a_failing_model_count_falls_back_to_the_local_estimate(caplog):
    import asyncio

    from agno.agent import Agent

    model = _RecordingModel.build()

    async def broken(messages, tools=None, output_schema=None):
        raise RuntimeError("count endpoint down")

    model.acount_tokens = broken  # type: ignore[method-assign]
    agent = Agent(
        model=model,
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=10_000, use_model_token_count=True, model=_StubModel()),
    )

    async def scenario():
        await agent.arun("question number 0")
        return await agent.arun("question number 1")

    with caplog.at_level(logging.WARNING, logger="agno"):
        run = asyncio.run(scenario())

    assert run.content == "ok"
    assert any("model's token count failed" in r.message for r in caplog.records)


def test_use_model_token_count_and_token_counter_cannot_both_be_set():
    with pytest.raises(ValueError, match="cannot both be set"):
        Compaction(use_model_token_count=True, token_counter=lambda messages, tools: 1)


def _async_counters():
    import functools

    from agno.models.openai import OpenAIResponses

    async def count(messages, tools):
        return 1

    class _AsyncCall:
        async def __call__(self, messages, tools):
            return 1

    return {
        "model.acount_tokens": OpenAIResponses(id="gpt-5.6-luna").acount_tokens,
        "async def": count,
        "partial of async": functools.partial(count),
        "async __call__": _AsyncCall(),
    }


@pytest.mark.parametrize("name", list(_async_counters()))
def test_every_form_of_async_token_counter_is_accepted_and_recognised(name):
    """callable() alone cannot tell an async counter from a sync one, so each form has to be
    recognised: async runs await it, sync runs refuse it."""
    from agno.compaction._tokens import is_async_callable

    counter = _async_counters()[name]
    assert Compaction(token_counter=counter).token_counter is counter
    assert is_async_callable(counter)


def _agent_with_async_counter(seen):
    import threading

    from agno.agent import Agent

    async def counter(messages, tools):
        seen.append(threading.current_thread())
        return 10 * len(messages)

    return Agent(
        model=_RecordingModel.build(),
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=10_000, token_counter=counter, model=_StubModel()),
    )


def test_async_runs_await_an_async_token_counter_on_the_event_loop():
    import asyncio
    import threading

    seen = []
    agent = _agent_with_async_counter(seen)

    async def scenario():
        for i in range(3):
            await agent.arun(f"question number {i}")

    asyncio.run(scenario())

    assert len(seen) == 2  # every run with history to measure
    assert all(thread is threading.main_thread() for thread in seen)


def test_a_sync_run_refuses_an_async_token_counter():
    """A sync run has nothing to await an async counter with. Falling back to the local estimate
    would quietly ignore what the user configured, so the run fails and says what to do instead."""
    from agno.run.base import RunStatus

    seen = []
    agent = _agent_with_async_counter(seen)
    agent.run("question number 0")
    run = agent.run("question number 1")

    assert run.status == RunStatus.error
    assert "only count in async runs" in run.content
    assert seen == []


def test_a_sync_counter_that_returns_a_coroutine_falls_back_without_leaking_it(caplog):
    """A lambda around an async call looks sync but hands back a coroutine. It is closed - not left to
    warn "never awaited" - and the local estimate is used."""
    import warnings

    from agno.compaction._tokens import count_request

    async def count(messages, tools):
        return 1

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with caplog.at_level(logging.WARNING, logger="agno"):
            assert count_request(lambda m, t: count(m, t), [Message(role="user", content="hi")]) is None
    assert any("returned a coroutine" in r.message for r in caplog.records)


def test_async_overflow_recovery_awaits_an_async_token_counter(caplog):
    import asyncio

    from agno.agent import Agent
    from agno.agent._messages import _arecompact_after_overflow
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    class _AsyncStub(_StubModel):
        async def aresponse(self, messages, **kwargs):
            return self.response(messages)

    async def counter(msgs, tools):
        return 1_000 * len(msgs)

    messages = [Message(role="system", content="sys", id="s0")]
    messages += [
        m
        for i in range(30)
        for m in (
            Message(role="user", content=f"q{i} " * 30, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 800, id=f"a{i}"),
        )
    ]
    run_messages = _RunMessages(messages)
    agent = Agent(
        num_history_runs=50,
        compaction=Compaction(
            uncompacted_runs=5,
            store_compacted_messages=False,
            model=_AsyncStub(),
            on_context_overflow=True,
            token_counter=counter,
        ),
    )

    with caplog.at_level(logging.INFO, logger="agno"):
        assert asyncio.run(
            _arecompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None)
        )
    assert any(f"(61000 -> {1_000 * len(run_messages.messages)} tokens)" in r.message for r in caplog.records)


@pytest.mark.parametrize("use_async", [False, True])
def test_overflow_recovery_sizes_the_request_with_the_models_own_count(use_async, caplog):
    import asyncio

    from agno.agent import Agent
    from agno.agent._messages import _arecompact_after_overflow, _recompact_after_overflow
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    class _AsyncStub(_StubModel):
        async def aresponse(self, messages, **kwargs):
            return self.response(messages)

    messages = [Message(role="system", content="sys", id="s0")]
    messages += [
        m
        for i in range(30)
        for m in (
            Message(role="user", content=f"q{i} " * 30, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 800, id=f"a{i}"),
        )
    ]
    run_messages = _RunMessages(messages)
    calls = []
    agent = Agent(
        model=_model_that_counts(calls),
        num_history_runs=50,
        compaction=Compaction(
            uncompacted_runs=5,
            store_compacted_messages=False,
            model=_AsyncStub(),
            on_context_overflow=True,
            use_model_token_count=True,
        ),
    )
    session = AgentSession(session_id="s1", runs=[])

    with caplog.at_level(logging.INFO, logger="agno"):
        if use_async:
            assert asyncio.run(_arecompact_after_overflow(agent, session, run_messages, None))
        else:
            assert _recompact_after_overflow(agent, session, run_messages, None)

    assert any(f"(610 -> {10 * len(run_messages.messages)} tokens)" in r.message for r in caplog.records)
    assert {kind for kind, _ in calls} == {"async" if use_async else "sync"}


def test_uncompacted_runs_and_uncompacted_tokens_are_mutually_exclusive():
    """Two settings claiming the same tail is a configuration nobody can reason about.

    Raised rather than resolved silently: honouring one of two values the user deliberately
    set is the kind of surprise that costs an afternoon to track down.
    """
    with pytest.raises(ValueError, match="cannot both be set"):
        Compaction(uncompacted_runs=3, uncompacted_tokens=40_000)

    # The default run count is not a choice, so it does not collide.
    c = Compaction(uncompacted_tokens=40_000)
    assert c.uncompacted_tokens == 40_000
    assert c.uncompacted_runs is None


def test_a_decline_does_not_suggest_a_knob_that_cannot_help(caplog):
    """Shrinking the tail only moves the boundary while the tail holds more than one turn.

    The cut is pair-safe, so it never lands inside a turn. Once the tail is a single turn no
    smaller budget can shrink it - observed lowering uncompacted_tokens from 4,000 to 100 with
    the ratio unchanged at 1.01. Advice to lower it there sends the reader nowhere.
    """
    head = [Message(role="user", content="q " * 12), Message(role="assistant", content="w " * 4540)]
    one_turn = [Message(role="user", content="q " * 12), Message(role="assistant", content="w " * 4936)]
    two_turns = [
        m
        for _ in range(2)
        for m in (Message(role="user", content="q " * 12), Message(role="assistant", content="w " * 2468))
    ]
    c = Compaction(enforce_min_fold_ratio=True, uncompacted_tokens=2_000)

    with caplog.at_level(logging.INFO, logger="agno"):
        c._worth_compacting(head, one_turn)
    assert "uncompacted_tokens" not in " ".join(r.message for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="agno"):
        c._worth_compacting(head, two_turns)
    assert "uncompacted_tokens" in " ".join(r.message for r in caplog.records)


def test_a_decline_names_continuing_first(caplog):
    """The fold grows with every turn while the tail stays roughly fixed.

    So waiting is usually the real answer, and it should be named before the config knobs.
    """
    head = [Message(role="user", content="q " * 12), Message(role="assistant", content="w " * 4540)]
    tail = [Message(role="user", content="q " * 12), Message(role="assistant", content="w " * 4936)]

    with caplog.at_level(logging.INFO, logger="agno"):
        Compaction(enforce_min_fold_ratio=True, uncompacted_tokens=2_000)._worth_compacting(head, tail)

    message = " ".join(r.message for r in caplog.records)
    assert message.index("Continue the conversation") < message.index("lower min_fold_ratio")


def test_declines_name_the_tail_setting_actually_in_force(caplog):
    """Telling someone to lower uncompacted_runs when they set uncompacted_tokens is a dead end.

    The run count is None once a token budget is configured, so a message naming it sends the
    reader to a setting that does not exist.
    """
    tiny = [Message(role="user", content="hi", id="u0"), Message(role="assistant", content="hello", id="a0")]

    with caplog.at_level(logging.INFO, logger="agno"):
        Compaction(uncompacted_tokens=40_000).plan(tiny)

    message = " ".join(r.message for r in caplog.records)
    assert "uncompacted_tokens=40000" in message
    assert "uncompacted_runs" not in message


def test_an_explicit_default_value_still_collides():
    """uncompacted_runs=5 written by hand is a choice, even though 5 is also the default.

    Comparing against the value alone cannot tell the two apart, so an explicit 5 alongside
    uncompacted_tokens was silently discarded - the exact surprise the mutual exclusion exists
    to prevent.
    """
    with pytest.raises(ValueError, match="cannot both be set"):
        Compaction(uncompacted_runs=5, uncompacted_tokens=20_000)

    # The untouched default still does not collide.
    assert Compaction(uncompacted_tokens=20_000).uncompacted_runs is None


def test_opting_into_overflow_recovery_drops_the_default_threshold():
    """Asking to fold on rejection is asking NOT to fold at a guessed size.

    Every large model's window sits above 150k, so a default threshold would fire first and
    the flag would be dead code - the user would have asked for something that never runs.
    """
    assert Compaction(on_context_overflow=True).compact_at_tokens is None
    assert Compaction(on_context_overflow=True, uncompacted_tokens=50_000).compact_at_tokens is None

    # Without the flag the default stands.
    assert Compaction().compact_at_tokens == 150_000


def test_an_explicit_threshold_survives_the_overflow_flag():
    """Naming both is unusual but coherent: fold at my size, and again if the provider says so.

    An explicit 150_000 must survive too - the default value is not the same as the default.
    """
    assert Compaction(on_context_overflow=True, compact_at_tokens=100_000).compact_at_tokens == 100_000
    assert Compaction(on_context_overflow=True, compact_at_tokens=150_000).compact_at_tokens == 150_000


def test_reactive_recovery_is_opt_in_on_a_configured_compaction():
    """A configured Compaction already has a threshold, so a rejection means it was wrong.

    That is worth surfacing rather than absorbing, so recovery is off unless asked for.
    compaction=True is the exception: with no threshold to rely on, the rejection is the
    only thing that can fold, so it is turned on there.
    """
    from agno.agent import Agent, _init

    bare = Agent(compaction=True)
    _init.set_compaction(bare)
    assert bare.compaction.compact_at_tokens is None
    assert bare.compaction.on_context_overflow is True

    configured = Agent(compaction=Compaction())
    _init.set_compaction(configured)
    assert configured.compaction.compact_at_tokens == 150_000
    assert configured.compaction.on_context_overflow is False

    opted_in = Agent(compaction=Compaction(on_context_overflow=True))
    _init.set_compaction(opted_in)
    assert opted_in.compaction.on_context_overflow is True


def test_compaction_true_is_reactive_only():
    """A proactive threshold is a guess about a number nobody can look up.

    No provider exposes its context window, and the same model id differs across deployments,
    so 150k is wrong for a 32k model and pointless for a 1M one. compaction=True waits for the
    rejection, which is always right - at the cost of one failed request before the first fold.
    Passing a Compaction object opts into the threshold, because someone configuring it has a
    size in mind.
    """
    from agno.agent import Agent, _init

    bare = Agent(compaction=True)
    _init.set_compaction(bare)
    assert bare.compaction.compact_at_tokens is None
    assert bare.compaction.on_context_overflow is True

    configured = Agent(compaction=Compaction())
    _init.set_compaction(configured)
    assert configured.compaction.compact_at_tokens == 150_000


def test_compaction_true_never_fires_the_proactive_trigger():
    """The threshold is off, not merely large - a 200k context still does not trip it."""
    from agno.agent import Agent, _init

    agent = Agent(compaction=True)
    _init.set_compaction(agent)

    assert agent.compaction.should_compact(_transcript(), context_tokens=200_000, model=None) is False


def test_the_archive_is_searchable_by_default():
    """An archive the agent cannot reach only helps a developer reading a row.

    The tool is still withheld until something has actually been archived, so it costs nothing
    on a conversation that never folds.
    """
    c = Compaction()

    assert c.store_compacted_messages is True
    assert c.search_compacted_messages is True
    assert c.tools_for("s1", None) is None  # nothing archived yet


def test_uncompacted_tokens_rejects_non_positive_values():
    with pytest.raises(ValueError, match="uncompacted_tokens"):
        Compaction(uncompacted_tokens=0)


def test_context_overflow_folds_and_asks_for_a_retry():
    """The provider's rejection is the only authoritative signal that a threshold was wrong.

    No provider exposes its context window, and the same model id differs across deployments,
    so compact_at_tokens is always a guess. This folds against the messages actually sent -
    reaching the current turn and anything a tool loop appended, which the run-start pass
    cannot - and reports whether the payload is worth resending.
    """
    from agno.agent import Agent
    from agno.agent._messages import _recompact_after_overflow
    from agno.compaction._tokens import estimate_tokens
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    messages = [Message(role="system", content="sys", id="s0")]
    messages += [
        m
        for i in range(30)
        for m in (
            Message(role="user", content=f"q{i} " * 30, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 800, id=f"a{i}"),
        )
    ]
    run_messages = _RunMessages(messages)
    before = estimate_tokens(messages)
    agent = Agent(
        num_history_runs=50,
        compaction=Compaction(
            uncompacted_runs=5, store_compacted_messages=False, model=_StubModel(), on_context_overflow=True
        ),
    )

    assert _recompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None) is True
    assert estimate_tokens(run_messages.messages) < before


@pytest.mark.parametrize("ratio", [-1, -0.5, -2])
def test_a_negative_min_fold_ratio_raises_naming_the_setting(ratio):
    """-1 divided by zero in the tail limit; other negatives gave a nonsense limit silently."""
    with pytest.raises(ValueError, match="min_fold_ratio"):
        Compaction(min_fold_ratio=ratio)


def test_a_model_string_is_resolved_to_a_model():
    """A "provider:model_id" string is accepted, as on the other managers. Left unresolved, the
    first fold called .response on a str and failed."""
    from agno.models.base import Model

    compaction = Compaction(model="openai:gpt-5.6-luna")

    assert isinstance(compaction.model, Model)
    assert compaction.model.id == "gpt-5.6-luna"


def test_revalidating_a_valid_config_never_raises():
    """Overflow recovery derives variants of the configured Compaction with dataclasses.replace(),
    which re-runs __post_init__. A config that validated once must validate again."""
    from dataclasses import replace

    for config in (
        Compaction(),
        Compaction(uncompacted_runs=3),
        Compaction(uncompacted_tokens=2_000),
        Compaction(uncompacted_tokens=2_000, on_context_overflow=True),
    ):
        assert replace(config, min_fold_ratio=0).min_fold_ratio == 0

    with pytest.raises(ValueError, match="cannot both be set"):
        Compaction(uncompacted_runs=3, uncompacted_tokens=2_000)


def test_overflow_recovery_works_with_a_token_tail():
    """uncompacted_tokens used to make recovery raise a config error inside the provider-error
    handler, so the user saw a ValueError instead of a recovered run."""
    from agno.agent import Agent
    from agno.agent._messages import _recompact_after_overflow
    from agno.compaction._tokens import estimate_tokens
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    messages = [Message(role="system", content="sys", id="s0")]
    messages += [
        m
        for i in range(30)
        for m in (
            Message(role="user", content=f"q{i} " * 30, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 800, id=f"a{i}"),
        )
    ]
    run_messages = _RunMessages(messages)
    before = estimate_tokens(messages)
    agent = Agent(
        num_history_runs=50,
        compaction=Compaction(
            uncompacted_tokens=3_000, store_compacted_messages=False, model=_StubModel(), on_context_overflow=True
        ),
    )

    assert _recompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None) is True
    assert estimate_tokens(run_messages.messages) < before


@pytest.mark.parametrize("stream", [False, True])
def test_async_overflow_recovery_does_not_block_the_event_loop(stream):
    """On the async path the summarizer must be awaited. Run synchronously it held the event loop
    for the whole model call, so every other request on the server waited on this one."""
    import asyncio
    import time

    from agno.agent import Agent
    from agno.exceptions import ContextWindowExceededError
    from agno.models.response import ModelResponse

    used = []

    class _SlowSummarizer:
        id = "stub"

        def response(self, messages, **kwargs):
            used.append("sync")
            time.sleep(0.3)
            return ModelResponse(content="SUMMARY")

        async def aresponse(self, messages, **kwargs):
            used.append("async")
            await asyncio.sleep(0.3)
            return ModelResponse(content="SUMMARY")

    model = _RecordingModel.build()
    calls = {"n": 0}
    reject_on = 6

    original_ainvoke, original_stream = model.ainvoke, model.ainvoke_stream

    async def ainvoke(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == reject_on:
            raise ContextWindowExceededError("prompt is too long")
        return await original_ainvoke(*args, **kwargs)

    async def ainvoke_stream(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == reject_on:
            raise ContextWindowExceededError("prompt is too long")
        async for chunk in original_stream(*args, **kwargs):
            yield chunk

    model.ainvoke, model.ainvoke_stream = ainvoke, ainvoke_stream
    agent = Agent(
        model=model,
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(
            compact_at_tokens=None, on_context_overflow=True, uncompacted_runs=1, model=_SlowSummarizer()
        ),
    )

    async def scenario():
        for i in range(5):
            await agent.arun(f"question number {i}")
        gaps, stop = [], asyncio.Event()

        async def heartbeat():
            last = time.perf_counter()
            while not stop.is_set():
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        beat = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.03)
        if stream:
            async for _ in agent.arun("question number 5", stream=True):
                pass
        else:
            await agent.arun("question number 5")
        stop.set()
        await beat
        return max(gaps)

    longest_stall = asyncio.run(scenario())

    assert used == ["async"]
    assert longest_stall < 0.15


def test_overflow_retry_sends_the_compacted_payload():
    """The retry has to reach the provider, not just the helper's own variable.

    The model call already holds the message list object in its kwargs, so rebinding an
    attribute leaves the retry sending exactly the payload that was just rejected - two
    identical failures instead of a recovery.
    """
    from agno.compaction._tokens import estimate_tokens
    from agno.exceptions import ContextWindowExceededError
    from agno.models.fallback import call_model_with_fallback
    from agno.models.response import ModelResponse

    received = []

    class _Model:
        id = "m"

        def __init__(self):
            self.calls = 0

        def response(self, **kwargs):
            self.calls += 1
            received.append(estimate_tokens(kwargs["messages"]))
            if self.calls == 1:
                raise ContextWindowExceededError("too long")
            return ModelResponse(content="ok")

    messages = [Message(role="user", content="q " * 2000)]

    def _fold() -> bool:
        messages[:] = [Message(role="user", content="tiny")]
        return True

    call_model_with_fallback(_Model(), None, recover_from_overflow=_fold, messages=messages)

    assert len(received) == 2
    assert received[1] < received[0]


def test_streaming_also_recovers_from_an_overflow():
    """print_response streams, so a streaming-only gap means most users never recover.

    The rejection for length arrives before the first chunk, so nothing has been yielded yet
    and the retry can safely start the stream from scratch.
    """
    from agno.compaction._tokens import estimate_tokens
    from agno.exceptions import ContextWindowExceededError
    from agno.models.fallback import call_model_stream_with_fallback
    from agno.models.response import ModelResponse

    received = []

    class _Model:
        id = "m"

        def __init__(self):
            self.calls = 0

        def response_stream(self, **kwargs):
            self.calls += 1
            received.append(estimate_tokens(kwargs["messages"]))
            if self.calls == 1:
                raise ContextWindowExceededError("prompt is too long: 326371 tokens > 200000 maximum")
            yield ModelResponse(content="recovered")

    messages = [Message(role="user", content="q " * 2000)]

    def _fold() -> bool:
        messages[:] = [Message(role="user", content="tiny")]
        return True

    events = list(call_model_stream_with_fallback(_Model(), None, recover_from_overflow=_fold, messages=messages))

    assert len(received) == 2
    assert received[1] < received[0]
    assert [e.content for e in events] == ["recovered"]


@pytest.mark.parametrize("use_async", [False, True])
def test_overflow_recovery_counts_the_summarizer_in_run_metrics(use_async):
    """The summarizer call an overflow makes is billed like any other model call, so it belongs in
    the run's metrics under compaction_model - as it is when the run-start trigger folds."""
    import asyncio

    from agno.agent import Agent
    from agno.exceptions import ContextWindowExceededError

    model = _RecordingModel.build()
    calls = {"n": 0}
    invoke, ainvoke = model.invoke, model.ainvoke

    def reject_sixth(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 6:
            raise ContextWindowExceededError("prompt is too long")
        return invoke(*args, **kwargs)

    async def areject_sixth(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 6:
            raise ContextWindowExceededError("prompt is too long")
        return await ainvoke(*args, **kwargs)

    # Patch only the entry point each path calls: the recording ainvoke delegates to invoke, so
    # patching both would count every async call twice.
    if use_async:
        model.ainvoke = areject_sixth
    else:
        model.invoke = reject_sixth
    agent = Agent(
        model=model,
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(
            compact_at_tokens=None,
            on_context_overflow=True,
            uncompacted_runs=1,
            # These messages are tiny: the search instruction that comes with stored messages would
            # outweigh what the fold reclaims, and recovery rightly refuses a retry that does not shrink.
            store_compacted_messages=False,
            model=_MeteredSummarizer(),
        ),
    )

    async def arun_all():
        for i in range(6):
            run = await agent.arun(f"question number {i}")
        return run

    if use_async:
        run = asyncio.run(arun_all())
    else:
        for i in range(6):
            run = agent.run(f"question number {i}")

    assert run.compaction is not None
    entries = (run.metrics.details or {}).get("compaction_model") or []
    assert [(entry.id, entry.input_tokens, entry.output_tokens) for entry in entries] == [("summarizer", 700, 40)]


class _MeteredSummarizer:
    """A summarizer whose responses carry token usage."""

    id = "summarizer"
    provider = "test"

    def get_provider(self):
        return self.provider

    def response(self, messages, **kwargs):
        from agno.metrics import MessageMetrics
        from agno.models.response import ModelResponse

        usage = MessageMetrics(input_tokens=700, output_tokens=40, total_tokens=740)
        return ModelResponse(content="SUMMARY", response_usage=usage)

    async def aresponse(self, messages, **kwargs):
        return self.response(messages)


@pytest.mark.parametrize("use_async", [False, True])
def test_a_threshold_fold_counts_the_summarizer_in_run_metrics(use_async):
    """A fold triggered by compact_at_tokens happens inside the run, so its summarizer call is in
    that run's metrics under compaction_model."""
    import asyncio

    from agno.agent import Agent

    agent = Agent(
        model=_RecordingModel.build(),
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=40, uncompacted_runs=1, min_fold_ratio=0, model=_MeteredSummarizer()),
    )

    async def arun_all():
        return [await agent.arun(f"question number {i} " + "word " * 10) for i in range(4)]

    runs = (
        asyncio.run(arun_all()) if use_async else [agent.run(f"question number {i} " + "word " * 10) for i in range(4)]
    )

    folded = [run for run in runs if run.compaction is not None]
    assert folded
    entries = folded[0].metrics.details["compaction_model"]
    assert [(entry.id, entry.input_tokens, entry.output_tokens) for entry in entries] == [("summarizer", 700, 40)]


@pytest.mark.parametrize("use_async", [False, True])
def test_manual_compact_reports_the_summarizer_usage(use_async):
    """agent.compact() has no run to add the summarizer's tokens to, so the result carries them."""
    import asyncio

    from agno.agent import Agent

    agent = Agent(
        model=_RecordingModel.build(),
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=None, uncompacted_runs=1, min_fold_ratio=0, model=_MeteredSummarizer()),
    )
    for i in range(4):
        agent.run(f"question number {i}")

    result = asyncio.run(agent.acompact(session_id="s")) if use_async else agent.compact(session_id="s")

    assert result.compacted
    entries = result.metrics.details["compaction_model"]
    assert [(entry.id, entry.input_tokens, entry.output_tokens) for entry in entries] == [("summarizer", 700, 40)]
    assert result.to_dict()["metrics"]["details"]["compaction_model"][0]["input_tokens"] == 700


def _stored_compaction_usage(db, session_id):
    """The compaction_model entries in the session's stored metrics, read back from the database."""
    from agno.db.base import SessionType

    session = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    metrics = (session.session_data or {}).get("session_metrics") or {}
    entries = (metrics.get("details") or {}).get("compaction_model") or []
    return [(entry["id"], entry["input_tokens"], entry["output_tokens"]) for entry in entries]


def test_a_threshold_fold_is_added_to_the_session_metrics():
    """A fold inside a run is in that run's metrics, and the session's totals add up its runs."""
    from agno.agent import Agent

    db = _db()
    agent = Agent(
        model=_RecordingModel.build(),
        db=db,
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=40, uncompacted_runs=1, min_fold_ratio=0, model=_MeteredSummarizer()),
    )
    runs = [agent.run(f"question number {i} " + "word " * 10) for i in range(4)]

    assert any(run.compaction is not None for run in runs)
    assert ("summarizer", 700, 40) in _stored_compaction_usage(db, "s")


@pytest.mark.parametrize("use_async", [False, True])
def test_manual_compact_is_added_to_the_session_metrics(use_async):
    """A manual fold has no run, so its summarizer call is added to the session's metrics directly -
    otherwise session totals, and the AgentOS metrics built from them, would leave it out."""
    import asyncio

    from agno.agent import Agent
    from agno.db.base import SessionType

    db = _db()
    agent = Agent(
        model=_RecordingModel.build(),
        db=db,
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=None, uncompacted_runs=1, min_fold_ratio=0, model=_MeteredSummarizer()),
    )
    for i in range(4):
        agent.run(f"question number {i}")
    stored = db.get_session(session_id="s", session_type=SessionType.AGENT).session_data["session_metrics"]
    before = stored.get("total_tokens", 0)

    result = asyncio.run(agent.acompact(session_id="s")) if use_async else agent.compact(session_id="s")

    assert result.compacted
    assert _stored_compaction_usage(db, "s") == [("summarizer", 700, 40)]
    after = db.get_session(session_id="s", session_type=SessionType.AGENT).session_data["session_metrics"]
    assert after["total_tokens"] == before + 740


def test_a_declined_manual_compact_reports_no_usage():
    """No summarizer call was made, so there is nothing to report."""
    from agno.agent import Agent

    agent = Agent(
        model=_RecordingModel.build(),
        db=_db(),
        session_id="s",
        add_history_to_context=True,
        compaction=Compaction(compact_at_tokens=None, uncompacted_runs=10, model=_MeteredSummarizer()),
    )
    agent.run("only question")

    result = agent.compact(session_id="s")

    assert not result.compacted
    assert result.metrics is None
    assert result.to_dict()["metrics"] is None
    assert "compaction_model" not in (agent.get_session_metrics(session_id="s").details or {})


def test_context_overflow_does_not_retry_what_it_cannot_shrink(caplog):
    """Retrying an identical payload just fails twice."""
    from agno.agent import Agent
    from agno.agent._messages import _recompact_after_overflow
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    run_messages = _RunMessages(
        [
            Message(role="system", content="sys", id="s0"),
            Message(role="user", content="analyse", id="u0"),
            Message(role="assistant", content="f " * 60000, id="a0"),
        ]
    )
    agent = Agent(
        compaction=Compaction(
            uncompacted_runs=1, store_compacted_messages=False, model=_StubModel(), on_context_overflow=True
        )
    )

    with caplog.at_level(logging.WARNING, logger="agno"):
        assert _recompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None) is False
    assert any("no safe cut left" in r.message for r in caplog.records)


def test_context_overflow_is_a_no_op_without_compaction():
    """An agent with no compaction configured must not be changed by the overflow path."""
    from agno.agent import Agent
    from agno.agent._messages import _recompact_after_overflow
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    run_messages = _RunMessages([Message(role="user", content="hi", id="u0")])

    assert _recompact_after_overflow(Agent(), AgentSession(session_id="s1", runs=[]), run_messages, None) is False


# --- boundary safety -----------------------------------------------------


def test_boundary_never_splits_a_tool_batch():
    """The kept tail must never begin with an unanswered tool result."""
    messages = _transcript(runs=3)
    for keep in range(len(messages) + 1):
        c = Compaction(uncompacted_runs=keep)
        boundary = c.boundary_for(messages)
        tail = messages[boundary:]
        if tail:
            assert tail[0].role != "tool", f"orphaned tool result at keep={keep}"
        # every call kept in the compacted half is answered in that half
        answered = {m.tool_call_id for m in messages[:boundary] if m.role == "tool"}
        for message in messages[:boundary]:
            for call in message.tool_calls or []:
                assert call["id"] in answered, f"unanswered call at keep={keep}"


def test_boundary_keeps_requested_runs():
    messages = _transcript(runs=3)
    c = Compaction(uncompacted_runs=1)
    tail = messages[c.boundary_for(messages) :]
    assert tail[0].role == "user"
    assert tail[0].content == "question 2"


def test_keeping_everything_compacts_nothing():
    """No safe cut is None, not 0: there is nothing to fold, so the pass aborts."""
    messages = _transcript(runs=2)
    c = Compaction(uncompacted_runs=99)
    assert c.boundary_for(messages) is None


# --- applying ------------------------------------------------------------


def test_apply_record_replaces_head_with_summary():
    messages = _transcript(runs=3)
    record = _record(messages, 4, summary="Earlier: discussed 0 and 1.")
    c = Compaction()
    from agno.compaction.prompts import SUMMARY_PREFIX

    out = c.apply_record(messages, record)

    assert out[0].content.startswith(SUMMARY_PREFIX)
    assert "Earlier: discussed 0 and 1." in out[0].content
    assert [m.id for m in out[1:]] == [m.id for m in messages[4:]]


def test_summary_is_injected_into_the_view_only():
    """The summary exists in the derived view, never in the stored transcript.

    Views are rebuilt per call and discarded, so there is nothing to persist and
    no way for a later compaction to end up summarizing its own summary.
    """
    from agno.compaction.prompts import SUMMARY_PREFIX

    messages = _transcript()
    original = list(messages)
    c = Compaction()

    view = c.apply_record(messages, _record(messages, 3, summary="earlier turns"))

    injected = next(m for m in view if isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX))
    assert "earlier turns" in injected.content
    assert injected.from_history is True
    # The canonical list is untouched: same objects, same order, no summary in it.
    assert messages == original
    assert not any(isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX) for m in messages)


def test_kept_messages_lose_provider_side_conversation_state():
    """Compaction must not leave a provider able to replay the dropped turns.

    OpenAI Responses chains on previous_response_id from an assistant
    message's provider_data, and the server then replays the whole prior
    conversation - so the context looks compacted locally while the model
    still sees everything. The saving would be imaginary.
    """
    messages = [
        Message(role="user", content="q0"),
        Message(role="assistant", content="a0"),
        Message(role="user", content="q1"),
        Message(role="assistant", content="a1", provider_data={"response_id": "resp_123", "other": "keep"}),
    ]
    c = Compaction()

    kept = c.apply_record(messages, _record(messages, 2, summary="s"))

    tail = kept[1:]
    assert all("response_id" not in (m.provider_data or {}) for m in tail)
    # Unrelated provider_data is preserved.
    assert tail[-1].provider_data == {"other": "keep"}
    # The stored history itself is untouched.
    assert messages[3].provider_data["response_id"] == "resp_123"


def test_only_the_chaining_key_is_stripped_not_the_exchange():
    """Reasoning payload and tool exchanges survive; only response_id goes.

    Dropping the whole exchange would be the blunt fix. The precise one is to
    remove only the chaining key: a function_call still needs its paired
    reasoning item, which lives elsewhere in provider_data.
    """
    messages = [
        Message(role="user", content="q0"),
        Message(role="assistant", content="a0"),
        Message(role="user", content="q1"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
            provider_data={"response_id": "resp_123"},
        ),
        Message(role="tool", tool_call_id="call_1", tool_name="search", content="data"),
        Message(role="assistant", content="a1"),
    ]

    tail = Compaction().apply_record(messages, _record(messages, 2, summary="s"))[1:]

    # The exchange survives intact - only the chaining key is gone.
    assert any(m.role == "tool" for m in tail)
    assert any(m.tool_calls for m in tail)
    assert all("response_id" not in (m.provider_data or {}) for m in tail)
    # The canonical message keeps its provider_data.
    assert messages[3].provider_data["response_id"] == "resp_123"


def test_kept_messages_lose_gemini_interaction_chaining():
    """GeminiInteractions chains on interaction_id the way OpenAI Responses chains on response_id:
    left on a kept reply, the request sends previous_interaction_id and only what follows it, so
    the summary in front of it is never sent and the server replays the folded turns."""
    from agno.models.google.gemini_interactions import GeminiInteractions

    messages = []
    for i in range(3):
        messages.append(Message(role="user", content=f"q{i}"))
        messages.append(Message(role="assistant", content=f"a{i}", provider_data={"interaction_id": f"int_{i}"}))
    messages.append(Message(role="user", content="new"))

    view = Compaction().apply_record(messages, _record(messages, 4, summary="SUMMARY"))
    kwargs = GeminiInteractions(api_key="test-key")._get_request_kwargs(view)

    assert "previous_interaction_id" not in kwargs
    texts = [item["text"] for step in kwargs["input"] for item in step["content"]]
    assert texts[0].endswith("SUMMARY")
    assert texts[1:] == ["q2", "a2", "new"]
    assert messages[5].provider_data == {"interaction_id": "int_2"}  # the stored history is untouched


def test_tool_exchanges_survive_when_there_is_no_server_state():
    """Nothing is dropped for providers that send history in the request."""
    messages = [
        Message(role="user", content="q0"),
        Message(role="assistant", content="a0"),
        Message(role="user", content="q1"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
        ),
        Message(role="tool", tool_call_id="call_1", tool_name="search", content="data"),
    ]

    tail = Compaction().apply_record(messages, _record(messages, 2, summary="s"))[1:]

    assert any(m.role == "tool" for m in tail)
    assert any(m.tool_calls for m in tail)


def test_summary_points_at_the_archive_only_when_the_agent_can_read_it():
    """The lookup instruction is promised only when the tools exist.

    Without searchable the archive is for a developer, not the model. Telling
    it to read a file it cannot open invites a refusal or an invented answer.
    """
    messages = _transcript()
    archived = _record(messages, 3, summary="s", archived=True)

    searchable = Compaction(search_compacted_messages=True).apply_record(messages, archived)[0]
    not_searchable = Compaction(search_compacted_messages=False).apply_record(messages, archived)[0]
    no_archive = Compaction(search_compacted_messages=True).apply_record(messages, _record(messages, 3, summary="s"))[0]

    assert "searchable" in searchable.content
    assert "search it rather than relying" in searchable.content
    assert "searchable" not in not_searchable.content
    assert "searchable" not in no_archive.content


def test_summarizer_is_told_to_flag_gaps_only_when_archived():
    """A summary should declare what it dropped only if that is recoverable."""
    c = Compaction()

    archived = c._summary_messages(_transcript(), None, archived=True)[0].content
    plain = c._summary_messages(_transcript(), None, archived=False)[0].content

    assert "Not covered here:" in archived
    assert "Not covered here:" not in plain


def test_record_roundtrips_through_dict():
    record = CompactionRecord(
        messages_compacted=4, summary="s", first_kept_message_id="m-4", archived=True, tokens_before=100
    )
    assert CompactionRecord.from_dict(record.to_dict()) == record


def test_second_compaction_only_covers_what_is_new():
    """A span already compacted is not archived or summarized twice.

    The stored boundary is an absolute index into the full history, so a later
    compaction starts where the previous one stopped. Getting this wrong makes
    the boundary crawl forward one message per run, so the context never
    actually shrinks and every subsequent run compacts again.
    """
    messages = _transcript(runs=4)
    # min_fold_ratio=0: this exercises the boundary, not the size floor.
    c = Compaction(uncompacted_runs=1, min_fold_ratio=0, model=_StubModel())
    previous = _record(messages, 2, summary="earlier")

    record = c.compact(messages, session_id="s", db=None, previous=previous)

    assert record is not None
    # The new anchor sits strictly after the previous one.
    ids = [m.id for m in messages]
    assert ids.index(record.first_kept_message_id) > ids.index(previous.first_kept_message_id)
    # Only the messages after the previous boundary were sent to the summarizer.
    assert "question 0" not in c.model.seen
    assert "question 2" in c.model.seen


def test_no_new_span_does_not_recompact():
    messages = _transcript(runs=2)
    c = Compaction(uncompacted_runs=1)
    boundary = c.boundary_for(messages)
    previous = _record(messages, boundary, summary="s")

    assert c.compact(messages, session_id="s", db=None, previous=previous) is None


def test_skips_a_fold_that_cannot_pay_for_its_summary():
    """Folding barely more than is kept leaves the context bigger, not smaller."""
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(uncompacted_runs=1, model=_StubModel())

    assert c.compact(tiny, session_id="s", db=None) is None


def test_fold_ratio_can_be_disabled():
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
        Message(role="user", content="more"),
    ]
    c = Compaction(uncompacted_runs=1, min_fold_ratio=0, model=_StubModel())

    assert c.compact(messages, session_id="s", db=None) is not None


def test_large_fold_against_a_small_tail_clears_the_ratio():
    big = [
        Message(role="user", content="x" * 5_000),
        Message(role="assistant", content="y" * 5_000),
        Message(role="user", content="tiny"),
    ]
    c = Compaction(uncompacted_runs=1, model=_StubModel())

    assert c.compact(big, session_id="s", db=None) is not None


def test_plan_refuses_what_compact_would_refuse():
    """plan() is what callers announce on, so it must agree with compact().

    should_compact() alone cannot see the pair-safe boundary or the size
    floor, so announcing on it logs "Auto-compacting" and emits
    CompactionStarted for compactions that then never happen.
    """
    # Too small to be worth folding: whatever boundary exists, both must decline together.
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(uncompacted_runs=1, model=_StubModel())

    assert c.plan(tiny) is None
    assert c.compact(tiny, session_id="s", db=None) is None


def test_plan_agrees_with_compact_when_worthwhile():
    big = [
        Message(role="user", content="x" * 5_000),
        Message(role="assistant", content="y" * 5_000),
        Message(role="user", content="tiny"),
    ]
    c = Compaction(uncompacted_runs=1, model=_StubModel())

    boundary = c.plan(big)
    record = c.compact(big, session_id="s", db=None)

    assert boundary is not None
    assert record is not None
    assert record.first_kept_message_id == big[boundary].id


def test_run_output_carries_the_compaction_record():
    """`run.compaction` is the documented way to inspect what happened."""
    from agno.run.agent import RunOutput

    record = CompactionRecord(
        messages_compacted=6,
        summary="s",
        first_kept_message_id="m-6",
        archived=True,
        tokens_before=100,
        tokens_after=40,
    )
    run = RunOutput(run_id="r", session_id="s", compaction=record)

    restored = RunOutput.from_dict(run.to_dict())
    assert restored.compaction == record


def test_run_output_without_compaction_serializes_cleanly():
    from agno.run.agent import RunOutput

    assert "compaction" not in RunOutput(run_id="r", session_id="s").to_dict()
    assert RunOutput.from_dict({"run_id": "r", "session_id": "s"}).compaction is None


def test_unresolvable_anchor_fails_open():
    """A record whose anchor is not in this list must not cut anything.

    History is rebuilt from stored runs every run. An anchor that no longer
    resolves means the record does not describe this list - sending the full
    list is always valid, silently cutting at the wrong place is not.
    """
    from agno.compaction.prompts import SUMMARY_PREFIX

    messages = _transcript()
    stale = CompactionRecord(messages_compacted=4, summary="s", first_kept_message_id="not-in-this-list")

    view = Compaction().apply_record(messages, stale)

    assert [m.id for m in view] == [m.id for m in messages]
    assert not any(isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX) for m in view)


def test_boundary_never_anchors_on_a_message_that_will_not_persist():
    """A temporary message is gone by the next run; anchoring there would break."""
    messages = [
        Message(role="user", content="q0" * 400),
        Message(role="assistant", content="a0" * 400),
        Message(role="user", content="temp", temporary=True),
        Message(role="assistant", content="a1" * 400),
        Message(role="user", content="q2"),
    ]

    boundary = Compaction(uncompacted_runs=1).boundary_for(messages)

    assert boundary is None or not messages[boundary].temporary


def test_envelopes_do_not_count_against_the_fold_ratio():
    """A pinned envelope must not make every later fold look worthless.

    Envelopes are held in the kept tail by design, so their cost is not something folding could
    reclaim. Counting them would stall compaction entirely once offloading is on.
    """
    envelope = Message(
        role="tool",
        tool_call_id="c1",
        tool_name="dump",
        content='<result id="res_abc" tool="dump">' + "preview " * 400 + "</result>",
    )
    folded = [Message(role="user", content="q " * 300), Message(role="assistant", content="a " * 300)]
    tail = [envelope, Message(role="user", content="tiny")]

    c = Compaction()

    assert c._worth_compacting(folded, tail) is True


def test_folded_envelope_ids_survive_in_the_summary():
    """Folding an envelope must not orphan its payload.

    Pinning envelopes in the kept tail was the alternative, but one early envelope then caps the
    boundary forever and compaction stops working. Carrying the ids forward costs a line.
    """
    from agno.compaction._view import build_view

    messages = [
        Message(role="user", content="fetch"),
        Message(
            role="tool",
            tool_call_id="c1",
            tool_name="dump",
            content='<result id="res_abc" tool="dump">preview</result>',
        ),
        Message(role="assistant", content="done"),
        Message(role="user", content="later question"),
    ]
    record = CompactionRecord(messages_compacted=3, summary="earlier", first_kept_message_id=messages[3].id)

    view = build_view(messages, record)

    assert "res_abc" in view[0].content
    assert "read_result" in view[0].content


def test_grep_returns_numbered_lines_with_context():
    from agno.compaction.compaction import _grep

    text = "alpha\nbeta\nINC-42 here\ndelta\nepsilon"

    out = _grep(text, "INC-42", context_lines=1)

    assert "3: INC-42 here" in out
    assert "2: beta" in out
    assert "4: delta" in out
    assert "1: alpha" not in out


def test_search_patterns_are_literal_so_they_cannot_backtrack():
    """The pattern comes from a model. As a regex, "(a+)+$" backtracks for hours on a 40-character
    line and cannot be interrupted; as literal text it is a plain substring search."""
    import time

    from agno.compaction.compaction import _grep

    started = time.perf_counter()
    result = _grep("a" * 40 + "!", "(a+)+$")

    assert time.perf_counter() - started < 0.5
    assert result == ""
    assert "port \\d+ here" in _grep("literal port \\d+ here", "port \\d+", context_lines=0)


def test_search_alternatives_match_any_term_case_insensitively():
    from agno.compaction.compaction import _grep

    text = "Build hash b7f2\nRotation window: 47 days\nunrelated"
    out = _grep(text, "build hash|ROTATION window", context_lines=0)

    assert "Build hash b7f2" in out and "Rotation window" in out
    assert "unrelated" not in out


def test_search_context_lines_are_capped():
    """An unbounded context_lines returned the whole archive."""
    from agno.compaction.compaction import _SEARCH_MAX_CONTEXT_LINES, _grep

    text = "\n".join(f"line {i}" for i in range(500))
    out = _grep(text, "line 250", context_lines=100_000)

    assert len(out.splitlines()) == 2 * _SEARCH_MAX_CONTEXT_LINES + 1


def test_a_long_matching_line_is_clipped_around_the_match():
    """A long line came back whole; clipped from the start, a match in the middle would be lost."""
    from agno.compaction.compaction import _SEARCH_LINE_CHARS, _grep

    out = _grep("x" * 150_000 + " SECRET-42 " + "y" * 150_000, "secret-42")

    assert "SECRET-42" in out
    assert len(out) < _SEARCH_LINE_CHARS + 50


def test_search_output_is_capped():
    """The result goes into the context window; on a small model an unbounded one overflows it."""
    from agno.compaction.compaction import _SEARCH_OUTPUT_CHARS, _grep

    text = "\n".join(f"hit {i} " + "z" * 400 for i in range(5_000))
    out = _grep(text, "hit", context_lines=0, max_matches=1_000)

    assert len(out) <= _SEARCH_OUTPUT_CHARS + 100
    assert out.endswith("narrow the search.")


def test_the_search_tool_caps_output_across_folds():
    """Each fold's result is capped; so is their sum, or five folds return five times the cap."""
    from agno.compaction.archive import CompactionArchive
    from agno.compaction.compaction import _SEARCH_OUTPUT_CHARS

    db = _db()
    archive = CompactionArchive(db, "s")
    folded = [Message(role="user", content="\n".join(f"hit {i} " + "z" * 400 for i in range(200)))]
    for _ in range(5):
        archive.write(CompactionRecord(messages_compacted=1, summary="s", first_kept_message_id="m"), folded)

    (search,) = Compaction().tools_for("s", db)
    out = search(pattern="hit", context_lines=0)

    assert len(out) <= _SEARCH_OUTPUT_CHARS + 200
    assert "narrow the search" in out


def test_grep_falls_back_to_literal_on_bad_regex():
    """The caller is a model; it may send plain text full of regex metacharacters."""
    from agno.compaction.compaction import _grep

    assert "found" in _grep("a (unclosed found", "(unclosed", context_lines=0)


def test_grep_merges_overlapping_context():
    from agno.compaction.compaction import _grep

    text = "\n".join(f"hit {i}" for i in range(5))

    out = _grep(text, "hit", context_lines=2)

    # One merged block, not five overlapping ones.
    assert "--" not in out


def _archive_with_folds(texts):
    """An archive holding one fold per text, oldest first, with distinct timestamps."""
    from agno.compaction.archive import CompactionArchive

    db = _db()
    archive = CompactionArchive(db, "s")
    for age, text in enumerate(texts):
        record = CompactionRecord(messages_compacted=1, summary="s", first_kept_message_id="m", created_at=1_000 + age)
        archive.write(record, [Message(role="user", content=text)])
    return db


def test_alternatives_reach_folds_older_than_the_newest_few():
    """With "|" in the pattern, only the newest 5 folds used to be scanned. Models search that way
    most of the time, so the earliest history - where facts are often first stated - went missing."""
    db = _archive_with_folds(["vendor 12: Hooli Ltd, phone 1444"] + [f"fold {i}: nothing here" for i in range(1, 9)])
    (search,) = Compaction().tools_for("s", db)

    assert "1444" in search(pattern="vendor 12|contact list")


def test_a_common_term_does_not_crowd_out_an_older_match():
    """A term found in every recent fold must not fill the candidate slots ahead of the fold that
    holds the other term."""
    db = _archive_with_folds(
        ["vendor 12: Hooli Ltd, phone 1444"] + [f"fold {i}: call the phone line" for i in range(1, 9)]
    )
    (search,) = Compaction().tools_for("s", db)

    assert "1444" in search(pattern="phone|vendor 12")


def test_the_prefilter_never_drops_a_matching_fold():
    """Searches are literal, so a single term goes to SQL even with regex-looking characters in it,
    and alternatives fall back to listing - either way every fold that matches is a candidate."""
    from agno.compaction.archive import CompactionArchive

    db = _db()
    archive = CompactionArchive(db, "s")
    for text in ("deployed version 1.2 to prod", "rotation window is 47 days", "nothing relevant"):
        archive.write(
            CompactionRecord(messages_compacted=1, summary="s", first_kept_message_id="m"),
            [Message(role="user", content=text)],
        )

    def texts(rows):
        return sorted(row["archived_messages"] for row in rows)

    assert len(archive.search("version 1.2")) == 1
    assert "version 1.2" in texts(archive.search("version 1.2"))[0]
    assert sum("47 days" in t or "1.2" in t for t in texts(archive.search("version 1.2|47 days"))) == 2


# --- token measurement ------------------------------------------------------


def test_supplied_context_tokens_win_over_local_estimation():
    """The caller can count the whole in-flight view once and pass that exact number."""

    class ExplodingModel:
        id = "x"

        def count_tokens(self, *args, **kwargs):
            raise AssertionError("provider count_tokens must not be called")

    c = Compaction()

    assert c._measured_tokens(_transcript(), 1234, ExplodingModel()) == 1234


def test_token_estimation_failure_is_not_fatal(monkeypatch):
    """Local counting failures must not take the run down with them."""
    import agno.utils.tokens

    monkeypatch.setattr(
        agno.utils.tokens,
        "count_tokens",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tokenizer said no")),
    )

    c = Compaction()

    assert c._measured_tokens(_transcript(), None, None) is None


def test_no_model_still_uses_local_estimate():
    c = Compaction()

    assert c._measured_tokens(_transcript(), None, None) > 0


# --- tail selection ---------------------------------------------------------


def test_uncompacted_runs_names_an_exact_position():
    """Turn-based settings resolve to an index, not to a token budget."""
    messages = _transcript(runs=4)
    user_indexes = [i for i, m in enumerate(messages) if m.role == "user"]

    assert Compaction(uncompacted_runs=1)._keep_from_index(messages) == user_indexes[-1]
    assert Compaction(uncompacted_runs=3)._keep_from_index(messages) == user_indexes[-3]


def test_tail_covering_everything_means_nothing_to_fold():
    """Returning 0 here would name a boundary at the start of the list, which reads
    downstream as a real fold and produces a ratio that collapses toward zero."""
    messages = _transcript(runs=2)

    c = Compaction(uncompacted_runs=5)

    assert c._keep_from_index(messages) is None
    assert c.boundary_for(messages) is None


# --- summarizer input -------------------------------------------------------


def test_oversized_transcripts_are_trimmed_oldest_first():
    """One summarization call cannot swallow an unbounded transcript."""
    from agno.compaction.compaction import DEFAULT_SUMMARIZE_CHAR_BUDGET

    messages = [Message(role="user", content="x" * 40_000) for _ in range(12)]

    compaction = Compaction()
    trimmed = compaction._trim_for_summary(messages)
    transcript = compaction._summary_messages(messages, previous=None)[-1].content

    assert len(trimmed) < len(messages)
    # The newest survive; the oldest are dropped.
    assert trimmed[-1] is messages[-1]
    # The budget bounds what the summarizer reads, which is each message clipped for it.
    assert len(transcript) <= DEFAULT_SUMMARIZE_CHAR_BUDGET


def test_a_single_oversized_message_still_gets_summarized():
    """Never return an empty transcript: one message over budget is still the input."""
    messages = [Message(role="user", content="x" * 500_000)]

    assert Compaction()._trim_for_summary(messages) == messages


# --- previous-record resolution ---------------------------------------------


def test_previous_boundary_resolves_by_anchor():
    messages = _transcript(runs=3)
    previous = CompactionRecord(messages_compacted=2, summary="s", first_kept_message_id=messages[3].id)

    assert Compaction._resolved_boundary(messages, previous) == 3


def test_unresolvable_previous_boundary_falls_open_to_zero():
    """Same fail-open the view takes: an anchor that does not resolve does not apply."""
    messages = _transcript(runs=3)
    stale = CompactionRecord(messages_compacted=2, summary="s", first_kept_message_id="gone")

    assert Compaction._resolved_boundary(messages, stale) == 0
    assert Compaction._resolved_boundary(messages, None) == 0


# --- archive instruction ----------------------------------------------------


def test_lookup_is_promised_only_when_the_agent_can_act_on_it():
    """Telling a model to search a store it has no tool for invites an invented answer."""
    archived = CompactionRecord(messages_compacted=2, summary="s", archived=True)
    unarchived = CompactionRecord(messages_compacted=2, summary="s", archived=False)

    assert Compaction(search_compacted_messages=True)._archive_instruction(archived)
    assert Compaction(search_compacted_messages=True)._archive_instruction(unarchived) is None
    assert Compaction(search_compacted_messages=False)._archive_instruction(archived) is None


# --- async parity -----------------------------------------------------------


@pytest.mark.asyncio
async def test_acompact_matches_compact():
    """The async path must fold the same span and anchor in the same place."""

    class _AsyncStub(_StubModel):
        async def aresponse(self, messages, **kwargs):
            return self.response(messages, **kwargs)

    messages = _transcript(runs=4)
    kwargs = dict(uncompacted_runs=1, min_fold_ratio=0)

    sync = Compaction(**kwargs, model=_AsyncStub()).compact(messages, session_id="s", db=None)
    asyn = await Compaction(**kwargs, model=_AsyncStub()).acompact(messages, session_id="s", db=None)

    assert sync is not None and asyn is not None
    assert sync.first_kept_message_id == asyn.first_kept_message_id
    assert sync.messages_compacted == asyn.messages_compacted


@pytest.mark.asyncio
async def test_acompact_declines_where_compact_declines():
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(uncompacted_runs=1, model=_StubModel())

    assert await c.acompact(tiny, session_id="s", db=None) is None


# --- reasoning-model tool calls ---------------------------------------------


def test_reasoning_item_travels_with_its_function_call():
    """A reasoning model's function_call is only valid beside its reasoning item.

    The server holds that item when a request chains on previous_response_id.
    Compaction severs that chain deliberately, so the item has to travel in the
    request or the API rejects the pair with a 400.
    """
    from agno.models.openai import OpenAIResponses

    model = OpenAIResponses(id="gpt-5.6-luna")
    messages = [
        Message(role="user", content="calc"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "fc_1", "call_id": "call_1", "function": {"name": "add", "arguments": "{}"}}],
            provider_data={"reasoning_output": {"id": "rs_1", "type": "reasoning", "summary": []}},
        ),
        Message(role="tool", tool_call_id="call_1", content="4"),
    ]

    kinds = [
        item.get("type") if isinstance(item, dict) else type(item).__name__ for item in model._format_messages(messages)
    ]

    assert "ResponseReasoningItem" in kinds
    assert kinds.index("ResponseReasoningItem") < kinds.index("function_call")


# --- events --------------------------------------------------------------


def test_compaction_events_are_registered():
    """Both events must round-trip through the run-event registry."""
    from agno.run.agent import RUN_EVENT_TYPE_REGISTRY, RunEvent

    assert RUN_EVENT_TYPE_REGISTRY[RunEvent.compaction_started.value].__name__ == "CompactionStartedEvent"
    assert RUN_EVENT_TYPE_REGISTRY[RunEvent.compaction_completed.value].__name__ == "CompactionCompletedEvent"


def test_completed_event_carries_what_happened():
    from agno.run.agent import RunOutput
    from agno.utils.events import create_compaction_completed_event

    event = create_compaction_completed_event(
        from_run_response=RunOutput(run_id="r1", session_id="s1"),
        messages_compacted=6,
        tokens_before=1000,
        tokens_after=200,
        archived=True,
    )

    assert event.messages_compacted == 6
    assert event.tokens_before == 1000
    assert event.tokens_after == 200
    assert event.archived is True


# --- archive -------------------------------------------------------------


def test_archive_roundtrip():
    """A record round-trips through the table with its transcript."""
    db = _db()
    c = Compaction()
    archive = c.archive_for("session-a", db)
    record = CompactionRecord(messages_compacted=1, summary="s", first_kept_message_id="m1", id="c1", run_id="r1")

    assert archive.write(record, [Message(role="assistant", content="policy KR-9912 applies")]) is True
    row = archive.latest()
    assert row["summary"] == "s"
    assert "KR-9912" in row["archived_messages"]


def test_archive_is_isolated_per_session():
    """One session must never be able to read another's history."""
    db = _db()
    c = Compaction()
    c.archive_for("session-a", db).write(
        CompactionRecord(messages_compacted=1, summary="s", first_kept_message_id="m1", id="c1"),
        [Message(role="assistant", content="secret KR-9912")],
    )

    assert c.archive_for("session-a", db).search("KR-9912")
    assert not c.archive_for("session-b", db).search("KR-9912")


def test_resumed_run_resolves_the_fold_that_run_saw():
    """A fork must not inherit a fold that summarizes its own future."""
    db = _db()
    c = Compaction()
    archive = c.archive_for("s", db)
    for cid, run_id, summary, at in (("c1", "r1", "early", 100), ("c2", "r3", "late", 200)):
        record = CompactionRecord(
            messages_compacted=1, summary=summary, first_kept_message_id="m1", id=cid, run_id=run_id
        )
        record.created_at = at
        archive.write(record, [Message(role="user", content="x")])

    assert archive.latest()["summary"] == "late"
    assert archive.latest("r3")["summary"] == "late"
    assert archive.latest("r1")["summary"] == "early"


def test_archive_degrades_when_db_cannot_store_records(caplog):
    """A db without the optional contract loses the archive, not the run."""

    class UnsupportedDb:
        pass

    archive = Compaction().archive_for("s", UnsupportedDb())
    with caplog.at_level(logging.WARNING, logger="agno"):
        assert archive.write(_record(_transcript(), 2), []) is False
    assert archive.latest() is None
    assert archive.search("anything") == []
    assert any("does not implement compaction records" in r.message for r in caplog.records)
    assert Compaction().archive_for("s", None) is None


def test_search_follows_the_archive_by_default():
    """Search reads the archived transcript, so unset it is on exactly when there is one. Turning the
    archive off is not a request about search, so it says nothing and raises nothing."""
    assert Compaction().search_compacted_messages is True
    assert Compaction(store_compacted_messages=False).search_compacted_messages is False


def test_asking_for_search_without_an_archive_is_rejected():
    """Two settings the user chose contradict each other; dropping one silently would leave them
    wondering where the search tool went."""
    with pytest.raises(ValueError, match="search_compacted_messages=True needs store_compacted_messages=True"):
        Compaction(store_compacted_messages=False, search_compacted_messages=True)


def test_search_can_still_be_turned_off():
    assert Compaction(search_compacted_messages=False).search_compacted_messages is False
    assert (
        Compaction(store_compacted_messages=False, search_compacted_messages=False).search_compacted_messages is False
    )


def test_a_resolved_search_setting_survives_revalidation():
    """Overflow recovery derives variants with dataclasses.replace(), which re-runs __post_init__."""
    from dataclasses import replace

    assert replace(Compaction(store_compacted_messages=False), min_fold_ratio=0).search_compacted_messages is False
    assert replace(Compaction(), min_fold_ratio=0).search_compacted_messages is True


def test_a_fold_without_an_archive_still_persists():
    """store_compacted_messages=False turns off storing the folded transcript, not storing the fold. Without the
    record the fold vanished after its own run: the next run sent the full history again, and the
    next threshold crossing summarized from scratch."""
    from agno.agent import Agent

    db = _db()
    model = _RecordingModel.build()
    agent = Agent(
        model=model,
        db=db,
        session_id="s",
        add_history_to_context=True,
        num_history_runs=20,
        compaction=Compaction(
            compact_at_tokens=None,
            uncompacted_runs=1,
            min_fold_ratio=0,
            store_compacted_messages=False,
            model=_StubModel(),
        ),
    )
    for i in range(5):
        agent.run(f"question number {i}")
    record = agent.compact(session_id="s").record

    agent.run("question number 5")
    sent = [m for m in model.requests[-1] if m.role != "system"]

    assert str(sent[0].content).startswith("Summary of earlier conversation")
    assert [m.content for m in sent if str(m.content).startswith("question")] == [
        "question number 4",
        "question number 5",
    ]
    row = db.get_compactions_for_session("s")[0]
    assert row["summary"] and row["archived_messages"] is None
    assert record.archived is False


def test_without_an_archive_there_is_nothing_to_search_or_point_to():
    """No transcript is stored, so no search tool is offered and the summarizer is not asked to
    name what it left out for a lookup the agent cannot make."""
    from agno.compaction.prompts import ARCHIVE_AWARE_PROMPT

    seen = {}

    class _Summarizer:
        id = "stub"

        def response(self, messages, **kwargs):
            from agno.models.response import ModelResponse

            seen["system"] = messages[0].content
            return ModelResponse(content="SUMMARY")

    db = _db()
    compaction = Compaction(uncompacted_runs=1, min_fold_ratio=0, store_compacted_messages=False, model=_Summarizer())
    assert compaction.compact(_transcript(4), session_id="s", db=db) is not None

    assert ARCHIVE_AWARE_PROMPT.strip() not in seen["system"]
    assert compaction.tools_for("s", db) is None


def test_render_includes_roles_and_tool_names():
    rendered = render_messages(_transcript(runs=2))
    assert "## user" in rendered
    assert "## tool (search)" in rendered
    assert "question 0" in rendered


def _span_with(large):
    """A span being folded: a fact early on, then one very large message."""
    return [
        Message(role="user", content="My budget is 4000 dollars and I fly on April 3."),
        Message(role="assistant", content="Noted: 4000 dollars, flying April 3."),
        Message(role="user", content="Search the fare database for flights."),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
        ),
        large,
        Message(role="assistant", content="Cheapest fare is 640 dollars."),
    ]


def test_a_large_tool_result_does_not_crowd_the_rest_out_of_the_summary():
    """Every folded message leaves the context, so every one must reach the summarizer. A tool
    result is sent clipped, so it must be charged at its clipped size: charged raw, one result
    larger than the whole budget used to leave the summarizer seeing 1 of 6 messages."""
    from agno.compaction.compaction import DEFAULT_SUMMARIZE_CHAR_BUDGET

    huge = Message(role="tool", tool_call_id="c1", tool_name="search", content="fare row " * 60_000)
    assert len(huge.content) > DEFAULT_SUMMARIZE_CHAR_BUDGET
    messages = _span_with(huge)
    compaction = Compaction()

    transcript = compaction._summary_messages(messages, previous=None)[-1].content

    assert len(compaction._trim_for_summary(messages)) == len(messages)
    assert "4000 dollars" in transcript
    assert len(transcript) < 30_000


def test_a_long_pasted_message_reaches_the_summarizer_in_full():
    """User and assistant messages are not clipped: within the budget, a long document is read whole."""
    pasted = Message(role="user", content="clause " * 21_000)
    messages = _span_with(pasted)
    compaction = Compaction()

    transcript = compaction._summary_messages(messages, previous=None)[-1].content

    assert len(compaction._trim_for_summary(messages)) == len(messages)
    assert pasted.content.strip() in transcript
    assert "4000 dollars" in transcript


def test_the_archive_keeps_long_messages_in_full():
    """Only the summarizer's view clips every message; the archive is the lossless record."""
    from agno.compaction.archive import render_messages

    pasted = Message(role="user", content="clause " * 21_000)

    assert len(render_messages([pasted])) > 140_000


def test_render_clips_huge_tool_results():
    """One enormous result must not be able to exhaust the archive quota."""
    from agno.compaction.archive import MAX_ARCHIVED_TOOL_RESULT_CHARS

    rendered = render_messages([Message(role="tool", tool_name="dump", content="x" * 60_000)])
    assert "clipped" in rendered
    assert len(rendered) < MAX_ARCHIVED_TOOL_RESULT_CHARS + 1000


# --- searchable tools ----------------------------------------------------


def test_searchable_exposes_read_only_tools():
    """Once something is archived, the read-only surface is attached."""
    c = Compaction(search_compacted_messages=True)
    db = _db()
    c.archive_for("s", db).write(
        CompactionRecord(messages_compacted=1, summary="s", first_kept_message_id="m1", id="c9"),
        [Message(role="user", content="something to find")],
    )

    tools = c.tools_for("s", db)

    assert [t.__name__ for t in tools] == ["search_compacted_history"]


def test_no_tools_until_something_is_archived():
    """An empty archive offers nothing - there is no history to search yet.

    Attaching the tools on turn one only invites a pointless lookup before
    any compaction has happened.
    """
    assert Compaction(search_compacted_messages=True).tools_for("s", _db()) is None


def test_searchable_tools_reach_the_agent():
    """The toolkit must actually be registered, not merely constructible.

    tools_for() existing is not enough - without it being wired into tool
    resolution the agent has no way to read its own archive, and the feature
    silently does nothing.
    """
    from agno.agent import Agent
    from agno.agent._tools import get_tools
    from agno.models.openai import OpenAIResponses
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session import AgentSession

    db = _db()
    compaction = Compaction(search_compacted_messages=True)
    compaction.archive_for("s", db).write(
        CompactionRecord(messages_compacted=1, summary="s", first_kept_message_id="m1", id="c8"),
        [Message(role="user", content="archived")],
    )
    agent = Agent(model=OpenAIResponses(id="gpt-4o-mini"), db=db, compaction=compaction)
    tools = get_tools(
        agent,
        run_response=RunOutput(run_id="r", session_id="s"),
        run_context=RunContext(run_id="r", session_id="s"),
        session=AgentSession(session_id="s"),
    )

    names = [getattr(t, "__name__", "") for t in tools]
    assert "search_compacted_history" in names


def test_archive_tools_absent_when_not_searchable():
    from agno.agent import Agent
    from agno.agent._tools import get_tools
    from agno.models.openai import OpenAIResponses
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session import AgentSession

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        db=_db(),
        compaction=Compaction(),
    )
    tools = get_tools(
        agent,
        run_response=RunOutput(run_id="r", session_id="s"),
        run_context=RunContext(run_id="r", session_id="s"),
        session=AgentSession(session_id="s"),
    )

    names = [getattr(t, "__name__", "") for t in tools]
    assert "search_compacted_history" not in names


def test_not_searchable_by_default():
    assert Compaction().tools_for("s", _db()) is None


# --- holding the summary to its budget --------------------------------------


_OVER_BUDGET = """## Goal
Ship the billing migration.

## In progress / next steps
- Canary at 5% on staging.

## Critical context
- Ticket OPS-4821, config /srv/billing/config/prod.yaml

## Constraints & preferences
- Never restart billing during business hours.

## Key decisions & facts
- Chose Postgres over MySQL for the ledger.

## Errors & fixes
- BILLING_E512 fixed by raising the pool.

## Completed
""" + "\n".join(f"- finished step {i} with detail {i * 7}" for i in range(60))


class _Verbose:
    """A summarizer that ignores its budget, as models do."""

    id = "gpt-4o"

    def __init__(self, summary):
        self.summary = summary

    def response(self, messages, **kwargs):
        from agno.models.response import ModelResponse

        self.system = messages[0].content
        return ModelResponse(content=self.summary)


def _fold(summary, **compaction_kwargs):
    compaction = Compaction(uncompacted_runs=1, min_fold_ratio=0, model=_Verbose(summary), **compaction_kwargs)
    return compaction.compact(_transcript(6), session_id="s")


def test_the_prompt_orders_sections_most_important_first():
    """The cut takes the end of the summary, so the end is where finished history goes."""
    from agno.compaction.prompts import DEFAULT_COMPACTION_PROMPT

    order = [
        "## Goal",
        "## In progress / next steps",
        "## Critical context",
        "## Constraints & preferences",
        "## Key decisions & facts",
        "## Errors & fixes",
        "## Completed",
    ]
    positions = [DEFAULT_COMPACTION_PROMPT.index(heading) for heading in order]
    assert positions == sorted(positions)


def test_no_budget_by_default_asks_for_a_compact_summary_without_a_number():
    """A model cannot count the tokens it writes, and a reasoning model spends part of any output
    cap on thinking, so no fixed number is a budget it can meet. The default names none."""
    assert Compaction().compacted_token_budget is None

    model = _Verbose("## Goal\nShip it.")
    Compaction(uncompacted_runs=1, min_fold_ratio=0, model=model).compact(_transcript(6), session_id="s")

    assert "Keep the summary compact" in model.system
    assert "length budget" not in model.system
    assert "tokens (roughly" not in model.system


def test_without_a_budget_the_summary_is_never_cut():
    record = _fold(_OVER_BUDGET)

    assert record.summary == _OVER_BUDGET


def test_without_a_budget_enforcement_has_nothing_to_hold():
    record = _fold(_OVER_BUDGET, enforce_token_budget=True)

    assert record.summary == _OVER_BUDGET


def test_the_budget_is_stated_in_tokens_words_and_characters():
    model = _Verbose("## Goal\nShip it.")
    Compaction(uncompacted_runs=1, min_fold_ratio=0, compacted_token_budget=800, model=model).compact(
        _transcript(6), session_id="s"
    )

    assert "800 tokens (roughly 600 words, 3200 characters)" in model.system


def test_an_over_budget_summary_is_cut_from_the_end_at_a_line_break():
    """A model cannot count its tokens, so the cap is held here: whole lines from the top, which the
    prompt orders most important first, and a note in place of what was cut."""
    from agno.compaction.prompts import SUMMARY_CUT_NOTE
    from agno.utils.tokens import count_text_tokens

    record = _fold(_OVER_BUDGET, compacted_token_budget=120)

    assert count_text_tokens(record.summary, "gpt-4o") <= 120
    lines = record.summary.splitlines()
    assert lines[-1] == SUMMARY_CUT_NOTE
    original = set(_OVER_BUDGET.splitlines())
    # Whole lines, then whole words of the next one: never half a word or identifier.
    *whole, partial = [line for line in lines[:-1] if line.strip()]
    assert all(line in original for line in whole)
    assert partial in original or (partial.endswith(" ...") and any(o.startswith(partial[:-4]) for o in original))
    assert "Ship the billing migration." in record.summary and "OPS-4821" in record.summary
    assert "finished step 59" not in record.summary


def test_a_cut_never_leaves_a_heading_with_nothing_under_it():
    from agno.compaction.prompts import SUMMARY_CUT_NOTE

    record = _fold(_OVER_BUDGET, compacted_token_budget=60)

    lines = [line for line in record.summary.splitlines() if line.strip()]
    assert not lines[-2].startswith("#")
    assert lines[-1] == SUMMARY_CUT_NOTE


def test_the_cut_note_points_at_search_when_the_agent_can_search():
    from agno.compaction.prompts import SUMMARY_CUT_NOTE_SEARCHABLE

    record = Compaction(
        uncompacted_runs=1, min_fold_ratio=0, compacted_token_budget=120, model=_Verbose(_OVER_BUDGET)
    ).compact(_transcript(6), session_id="s", db=_db())

    assert record.summary.endswith(SUMMARY_CUT_NOTE_SEARCHABLE)


def test_a_summary_within_budget_is_left_alone():
    record = _fold("## Goal\nShip it.", compacted_token_budget=2_000)

    assert record.summary == "## Goal\nShip it."


def test_without_enforcement_the_budget_is_only_a_target():
    record = _fold(_OVER_BUDGET, compacted_token_budget=120, enforce_token_budget=False)

    assert record.summary == _OVER_BUDGET


def test_a_long_line_fills_the_room_left_with_whole_words():
    """A paragraph-style section is one long line. Dropping it whole wasted most of the budget - found
    live, a summary kept 129 of 500 tokens - so as many of its words as fit are kept."""
    from agno.utils.tokens import count_text_tokens

    paragraph = " ".join(f"OPS-{1000 + i}," for i in range(400))
    record = _fold(f"## Goal\nShip it.\n\n## Critical context\n{paragraph}", compacted_token_budget=200)

    assert 150 <= count_text_tokens(record.summary, "gpt-4o") <= 200
    partial = [line for line in record.summary.splitlines() if line.startswith("OPS-")][0]
    assert partial.endswith(" ...")
    assert all(word.startswith("OPS-") and word[4:].rstrip(",").isdigit() for word in partial[:-4].split(" "))


def test_the_cap_holds_even_below_the_notes_own_size():
    from agno.utils.tokens import count_text_tokens

    for budget in (20, 5, 1):
        record = _fold(_OVER_BUDGET, compacted_token_budget=budget)
        assert record.summary
        assert count_text_tokens(record.summary, "gpt-4o") <= budget


def test_the_summary_budget_must_be_positive():
    with pytest.raises(ValueError, match="compacted_token_budget"):
        Compaction(compacted_token_budget=0)


# --- the newest exchange is never folded -----------------------------------


def _history_then_a_tool_loop():
    """Four answered turns, then the current question and a three-call tool loop."""
    messages = [Message(role="system", content="sys", id="s0")]
    for i in range(4):
        messages += [
            Message(role="user", content=f"old question {i} " * 40, id=f"hu{i}"),
            Message(role="assistant", content=f"old answer {i} " * 300, id=f"ha{i}"),
        ]
    messages.append(Message(role="user", content="CURRENT QUESTION", id="current"))
    for c in range(3):
        call = {"id": f"call_{c}", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
        messages.append(Message(role="assistant", content=None, tool_calls=[call], id=f"call{c}"))
        messages.append(
            Message(
                role="tool", tool_call_id=f"call_{c}", tool_name="lookup", content=f"result {c} " * 400, id=f"result{c}"
            )
        )
    return messages


def test_a_token_tail_never_cuts_inside_the_newest_exchange():
    """A token budget smaller than the newest exchange used to cut inside it. The run-count path
    never did; the token path now has the same guard."""
    messages = _history_then_a_tool_loop()
    current = next(i for i, m in enumerate(messages) if m.id == "current")

    boundary = Compaction(uncompacted_tokens=500).boundary_for(messages, min_index=1)

    assert boundary is not None and boundary <= current


@pytest.mark.parametrize("use_async", [False, True])
def test_overflow_recovery_with_a_token_tail_keeps_the_current_run(use_async):
    """Overflow recovery folds the list the current run is built from. Cutting inside the run
    dropped its question and tool results from the stored run, not just from the request."""
    import asyncio

    from agno.agent import Agent
    from agno.agent._messages import _arecompact_after_overflow, _recompact_after_overflow
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    class _AsyncStub(_StubModel):
        async def aresponse(self, messages, **kwargs):
            return self.response(messages)

    run_messages = _RunMessages(_history_then_a_tool_loop())
    agent = Agent(
        compaction=Compaction(
            uncompacted_tokens=500, on_context_overflow=True, store_compacted_messages=False, model=_AsyncStub()
        )
    )
    session = AgentSession(session_id="s", runs=[])

    if use_async:
        folded = asyncio.run(_arecompact_after_overflow(agent, session, run_messages, None))
    else:
        folded = _recompact_after_overflow(agent, session, run_messages, None)

    ids = [m.id for m in run_messages.messages]
    assert folded  # the history in front of the current run still folds
    assert "current" in ids
    assert [i for i in ids if str(i).startswith("result")] == ["result0", "result1", "result2"]
