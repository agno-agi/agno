"""After a fold the conversation is continued from the folded state, and a fold larger than one
summarizer call is read in parts."""

import asyncio

import pytest

from agno.compaction import Compaction, CompactionRecord
from agno.compaction.compaction import DEFAULT_SUMMARIZE_CHAR_BUDGET
from agno.compaction.prompts import SUMMARY_PREFIX
from agno.exceptions import ContextWindowExceededError, ModelProviderError
from agno.models.message import Message
from agno.models.response import ModelResponse

FOLD_AT = 1_000


def _reply(text, response_id, at, key="response_id"):
    return Message(role="assistant", content=text, provider_data={key: response_id, "other": "kept"}, created_at=at)


def _conversation(key="response_id"):
    """Two turns before the fold, the turn that made the fold, and one turn after it."""
    return [
        Message(role="user", content="q0", created_at=FOLD_AT - 30),
        _reply("a0", "old_0", FOLD_AT - 29, key),
        Message(role="user", content="q1", created_at=FOLD_AT - 20),
        _reply("a1", "old_1", FOLD_AT - 19, key),
        Message(role="user", content="q2", created_at=FOLD_AT),
        _reply("a2", "new_2", FOLD_AT + 4, key),
        Message(role="user", content="q3", created_at=FOLD_AT + 60),
        _reply("a3", "new_3", FOLD_AT + 61, key),
    ]


def _fold(messages, kept_from, at=FOLD_AT):
    return CompactionRecord(
        messages_compacted=kept_from, summary="SUMMARY", first_kept_message_id=messages[kept_from].id, created_at=at
    )


def _ids(view, key="response_id"):
    return [(m.content, (m.provider_data or {}).get(key)) for m in view if m.role == "assistant"]


# ----------------------------------------------------------------- the view


@pytest.mark.parametrize("key", ["response_id", "interaction_id"])
def test_replies_made_after_the_fold_keep_what_the_provider_continues_from(key):
    """The reply kept from before the fold must not be continued from: the provider's conversation
    behind it holds the folded turns. The replies made from the fold are safe to continue from."""
    messages = _conversation(key)

    view = Compaction().apply_record(messages, _fold(messages, kept_from=2))

    assert view[0].content.startswith(SUMMARY_PREFIX)
    assert _ids(view, key) == [("a1", None), ("a2", "new_2"), ("a3", "new_3")]
    # Nothing else is taken off the old reply, and the stored messages are untouched.
    assert view[2].provider_data == {"other": "kept"}
    assert messages[3].provider_data[key] == "old_1"


def test_a_reply_stamped_in_the_same_second_as_the_fold_counts_as_made_before_it():
    """It cannot be told apart from a reply the fold kept. Sending one request in full is the
    cheap mistake; continuing from a reply made before the fold would bring the folded turns back."""
    messages = _conversation()
    messages[5] = _reply("a2", "new_2", FOLD_AT)

    view = Compaction().apply_record(messages, _fold(messages, kept_from=2))

    assert _ids(view) == [("a1", None), ("a2", None), ("a3", "new_3")]


def test_a_second_fold_cuts_the_chain_again():
    """The replies made between two folds were continued from the first fold. Once a second fold
    replaces part of that conversation, they are replies from before a fold like any other."""
    messages = _conversation()
    messages += [Message(role="user", content="q4", created_at=FOLD_AT + 500), _reply("a4", "newer_4", FOLD_AT + 505)]

    view = Compaction().apply_record(messages, _fold(messages, kept_from=6, at=FOLD_AT + 500))

    assert _ids(view) == [("a3", None), ("a4", "newer_4")]


def test_with_no_fold_in_force_every_reply_loses_it_as_before():
    """A record whose first kept message is gone applies no cut: the whole list is sent, in full."""
    messages = _conversation()
    record = CompactionRecord(messages_compacted=2, summary="S", first_kept_message_id="gone", created_at=FOLD_AT)

    view = Compaction().apply_record(messages, record)

    assert len(view) == len(messages)
    assert all(response_id is None for _, response_id in _ids(view))


