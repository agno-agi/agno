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


def test_replay_window_at_or_below_the_tail_is_rejected():
    """keep_last_runs is the part of num_history_runs kept verbatim, so it must be smaller.

    Equal or larger leaves nothing in front of the tail to fold, and the boundary anchor could
    never be found again - every summary would be dropped on the next run. Raised at
    construction rather than widened silently: ignoring a number the user set is worse than the
    misconfiguration it works around.
    """
    from agno.agent import Agent

    for window, keep in ((3, 5), (5, 5)):
        with pytest.raises(ValueError, match="must be less than num_history_runs"):
            Agent(num_history_runs=window, compaction=Compaction(keep_last_runs=keep))


def test_defaults_do_not_collide():
    """The two defaults have to satisfy the rule the validation enforces.

    keep_last_runs defaulted to 5 against Agent's own num_history_runs default of 3, so the
    one-flag setup could never fold - and once the collision raises, it could not even be
    constructed.
    """
    from agno.agent import Agent

    agent = Agent(compaction=Compaction())

    assert agent.compaction.keep_last_runs < agent.num_history_runs


def test_a_copied_agent_is_not_validated_as_if_the_user_chose_the_default(caplog):
    """deep_copy rebuilds from fields, so num_history_runs always arrives looking explicit.

    AgentOS copies an agent per request, so a framework default validated as a user choice
    would fail every route rather than just an odd configuration.
    """
    from agno.agent import Agent

    with caplog.at_level(logging.WARNING, logger="agno"):
        copy = Agent(compaction=Compaction()).deep_copy()

    assert copy is not None
    assert not [r for r in caplog.records if "keep_last_runs" in r.message]


def test_a_barely_foldable_window_warns_rather_than_raising(caplog):
    """Passing the check is not the same as compacting usefully.

    With a finite window the foldable share is fixed at (window - keep) / window however long
    the session runs - four runs out of ten rarely pay for a summary. Legal, so it warns
    rather than raising.
    """
    from agno.agent import Agent

    with caplog.at_level(logging.WARNING, logger="agno"):
        Agent(num_history_runs=10, compaction=Compaction(keep_last_runs=6))

    assert any("rarely pay for the summary" in r.message for r in caplog.records)


def test_workable_replay_window_is_not_warned_about(caplog):
    """A window larger than the tail is a normal configuration, not a mistake."""
    from agno.agent import Agent, _init

    agent = Agent(num_history_runs=20, compaction=Compaction(keep_last_runs=5))
    with caplog.at_level(logging.WARNING, logger="agno"):
        _init.set_compaction(agent)

    assert not [r for r in caplog.records if "keep_last_runs" in r.message]


def test_defaults_the_user_did_not_choose_are_not_warned_about(caplog):
    """compaction=True collides two framework defaults - that is not the user's mistake."""
    from agno.agent import Agent, _init

    agent = Agent(compaction=True)
    with caplog.at_level(logging.WARNING, logger="agno"):
        _init.set_compaction(agent)

    assert not [r for r in caplog.records if "keep_last_runs" in r.message]


def test_compaction_is_not_starved_by_the_default_history_window():
    """num_history_runs defaults to 3, which would leave compaction nothing to fold.

    Compaction folds what sits in FRONT of the kept tail. A 3-run window with keep_last_runs=5
    has no front, so compaction could never fire under the one-flag setup - and an anchor
    outside the window cannot resolve, dropping the summary along with the turns it replaced.
    """
    from agno.agent import Agent
    from agno.agent._messages import _compaction_history_runs

    agent = Agent(compaction=Compaction(keep_last_runs=5))

    assert agent.num_history_runs == 3  # the replay default is unchanged
    assert _compaction_history_runs(agent) > 5  # but the planner sees past it


def test_an_explicit_history_window_is_used_verbatim():
    """A workable explicit window is the user's decision and is not second-guessed.

    The window that could strand an anchor is rejected at construction, so anything reaching
    the planner is already usable as given.
    """
    from agno.agent import Agent
    from agno.agent._messages import _compaction_history_runs

    agent = Agent(num_history_runs=20, compaction=Compaction(keep_last_runs=5))

    assert _compaction_history_runs(agent) == 20


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
    compaction = Compaction(compact_at_tokens=10_000_000, keep_last_runs=3, archive=False, model=_StubModel())
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
    compaction = Compaction(keep_last_runs=2, archive=False, model=_StubModel())
    agent = Agent(compaction=compaction)

    result = compact_now(agent, AgentSession(session_id="s1", runs=[]), history)

    assert not result.compacted
    assert result.record is None
    assert result.status is CompactionStatus.NOT_WORTH_IT
    assert "min_fold_tokens" in result.message


