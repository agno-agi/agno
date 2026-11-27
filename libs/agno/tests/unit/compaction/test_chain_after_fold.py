"""After a fold the conversation is continued from the folded state, and a fold larger than one
summarizer call is read in parts."""

import asyncio

import pytest

from agno.compaction import Compaction, CompactionRecord
from agno.compaction.compaction import DEFAULT_SUMMARIZE_CHAR_BUDGET
from agno.compaction.prompts import SUMMARY_PREFIX
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