def test_a_reply_or_a_record_with_no_time_is_never_continued_from():
    messages = _conversation()
    messages[5] = Message(role="assistant", content="a2", provider_data={"response_id": "new_2"}, created_at=0)

    assert _ids(Compaction().apply_record(messages, _fold(messages, kept_from=2)))[1] == ("a2", None)
    assert all(rid is None for _, rid in _ids(Compaction().apply_record(messages, _fold(messages, 2, at=0))))


# ----------------------------------------------------------------- what OpenAI is sent


def _openai_request(view):
    from agno.models.openai import OpenAIResponses

    model = OpenAIResponses(id="gpt-6.1-terra", api_key="test")
    return model.get_request_params(messages=view), model._format_messages(view)


def test_the_turn_that_folds_is_sent_in_full_and_the_next_turn_continues_from_it():
    messages = _conversation()
    record = _fold(messages, kept_from=2)

    # The turn that made the fold: its own reply does not exist yet.
    params, sent = _openai_request(Compaction().apply_record(messages[:5], record))
    assert "previous_response_id" not in params
    assert [item["content"] for item in sent if item.get("role") == "user"][0].startswith(SUMMARY_PREFIX)
    assert len(sent) == 4  # the summary, the kept turn, the person's message

    # The next turn: continued from the reply made from the fold, so only the new message is sent.
    params, sent = _openai_request(Compaction().apply_record(messages[:7], record))
    assert params["previous_response_id"] == "new_2"
    assert [item["content"] for item in sent] == ["q3"]


# ----------------------------------------------------------------- when the fold is stamped


class _Clock:
    """Stands in for the wall clock: the summary takes five seconds to write."""

    def __init__(self):
        self.now = 5_000

    def __call__(self):
        return self.now


class _Summarizer:
    id = "summarizer"

    def __init__(self, clock=None, fail_on=None):
        self.clock, self.fail_on, self.asked = clock, fail_on, []

    def response(self, messages, **kwargs):
        self.asked.append(messages[-1].content)
        if self.clock is not None:
            self.clock.now += 5
        if self.fail_on == len(self.asked):
            return ModelResponse(content="")
        return ModelResponse(content=f"SUMMARY {len(self.asked)}")

    async def aresponse(self, messages, **kwargs):
        return self.response(messages)


def _turns(count, size=20):
    messages = []
    for i in range(count):
        messages += [Message(role="user", content=f"q{i} " + "x" * size), Message(role="assistant", content=f"a{i}")]
    return messages


@pytest.mark.parametrize("use_async", [False, True])
def test_a_fold_is_stamped_with_when_it_started_not_when_its_summary_was_done(monkeypatch, use_async):
    """The reply made from the fold starts right after the summary is written. Stamped then, the
    record would share its second and the reply would be taken for one made before the fold."""
    from agno.compaction import compaction as module

    clock = _Clock()
    monkeypatch.setattr(module, "time", clock)
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=_Summarizer(clock))
    messages = _turns(4)

    if use_async:
        record = asyncio.run(compaction.acompact(messages, session_id="s"))
    else:
        record = compaction.compact(messages, session_id="s")

    assert record.created_at == 5_000 and clock.now == 5_005


# ----------------------------------------------------------------- a fold larger than one call reads