def test_not_worth_it_message_carries_the_numbers():
    """The verdict alone is not actionable.

    "not worth it" with no figures leaves a caller unable to tell a fold that missed by a hair
    from one that was never close, and the token count is what says whether waiting will help.
    """
    from agno.agent import Agent
    from agno.agent._messages import compact_now
    from agno.session.agent import AgentSession

    # Short turns, so the foldable span stays well under the default min_fold_tokens.
    history = [
        m
        for i in range(4)
        for m in (
            Message(role="user", content="q " * 15, id=f"u{i}"),
            Message(role="assistant", content="a " * 30, id=f"a{i}"),
        )
    ]
    agent = Agent(compaction=Compaction(keep_last_runs=2, archive=False, model=_StubModel()))

    result = compact_now(agent, AgentSession(session_id="s1", runs=[]), history)

    assert result.status is CompactionStatus.NOT_WORTH_IT
    assert "tokens" in result.message
    assert "min_fold_tokens" in result.message
    # The usual fix is more conversation, so it is named before the knob to lower.
    assert result.message.index("Continue") < result.message.index("lower min_fold_tokens")


def test_compaction_result_serializes_for_an_api():
    """The route returns result.to_dict() verbatim, so this IS the API contract."""
    from agno.compaction.types import CompactionResult, CompactionStatus

    declined = CompactionResult(status=CompactionStatus.NOT_WORTH_IT, message="too small").to_dict()

    assert declined == {
        "status": "not_worth_it",
        "message": "too small",
        "compacted": False,
        "record": None,
    }


def test_declines_are_reported_not_raised():
    """A decline is a normal outcome an API returns 200 for, with a reason to display.

    Raising would make a legitimate "folding would not help here" indistinguishable from a
    failure, and force every caller to catch it.
    """
    from agno.agent import Agent
    from agno.agent._messages import compact_now
    from agno.session.agent import AgentSession

    agent = Agent(compaction=Compaction(keep_last_runs=2, archive=False, model=_StubModel()))
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


def test_context_overflow_folds_and_asks_for_a_retry():
    """The provider's rejection is the only authoritative signal that a threshold was wrong.

    No provider exposes its context window, and the same model id differs across deployments,
    so compact_at_tokens is always a guess. This path folds against the messages actually sent -
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
    agent = Agent(compaction=Compaction(keep_last_runs=5, archive=False, model=_StubModel()))

    assert _recompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None) is True
    # The payload is replaced in place, so the retry sends the smaller list.
    assert estimate_tokens(run_messages.messages) < before


def test_overflow_retry_sends_the_compacted_payload():
    """The retry has to reach the provider, not just the helper's own variable.

    The model call already holds the message list object in its kwargs, so rebinding
    run_messages.messages to a new list leaves the retry sending exactly the payload that was
    just rejected - two identical failures instead of a recovery. Asserted on what the model
    received, because asserting on the helper's attribute passes either way.
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

    call_model_with_fallback(_Model(), None, on_context_overflow=_fold, messages=messages)

    assert len(received) == 2
    assert received[1] < received[0]


def test_a_valid_agent_can_always_be_copied():
    """deep_copy must not reject a configuration that constructed successfully.

    A defaulted history window is not the user's choice, so the copy has to be told that -
    restoring the flag after construction is too late, because __init__ has already validated.
    AgentOS copies an agent per request, so this would fail every route.
    """
    from agno.agent import Agent

    for compaction in (Compaction(), Compaction(keep_last_runs=5)):
        agent = Agent(compaction=compaction)
        copy = agent.deep_copy()
        assert copy._num_history_runs_defaulted is True

    explicit = Agent(num_history_runs=20, compaction=Compaction(keep_last_runs=5)).deep_copy()
    assert explicit.num_history_runs == 20
    assert explicit._num_history_runs_defaulted is False


