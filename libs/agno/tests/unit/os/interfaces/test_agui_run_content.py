"""What an agent or team run puts on the stream as content.

RunContentEvent.content is typed Any and the mapper reads it with a helper written for
message content, so the mapper meets shapes that helper cannot read. Failing to read one
may cost the client that content. It must never cost the client the rest of the run: the
mapper raising takes the stream down with it, and no terminal event ever arrives.
"""

import logging

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType

from agno.models.message import Message
from agno.run.agent import RunContentEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent

from ._agui_mappers import MAPPER_DRIVERS, MAPPER_IDS, validated


@pytest.fixture(params=MAPPER_DRIVERS, ids=MAPPER_IDS)
def run_stream(request):
    """Drive one chunk sequence through a mapper, once per mapper."""
    return validated(request.param)


def deltas_of(events):
    return [event.delta for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT]


UNREADABLE_CONTENTS = [
    pytest.param([1, 2, 3], id="list_of_ints"),
    pytest.param([1.5], id="list_of_floats"),
    pytest.param([None], id="list_of_nones"),
    pytest.param([True], id="list_of_bools"),
]


@pytest.mark.parametrize("content", UNREADABLE_CONTENTS)
def test_content_the_message_helper_cannot_read_costs_only_that_delta(run_stream, content):
    """The helper probes a list's first element for keys, which a scalar has none of.

    The run keeps streaming and still reaches its terminal event, and the deltas around
    the one it could not read arrive as they were sent.
    """
    events = run_stream([RunContentEvent(content=content), RunContentEvent(content="the rest of the answer")])

    assert events[-1].type == EventType.RUN_FINISHED
    assert deltas_of(events) == ["the rest of the answer"]


def test_content_the_message_helper_cannot_read_is_reported(caplog):
    """Content the mapper drops has to leave a trace, or it cannot be diagnosed at all.

    Swallowing the read and returning empty text is what keeps the run alive, and a
    crash guard that reports nothing is the fault it was written to remove.
    """
    with caplog.at_level(logging.WARNING):
        validated(MAPPER_DRIVERS[0])([RunContentEvent(content=[1, 2, 3]), RunContentEvent(content="the rest")])

    assert "could not read content" in caplog.text


@pytest.mark.parametrize("content", UNREADABLE_CONTENTS)
def test_team_content_the_message_helper_cannot_read_costs_only_that_delta(run_stream, content):
    """A team folds member output into the same reading, from the same helper."""
    events = run_stream([TeamRunContentEvent(content=content), TeamRunContentEvent(content="the rest of the answer")])

    assert events[-1].type == EventType.RUN_FINISHED
    assert deltas_of(events) == ["the rest of the answer"]


READABLE_CONTENTS = [
    pytest.param("plain text", "plain text", id="str"),
    pytest.param(
        [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}],
        "first\nsecond",
        id="list_of_typed_dicts",
    ),
    pytest.param([Message(role="user", content="from a message")], "from a message", id="list_of_messages"),
    pytest.param({"summary": "a record"}, '"summary": "a record"', id="dict"),
]


@pytest.mark.parametrize("content, expected_delta", READABLE_CONTENTS)
def test_content_the_message_helper_reads_is_sent_as_it_was_before(run_stream, content, expected_delta):
    """Guarding the read must not change the text a shape that already worked produces."""
    events = run_stream([RunContentEvent(content=content)])

    deltas = deltas_of(events)
    assert len(deltas) == 1
    assert expected_delta in deltas[0]


def test_a_team_content_event_carrying_member_responses_still_sends_the_leader_text(run_stream):
    """`member_responses` is not a field of the team content event, and the one path that
    can put it there rebuilds the event from a dict, where each member is a finished
    RunOutput. The mapper's fold reads members that are themselves content events, so it
    contributes nothing here and the leader's own text is the whole delta."""
    rebuilt = TeamRunContentEvent.from_dict(
        {
            "event": "TeamRunContent",
            "content": "leader text",
            "member_responses": [{"agent_id": "a1", "run_id": "r1", "content": "member text"}],
        }
    )

    events = run_stream([rebuilt])

    assert events[-1].type == EventType.RUN_FINISHED
    assert deltas_of(events) == ["leader text"]