@pytest.mark.parametrize("use_async", [False, True])
def test_a_fold_larger_than_one_summarizer_call_is_read_in_parts_oldest_first(use_async):
    """Read from its newest end only, the older turns of a large fold left the context without
    reaching any summary."""
    summarizer = _Summarizer()
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=summarizer)
    messages = _turns(13, size=80_000)
    assert sum(len(m.content) for m in messages[:-2]) > 2 * DEFAULT_SUMMARIZE_CHAR_BUDGET

    if use_async:
        record = asyncio.run(compaction.acompact(messages, session_id="s"))
    else:
        record = compaction.compact(messages, session_id="s")

    assert len(summarizer.asked) == 3 and record.summary == "SUMMARY 3"
    # Every folded turn was read once, in order, and no call was given more than the budget.
    read = "".join(summarizer.asked)
    assert [read.count(f"q{i} x") for i in range(13)] == [1] * 12 + [0]
    assert read.index("q0 x") < read.index("q5 x") < read.index("q11 x")
    assert all(len(asked) <= DEFAULT_SUMMARIZE_CHAR_BUDGET + 200 for asked in summarizer.asked)
    # Each part is folded into the summary of the parts before it.
    assert "Summary of the conversation before this point:\nSUMMARY 1" in summarizer.asked[1]
    assert "Summary of the conversation before this point:\nSUMMARY 2" in summarizer.asked[2]
    assert record.messages_compacted == 24


def test_a_fold_that_fits_is_one_call_as_before():
    summarizer = _Summarizer()
    record = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=summarizer).compact(_turns(6), session_id="s")

    assert len(summarizer.asked) == 1 and record.summary == "SUMMARY 1"


def test_one_message_larger_than_the_budget_is_a_part_of_its_own():
    summarizer = _Summarizer()
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=summarizer)
    messages = _turns(3)
    messages[2] = Message(role="user", content="pasted " + "y" * (DEFAULT_SUMMARIZE_CHAR_BUDGET + 50_000))

    compaction.compact(messages, session_id="s")

    assert len(summarizer.asked) == 3
    assert "q0 x" in summarizer.asked[0] and "pasted y" in summarizer.asked[1] and "a1" in summarizer.asked[2]


@pytest.mark.parametrize("use_async", [False, True])
def test_a_part_that_gets_no_summary_leaves_the_history_as_it_is(use_async):
    """Carrying on would fold the turns of that part away with nothing standing in for them."""
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=_Summarizer(fail_on=2))
    messages = _turns(13, size=80_000)

    if use_async:
        record = asyncio.run(compaction.acompact(messages, session_id="s"))
    else:
        record = compaction.compact(messages, session_id="s")

    assert record is None


@pytest.mark.parametrize("use_async", [False, True])
def test_a_message_that_cannot_be_rendered_leaves_the_history_as_it_is(use_async):
    """Splitting the fold renders every message. A message that cannot be rendered - raw bytes in
    a provider content block - must not fail the run: the fold is given up, as when the summarizer
    call fails."""
    summarizer = _Summarizer()
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=summarizer)
    messages = _turns(4)
    messages[2] = Message(role="user", content=[{"image": {"format": "png", "source": {"bytes": b"\x89PNG"}}}])

    if use_async:
        record = asyncio.run(compaction.acompact(messages, session_id="s"))
    else:
        record = compaction.compact(messages, session_id="s")

    assert record is None and summarizer.asked == []


# ----------------------------------------------------------------- a part the summarizer cannot read


class _SmallWindowSummarizer(_Summarizer):
    """Rejects a transcript longer than its window, as a provider rejects one with too many tokens.

    A part is sized in characters and a provider counts tokens, so a part within the budget can
    still be more than the summarizer reads. ``asked`` holds only the transcripts it accepted."""

    def __init__(self, window, error=None):
        super().__init__()
        self.window, self.error, self.rejected = window, error, 0

    def response(self, messages, **kwargs):
        if len(messages[-1].content) > self.window:
            self.rejected += 1
            raise self.error or ContextWindowExceededError("This model's maximum context length was exceeded")
        return super().response(messages)