def test_context_overflow_gives_up_the_tail_when_the_tail_is_the_problem(caplog):
    """keep_last_runs is a promise about ordinary runs, not a reason to let this one die.

    An oversized turn INSIDE the kept tail cannot be reached by any cut in front of it, so
    honouring the setting here means folding a few hundred tokens and failing again. The tail
    is given up one run at a time, and only when the fold in front of it is too small to help.
    """
    from agno.agent import Agent
    from agno.agent._messages import _recompact_after_overflow
    from agno.compaction._tokens import estimate_tokens
    from agno.session.agent import AgentSession

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    # 3 runs with keep_last_runs=3: the tail covers everything, and run 2 is enormous.
    messages = [Message(role="system", content="sys", id="s0")]
    for i in range(3):
        messages.append(Message(role="user", content=f"q{i} " * 20, id=f"u{i}"))
        messages.append(Message(role="assistant", content=("f " * 40000 if i == 1 else f"a{i} " * 100), id=f"a{i}"))
    run_messages = _RunMessages(messages)
    before = estimate_tokens(messages)
    agent = Agent(compaction=Compaction(keep_last_runs=3, archive=False, model=_StubModel()))

    with caplog.at_level(logging.INFO, logger="agno"):
        assert _recompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None) is True

    assert estimate_tokens(run_messages.messages) < before / 10
    assert any("keeping 1 run(s) instead of 3" in r.message for r in caplog.records)