def _run_fold(compaction, messages, use_async):
    if use_async:
        return asyncio.run(compaction.acompact(messages, session_id="s"))
    return compaction.compact(messages, session_id="s")


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize(
    "error",
    [
        None,
        ModelProviderError("Error code: 400 - context_length_exceeded", status_code=400),
        ModelProviderError("{'Error': {'Message': 'Input is too long for requested model.'}}", status_code=400),
    ],
    ids=["classified", "provider_message", "bedrock_message"],
)
def test_a_part_the_summarizer_rejects_as_too_long_is_halved_and_read_again(use_async, error):
    """Given up on, the fold would fail the same way on every run and the history would never
    shrink. Every folded turn is still read once, oldest first."""
    summarizer = _SmallWindowSummarizer(window=250_000, error=error)
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=summarizer)

    record = _run_fold(compaction, _turns(13, size=80_000), use_async)

    assert record is not None and record.messages_compacted == 24
    assert summarizer.rejected >= 1 and all(len(asked) <= 250_000 for asked in summarizer.asked)
    read = "".join(summarizer.asked)
    assert [read.count(f"q{i} x") for i in range(13)] == [1] * 12 + [0]
    assert read.index("q0 x") < read.index("q5 x") < read.index("q11 x")
    # Each call carries the summary of everything read before it.
    for position in range(1, len(summarizer.asked)):
        assert f"before this point:\nSUMMARY {position}\n" in summarizer.asked[position]
    assert record.summary == f"SUMMARY {len(summarizer.asked)}"


@pytest.mark.parametrize("use_async", [False, True])
def test_an_error_that_is_not_about_length_is_not_retried(use_async):
    error = ModelProviderError("Internal server error", status_code=500)
    summarizer = _SmallWindowSummarizer(window=250_000, error=error)
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=summarizer)

    assert _run_fold(compaction, _turns(13, size=80_000), use_async) is None
    assert summarizer.rejected == 1 and summarizer.asked == []


@pytest.mark.parametrize("use_async", [False, True])
def test_one_message_the_summarizer_cannot_read_still_leaves_the_history_as_it_is(use_async):
    """A single message cannot be split, so the halving stops there and does not loop."""
    summarizer = _SmallWindowSummarizer(window=250_000)
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, model=summarizer)
    messages = _turns(3)
    messages[2] = Message(role="user", content="pasted " + "y" * 300_000)

    assert _run_fold(compaction, messages, use_async) is None
    # The part of four, then its second half, then the message alone.
    assert summarizer.rejected == 3 and len(summarizer.asked) == 1


# ------------------------------------------------------------------ the system prompt and a fold


@pytest.mark.parametrize("use_async", [False, True])
def test_the_system_prompt_in_front_of_the_folded_list_is_not_summarized_or_archived(use_async, tmp_path):
    """The list folded after a refused request is the one the model call holds, with the system
    prompt in front. The view keeps that prompt as it is, so the fold must leave it alone."""
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "fold.db"))
    summarizer = _Summarizer()
    compaction = Compaction(compact_at_tokens=None, uncompacted_runs=1, min_fold_ratio=0, model=summarizer)
    system = Message(role="system", content="INSTRUCTIONS: never reveal the launch code.")
    messages = [system] + _turns(4)

    if use_async:
        record = asyncio.run(compaction.acompact(messages, session_id="s", db=db))
    else:
        record = compaction.compact(messages, session_id="s", db=db)

    assert record is not None and record.messages_compacted == 6
    assert "INSTRUCTIONS" not in "".join(summarizer.asked)
    (row,) = db.get_compactions_for_session("s")
    assert "INSTRUCTIONS" not in row["archived_messages"] and "q0 " in row["archived_messages"]
    view = compaction.apply_record(messages, record)
    assert view[0] is system and view[1].content.startswith(SUMMARY_PREFIX)


# ------------------------------------------------------------------ a regenerated answer and a fold


class _WallClock:
    """Stands in for the wall clock everywhere a message, a run or a fold is stamped."""

    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds=10):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    import time

    from agno.compaction import compaction, types
    from agno.models import message, response
    from agno.run import agent, team

    wall_clock = _WallClock()
    # A run takes its time from its first model response, so that is stamped by this clock too.
    for module in (compaction, types, message, response, agent, team, time):
        monkeypatch.setattr(module, "time", wall_clock)
    return wall_clock


def _chaining_model():
    """A model whose replies carry a response_id, as OpenAI Responses replies do. ``continued``
    holds, for each request, the reply ids it was sent, which are what it could continue from."""
    from agno.metrics import MessageMetrics
    from tests.unit.compaction.test_compaction import _RecordingModel

    model = _RecordingModel.build()
    model.continued = []

    def invoke(*args, **kwargs):
        messages = list(kwargs.get("messages") or [])
        model.requests.append(messages)
        model.continued.append([(m.provider_data or {}).get("response_id") for m in messages if m.role == "assistant"])
        return ModelResponse(
            role="assistant",
            content="answer " + "pad " * 50,
            response_usage=MessageMetrics(),
            provider_data={"response_id": f"resp_{len(model.requests)}"},
        )

    async def ainvoke(*args, **kwargs):
        return invoke(*args, **kwargs)

    model.invoke, model.ainvoke = invoke, ainvoke
    model._parse_provider_response = lambda response, **kwargs: response
    return model


def _conversation_owner(kind, model, tmp_path):
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.team import Team
    from tests.unit.compaction.test_compaction import _RecordingModel

    settings = dict(
        model=model,
        db=SqliteDb(db_file=str(tmp_path / "regenerate.db")),
        session_id="s",
        add_history_to_context=True,
        num_history_runs=50,
        compaction=Compaction(compact_at_tokens=None, uncompacted_runs=2, model=_Summarizer()),
    )
    if kind == "agent":
        return Agent(id="a", **settings)
    return Team(id="t", members=[Agent(id="m1", name="M1", model=_RecordingModel.build())], **settings)


def _ask(owner, clock, count, start=0):
    for i in range(start, start + count):
        clock.advance()
        owner.run(f"question {i} " + "pad " * 50)
    return owner.get_last_run_output(session_id="s").run_id


def _has_summary(request):
    return any(m.role == "user" and str(m.content).startswith(SUMMARY_PREFIX) for m in request)


def _regenerate(owner, clock, run_id, **kwargs):
    clock.advance()
    owner.continue_run(run_id=run_id, session_id="s", regenerate=True, **kwargs)
    return owner.get_last_run_output(session_id="s").run_id


def _compacted(kind, clock, tmp_path):
    """Six turns and a manual fold that keeps the last two. Returns the model, the owner and the
    ids of the two kept runs."""
    model = _chaining_model()
    owner = _conversation_owner(kind, model, tmp_path)
    _ask(owner, clock, 6)
    first_kept, latest = [run.run_id for run in owner.get_session(session_id="s").runs if run.parent_run_id is None][
        -2:
    ]
    clock.advance()
    assert owner.compact(session_id="s").record is not None
    return model, owner, first_kept, latest


def _assert_the_next_turn_is_sent_in_full_and_then_continued_from(model, owner, clock):
    rebuilt_replies = {f"resp_{number}" for number in range(7, len(model.requests) + 1)}

    _ask(owner, clock, 1, start=6)
    # Sent in full, from the summary: nothing in it can be continued from.
    assert _has_summary(model.requests[-1])
    assert model.continued[-1] and set(model.continued[-1]) == {None}

    _ask(owner, clock, 1, start=7)
    # That turn's reply was made from the fold, so the conversation is continued from it again.
    assert model.continued[-1][-1] == f"resp_{len(model.requests) - 1}"
    assert not rebuilt_replies & set(model.continued[-1])