def test_context_overflow_keeps_the_configured_tail_when_it_works(caplog):
    """Giving up the tail is a last resort, not the overflow path's default.

    A long session where folding in front of the tail already reclaims plenty must keep the
    runs the user asked for - the rejection says the request was too big, not that the setting
    was wrong.
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
    agent = Agent(compaction=Compaction(keep_last_runs=5, archive=False, model=_StubModel()))

    with caplog.at_level(logging.INFO, logger="agno"):
        assert _recompact_after_overflow(agent, AgentSession(session_id="s1", runs=[]), run_messages, None) is True

    assert estimate_tokens(run_messages.messages) < before
    assert not [r for r in caplog.records if "run(s) instead of" in r.message]


def test_context_overflow_does_not_retry_what_it_cannot_shrink(caplog):
    """Retrying an identical payload just fails twice.

    When the most recent turn alone exceeds the window there is no safe cut left, and the
    caller needs to hear why rather than watch a silent second failure.
    """
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
    agent = Agent(compaction=Compaction(keep_last_runs=1, archive=False, model=_StubModel()))

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


def test_a_repeat_fold_measures_against_what_the_model_was_sent():
    """tokens_before is the view in flight, not the raw stored history.

    On a repeat fold those differ by everything the previous fold already replaced, so raw
    history overstates the saving - and _fold_paid_off would be comparing a number the provider
    never saw against one it will. The row is written once and never updated, so a wrong value
    here is permanent.
    """
    from agno.compaction._tokens import estimate_tokens
    from agno.models.response import ModelResponse

    class _Summarizer:
        id = "stub"

        def response(self, messages, **kwargs):
            return ModelResponse(content="summary " * 400)

    messages = [
        m
        for i in range(12)
        for m in (
            Message(role="user", content=f"q{i} " * 20, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 300, id=f"a{i}"),
        )
    ]
    c = Compaction(keep_last_runs=2, archive=False, model=_Summarizer())

    first = c.compact(messages, session_id="s", db=None)
    assert first is not None

    # Grow the conversation so a second fold has a new boundary to cut at.
    messages += [
        m
        for i in range(12, 20)
        for m in (
            Message(role="user", content=f"q{i} " * 20, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 300, id=f"a{i}"),
        )
    ]
    in_flight = estimate_tokens(c.apply_record(messages, first))

    second = c.compact(messages, session_id="s", db=None, previous=first)

    assert second is not None
    assert second.tokens_before == in_flight
    assert second.tokens_after == estimate_tokens(c.apply_record(messages, second))


def test_a_fold_that_grows_the_context_is_discarded(caplog):
    """min_fold_tokens bounds the input; only this check sees the outcome.

    The summarizer is asked to reproduce identifiers verbatim, so on a span that is mostly raw
    data the summary can come back larger than what it replaces. Accepting that grows the
    context while reporting a compaction - the one thing the guard exists to prevent.
    """
    from agno.compaction._tokens import estimate_tokens
    from agno.models.response import ModelResponse

    class _FatSummarizer:
        id = "stub"

        def response(self, messages, **kwargs):
            return ModelResponse(content="verbose summary text " * 2000)

    messages = [
        m
        for i in range(8)
        for m in (
            Message(role="user", content=f"q{i} " * 20, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 300, id=f"a{i}"),
        )
    ]
    before = estimate_tokens(messages)
    c = Compaction(keep_last_runs=2, archive=False, model=_FatSummarizer())

    with caplog.at_level(logging.WARNING, logger="agno"):
        assert c.compact(messages, session_id="s", db=None) is None

    assert estimate_tokens(messages) == before
    assert any("came back larger" in r.message for r in caplog.records)


def test_a_fold_that_shrinks_the_context_is_kept():
    """The outcome check must not reject folds that work."""
    from agno.compaction._tokens import estimate_tokens
    from agno.models.response import ModelResponse

    class _ThinSummarizer:
        id = "stub"

        def response(self, messages, **kwargs):
            return ModelResponse(content="short summary")

    messages = [
        m
        for i in range(8)
        for m in (
            Message(role="user", content=f"q{i} " * 20, id=f"u{i}"),
            Message(role="assistant", content=f"a{i} " * 300, id=f"a{i}"),
        )
    ]
    c = Compaction(keep_last_runs=2, archive=False, model=_ThinSummarizer())

    record = c.compact(messages, session_id="s", db=None)

    assert record is not None
    assert estimate_tokens(c.apply_record(messages, record)) < estimate_tokens(messages)


def test_the_pending_input_counts_toward_the_threshold():
    """Compaction runs before the user message is built, so it would otherwise be invisible.

    Fine for a one-line question, wrong when someone pastes a document - which is exactly when
    the request overflows and the trigger most needs to see it coming.
    """
    from agno.agent import Agent
    from agno.agent._messages import _estimated_context_tokens, _input_preview

    agent = Agent()
    history = [
        m
        for i in range(5)
        for m in (
            Message(role="user", content=f"q{i} " * 20),
            Message(role="assistant", content=f"a{i} " * 200),
        )
    ]
    pasted = "Here is a document: " + "word " * 4000

    measured = _estimated_context_tokens(agent, history + _input_preview(pasted))
    actually_sent = _estimated_context_tokens(agent, history + [Message(role="user", content=pasted)])

    assert measured == actually_sent
    assert measured > _estimated_context_tokens(agent, history) * 2


# --- boundary safety -----------------------------------------------------


def test_boundary_never_splits_a_tool_batch():
    """The kept tail must never begin with an unanswered tool result."""
    messages = _transcript(runs=3)
    for keep in range(len(messages) + 1):
        c = Compaction(keep_last_runs=keep)
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
    c = Compaction(keep_last_runs=1)
    tail = messages[c.boundary_for(messages) :]
    assert tail[0].role == "user"
    assert tail[0].content == "question 2"


def test_keeping_everything_compacts_nothing():
    """No safe cut is None, not 0: there is nothing to fold, so the pass aborts."""
    messages = _transcript(runs=2)
    c = Compaction(keep_last_runs=99)
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

    searchable = Compaction(searchable=True).apply_record(messages, archived)[0]
    not_searchable = Compaction().apply_record(messages, archived)[0]
    no_archive = Compaction(searchable=True).apply_record(messages, _record(messages, 3, summary="s"))[0]

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
    # min_fold_tokens=0: this exercises the boundary, not the size floor.
    c = Compaction(keep_last_runs=1, min_fold_tokens=0, model=_StubModel())
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
    c = Compaction(keep_last_runs=1)
    boundary = c.boundary_for(messages)
    previous = _record(messages, boundary, summary="s")

    assert c.compact(messages, session_id="s", db=None, previous=previous) is None


def test_skips_a_fold_that_cannot_pay_for_its_summary():
    """Folding barely more than is kept leaves the context bigger, not smaller."""
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(keep_last_runs=1, model=_StubModel())

    assert c.compact(tiny, session_id="s", db=None) is None


def test_the_size_floor_can_be_disabled():
    """min_fold_tokens=0 folds spans the floor would decline.

    The outcome check still applies - it is about whether the summary actually shrank the
    context, not about how large the input was - so this span is big enough to shrink.
    """
    messages = [
        Message(role="user", content="word " * 200),
        Message(role="assistant", content="text " * 200),
        Message(role="user", content="more"),
    ]
    c = Compaction(keep_last_runs=1, min_fold_tokens=0, model=_StubModel())

    assert c.compact(messages, session_id="s", db=None) is not None


def test_large_fold_clears_the_size_floor():
    big = [
        Message(role="user", content="word " * 1_500),
        Message(role="assistant", content="text " * 1_500),
        Message(role="user", content="tiny"),
    ]
    c = Compaction(keep_last_runs=1, model=_StubModel())

    assert c.compact(big, session_id="s", db=None) is not None


def test_plan_refuses_what_compact_would_refuse():
    """plan() is what callers announce on, so it must agree with compact().

    should_compact() alone cannot see the pair-safe boundary or the size
    floor, so announcing on it logs "Auto-compacting" and emits
    CompactionStarted for compactions that then never happen.
    """
    # Too small to be worth folding: whatever boundary exists, both must decline together.
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(keep_last_runs=1, model=_StubModel())

    assert c.plan(tiny) is None
    assert c.compact(tiny, session_id="s", db=None) is None


def test_plan_agrees_with_compact_when_worthwhile():
    big = [
        Message(role="user", content="word " * 1_500),
        Message(role="assistant", content="text " * 1_500),
        Message(role="user", content="tiny"),
    ]
    c = Compaction(keep_last_runs=1, model=_StubModel())

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


def test_tool_results_before_the_watermark_are_elided():
    """Elision reclaims bulk tool output without paying a summarizer for it."""
    from agno.compaction.prompts import ELISION_PLACEHOLDER

    messages = [
        Message(role="user", content="q0"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "c1", "function": {"name": "dump", "arguments": "{}"}}],
        ),
        Message(role="tool", tool_call_id="c1", tool_name="dump", content="x" * 5_000),
        Message(role="user", content="q1"),
    ]
    record = CompactionRecord(messages_compacted=0, summary="", elision_watermark_message_id=messages[3].id)

    view = Compaction().apply_record(messages, record)

    elided = next(m for m in view if m.role == "tool")
    assert elided.content == ELISION_PLACEHOLDER.format(n_chars=5_000)
    # The transcript keeps the real payload.
    assert messages[2].content == "x" * 5_000


def test_boundary_never_anchors_on_a_message_that_will_not_persist():
    """A temporary message is gone by the next run; anchoring there would break."""
    messages = [
        Message(role="user", content="q0" * 400),
        Message(role="assistant", content="a0" * 400),
        Message(role="user", content="temp", temporary=True),
        Message(role="assistant", content="a1" * 400),
        Message(role="user", content="q2"),
    ]

    boundary = Compaction(keep_last_runs=1).boundary_for(messages)

    assert boundary is None or not messages[boundary].temporary


def test_envelopes_do_not_count_against_the_size_floor():
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
    folded = [Message(role="user", content="q " * 1_500), Message(role="assistant", content="a " * 1_500)]
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
    from agno.compaction.manager import _grep

    text = "alpha\nbeta\nINC-42 here\ndelta\nepsilon"

    out = _grep(text, "INC-42", context_lines=1)

    assert "3: INC-42 here" in out
    assert "2: beta" in out
    assert "4: delta" in out
    assert "1: alpha" not in out


def test_grep_supports_regex():
    from agno.compaction.manager import _grep

    text = "port 5432 open\nno numbers here"

    assert "5432" in _grep(text, r"port \d+", context_lines=0)
    assert _grep(text, r"port \d+", context_lines=0).count("\n") == 0


def test_grep_falls_back_to_literal_on_bad_regex():
    """The caller is a model; it may send plain text full of regex metacharacters."""
    from agno.compaction.manager import _grep

    assert "found" in _grep("a (unclosed found", "(unclosed", context_lines=0)


def test_grep_merges_overlapping_context():
    from agno.compaction.manager import _grep

    text = "\n".join(f"hit {i}" for i in range(5))

    out = _grep(text, "hit", context_lines=2)

    # One merged block, not five overlapping ones.
    assert "--" not in out


def test_regex_patterns_skip_the_sql_prefilter():
    """A regex is not a valid ILIKE string; prefiltering on it would drop real matches."""
    from agno.compaction.archive import _is_plain_text

    assert _is_plain_text("INC-88213") is True
    assert _is_plain_text(r"INC-\d+") is False


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


def test_keep_last_runs_names_an_exact_position():
    """Turn-based settings resolve to an index, not to a token budget."""
    messages = _transcript(runs=4)
    user_indexes = [i for i, m in enumerate(messages) if m.role == "user"]

    assert Compaction(keep_last_runs=1)._keep_from_index(messages) == user_indexes[-1]
    assert Compaction(keep_last_runs=3)._keep_from_index(messages) == user_indexes[-3]


def test_tail_covering_everything_means_nothing_to_fold():
    """Returning 0 here would name a boundary at the start of the list, which reads
    downstream as a real fold and produces a ratio that collapses toward zero."""
    messages = _transcript(runs=2)

    c = Compaction(keep_last_runs=5)

    assert c._keep_from_index(messages) is None
    assert c.boundary_for(messages) is None


# --- summarizer input -------------------------------------------------------


def test_oversized_transcripts_are_trimmed_oldest_first():
    """One summarization call cannot swallow an unbounded transcript."""
    from agno.compaction.manager import DEFAULT_SUMMARIZE_CHAR_BUDGET

    messages = [Message(role="user", content="x" * 40_000) for _ in range(6)]

    trimmed = Compaction()._trim_for_summary(messages)

    assert len(trimmed) < len(messages)
    # The newest survive; the oldest are dropped.
    assert trimmed[-1] is messages[-1]
    assert sum(len(m.get_content_string()) for m in trimmed) <= DEFAULT_SUMMARIZE_CHAR_BUDGET + 40_000


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

    assert Compaction(searchable=True)._archive_instruction(archived)
    assert Compaction(searchable=True)._archive_instruction(unarchived) is None
    assert Compaction()._archive_instruction(archived) is None


# --- async parity -----------------------------------------------------------


@pytest.mark.asyncio
async def test_acompact_matches_compact():
    """The async path must fold the same span and anchor in the same place."""

    class _AsyncStub(_StubModel):
        async def aresponse(self, messages, **kwargs):
            return self.response(messages, **kwargs)

    messages = _transcript(runs=4)
    kwargs = dict(keep_last_runs=1, min_fold_tokens=0)

    sync = Compaction(**kwargs, model=_AsyncStub()).compact(messages, session_id="s", db=None)
    asyn = await Compaction(**kwargs, model=_AsyncStub()).acompact(messages, session_id="s", db=None)

    assert sync is not None and asyn is not None
    assert sync.first_kept_message_id == asyn.first_kept_message_id
    assert sync.messages_compacted == asyn.messages_compacted


@pytest.mark.asyncio
async def test_acompact_declines_where_compact_declines():
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(keep_last_runs=1, model=_StubModel())

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


def test_archive_degrades_when_db_cannot_store_records():
    """A db without the optional contract loses the archive, not the run."""

    class UnsupportedDb:
        pass

    assert Compaction().archive_for("s", UnsupportedDb()) is None
    assert Compaction().archive_for("s", None) is None


def test_archive_off_returns_no_store():
    assert Compaction(archive=False).archive_for("s", _db()) is None


def test_render_includes_roles_and_tool_names():
    rendered = render_messages(_transcript(runs=2))
    assert "## user" in rendered
    assert "## tool (search)" in rendered
    assert "question 0" in rendered


def test_render_clips_huge_tool_results():
    """One enormous result must not be able to exhaust the archive quota."""
    from agno.compaction.archive import MAX_ARCHIVED_TOOL_RESULT_CHARS

    rendered = render_messages([Message(role="tool", tool_name="dump", content="x" * 60_000)])
    assert "clipped" in rendered
    assert len(rendered) < MAX_ARCHIVED_TOOL_RESULT_CHARS + 1000


# --- searchable tools ----------------------------------------------------


def test_searchable_exposes_read_only_tools():
    """Once something is archived, the read-only surface is attached."""
    c = Compaction(searchable=True)
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
    assert Compaction(searchable=True).tools_for("s", _db()) is None


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
    compaction = Compaction(searchable=True)
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