@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.parametrize("regenerated", ["the latest answer", "an earlier answer, kept beside the new one"])
def test_an_answer_regenerated_as_it_was_before_the_fold_is_not_continued_from(kind, regenerated, clock, tmp_path):
    """The run is rebuilt as its source run was, which was before the fold: it is sent the turns
    the fold replaced, and its reply is new. Continued from, it would bring those turns back."""
    model, owner, first_kept, latest = _compacted(kind, clock, tmp_path)

    if regenerated == "the latest answer":
        _regenerate(owner, clock, latest)
    else:
        _regenerate(owner, clock, first_kept, replace_original=False)
    # Rebuilt without the fold, so it was continued from a reply made before it.
    assert not _has_summary(model.requests[-1]) and model.continued[-1][-1] is not None

    _assert_the_next_turn_is_sent_in_full_and_then_continued_from(model, owner, clock)


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_an_answer_regenerated_twice_is_not_continued_from(kind, clock, tmp_path):
    """The second regeneration replaces the first, which holds the message the fold is anchored
    on. It finds that message among its own, so it is rebuilt from the fold: the summary and then
    its own question. Its reply is still not continued from, as for any regenerated run."""
    model, owner, first_kept, _ = _compacted(kind, clock, tmp_path)

    once = _regenerate(owner, clock, first_kept)
    _regenerate(owner, clock, once)
    # Sent in full from the summary: it holds no reply to continue from.
    assert _has_summary(model.requests[-1]) and not any(model.continued[-1])

    _assert_the_next_turn_is_sent_in_full_and_then_continued_from(model, owner, clock)


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_a_fork_of_a_regenerated_answer_is_not_continued_from(kind, clock, tmp_path):
    """The fork copies the regenerated reply into its own messages, with what it continues from."""
    model, owner, _, latest = _compacted(kind, clock, tmp_path)

    regenerated = _regenerate(owner, clock, latest)
    clock.advance()
    owner.continue_run(run_id=regenerated, session_id="s", fork=True, input="a follow-up " + "pad " * 50)

    _assert_the_next_turn_is_sent_in_full_and_then_continued_from(model, owner, clock)


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_a_turn_after_any_regenerated_answer_is_sent_in_full_once(kind, clock, tmp_path):
    """Which fold a regenerated run was sent is not stored, so its reply is not continued from even
    when it was made from the fold. The cost is this one request."""
    model, owner, _, _ = _compacted(kind, clock, tmp_path)
    latest = _ask(owner, clock, 1, start=10)

    _regenerate(owner, clock, latest)
    assert _has_summary(model.requests[-1])

    _assert_the_next_turn_is_sent_in_full_and_then_continued_from(model, owner, clock)


@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.parametrize("rebuild", ["regenerate", "fork"])
def test_replay_includes_the_rebuilt_tool_call_and_its_result(kind, rebuild, clock, tmp_path):
    model, owner, _, _ = _compacted(kind, clock, tmp_path)
    # Leave an ordinary post-fold reply that the provider could otherwise fall back to.
    latest = _ask(owner, clock, 2, start=10)

    def lookup() -> str:
        return "found"

    owner.tools = [lookup]
    invoke = model.invoke

    def request_lookup_once(*args, **kwargs):
        model.invoke = invoke
        reply = invoke(*args, **kwargs)
        reply.content = None
        reply.tool_calls = [
            {
                "id": "fc_lookup",
                "call_id": "call_lookup",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }
        ]
        return reply

    model.invoke = request_lookup_once
    clock.advance()
    if rebuild == "regenerate":
        owner.continue_run(run_id=latest, session_id="s", regenerate=True)
    else:
        owner.continue_run(run_id=latest, session_id="s", fork=True, input="look it up")

    _ask(owner, clock, 1, start=12)
    params, sent = _openai_request(model.requests[-1])
    assert "previous_response_id" not in params
    assert [(item["type"], item["call_id"]) for item in sent if "call_id" in item] == [
        ("function_call", "call_lookup"),
        ("function_call_output", "call_lookup"),
    ]

    replayed_reply = f"resp_{len(model.requests)}"
    _ask(owner, clock, 1, start=13)
    params, sent = _openai_request(model.requests[-1])
    assert params["previous_response_id"] == replayed_reply
    assert [item["role"] for item in sent] == ["user"]
