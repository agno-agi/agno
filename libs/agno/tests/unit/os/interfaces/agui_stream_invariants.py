"""An executable definition of a well-formed AG-UI stream, shared by the suites.

Three shapes of weak test kept reappearing in the AG-UI member attribution
suites: an assertion that passed because it folded two emissions into one key, an
assertion made against a fixture that emitted nothing of the kind it reasoned
about, and a wire-level invariant that no test checked at all. A fourth kept
reappearing too: a use of the subagent lineage protocol on an install that has
none, which fails rather than skipping. Each helper here is the one way the
suites do the thing that kept going wrong:

``assert_well_formed_stream``
    Every structural promise the protocol and this interface make, checked at
    once. Every collector below runs it, and so does every collector in the
    suites, so a new test inherits the whole set without opting in. Each of
    those promises has a stream that breaks it in
    ``test_agui_stream_invariants``, so one going quiet is a failure there
    rather than a silence everywhere.
``in_emitted_order``
    Ordered tuples of what was emitted, in place of a mapping keyed by a wire id
    or by content. A mapping silently folds a duplicate emission, and two
    members that produced identical text, into one entry.
``assert_stream_contains`` / ``assert_stream_carries_exactly``
    A census, so an assertion about reasoning, pauses or state cannot be made
    against a stream that carries none of it. A test that means "none of it"
    says the count, which the first of the two refuses to be handed.
``collect_sync`` / ``collect_async``
    The same chunk list driven through the sync and the async mapper, so the two
    bodies cannot drift. The ``*_recording_violations`` pair is for the one
    suite whose subject is streams that are NOT well formed today.
``attributed`` / ``event_type_named`` / ``needs_lineage_events``
    The single door to everything the subagent lineage protocol release added.
    Asking for the attributed setting, or for a ``SUBAGENT_*`` event type, on an
    install that has neither skips the test instead of failing it.
``member_mentions``
    Every way one stream names a member, for the assertions whose subject is a
    visibility that must name none. Reading one member event class passes while
    the privacy is broken, because a member announced and then closed as an
    error is named twice and counted zero times.
``assert_stream_is_malformed_as_recorded``
    The stream this interface emits malformed today, pinned to the violation it
    breaks. For a behaviour that is deferred rather than blessed: an exemption
    would say the stream is well formed and stop an invariant being checked on
    every later stream that names it, and these streams are not well formed at
    all.
``HOSTILE_VALUES`` / ``encoding_failures``
    Values a run's content can hold that serialization handles badly or not at
    all, to drive through every boundary that builds an event out of run
    content, and the protocol's own encoder to say whether what came out could
    have reached a client at all.
``LINEAGE_EVENTS_PROTOCOL_FLOOR`` / ``lineage_announcement_fields_missing``
    The protocol release member attribution needs, beside the fields this
    checker actually reads off an announcement, so the floor is recomputed
    against those fields rather than left standing as a comment.
``captured_agno_logs``
    Log capture at every logger this codebase writes through, at a level that
    can only widen what a test sees, never narrow it.
"""

import json
import logging
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from typing import Any, AsyncIterator, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import ag_ui.core
import pytest
from ag_ui.core import BaseEvent, EventType
from ag_ui.encoder import EventEncoder

from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.os.interfaces.agui.handlers import validate_subagent_visibility
from agno.os.interfaces.agui.state import SUBAGENT_VISIBILITY_ATTRIBUTED
from agno.os.interfaces.agui.stream import (
    async_stream_agno_response_as_agui_events,
    stream_agno_response_as_agui_events,
)
from agno.run.agent import RunContentEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.utils.log import LOGGER_NAME, TEAM_LOGGER_NAME, WORKFLOW_LOGGER_NAME

# --- The one door to the lineage protocol -----------------------------------

# The lineage events arrived in the ag-ui-protocol release named by
# ``LINEAGE_EVENTS_PROTOCOL_FLOOR`` below, and this package's agui extra still
# permits older ones, so everything that needs them skips instead of failing
# while the settings that work on any release keep running.
# Both halves of what ``attributed`` needs are feature-detected by the interface
# itself, so this asks the interface rather than guessing.
_NO_LINEAGE_REASON = "installed ag-ui-protocol cannot serve subagent_visibility='attributed'"


def _attributed_is_servable() -> bool:
    try:
        validate_subagent_visibility(SUBAGENT_VISIBILITY_ATTRIBUTED)
    except ValueError:
        return False
    return True


ATTRIBUTED_IS_SERVABLE = _attributed_is_servable()

needs_lineage_events = pytest.mark.skipif(not ATTRIBUTED_IS_SERVABLE, reason=_NO_LINEAGE_REASON)


def require_lineage_events() -> None:
    """Skip unless this install can serve member attribution."""
    if not ATTRIBUTED_IS_SERVABLE:
        pytest.skip(_NO_LINEAGE_REASON)


def attributed() -> str:
    """The attributed visibility, skipping when this install cannot serve it.

    Every request for member attribution in the suites comes through here, so an
    install without the lineage events cannot be asked for a setting the
    interface refuses at startup.
    """
    require_lineage_events()
    return SUBAGENT_VISIBILITY_ATTRIBUTED


# The same value without the skip, for the tests whose subject IS the refusal:
# on an install that lacks the lineage events those are the only tests that
# still have something to assert, so they must not skip there.
ATTRIBUTED_EVEN_WHEN_REFUSED = SUBAGENT_VISIBILITY_ATTRIBUTED


def event_type_named(name: str) -> "EventType":
    """One AG-UI event type by name, skipping when this install lacks it.

    The ``SUBAGENT_*`` members arrived with the lineage release, so naming one
    directly is what breaks a suite on an older install. Reaching an event type
    through here means a test that needs one this install does not define skips.
    """
    event_type = _event_type(name)
    if event_type is None:
        require_lineage_events()
        raise AssertionError(f"the installed ag_ui.core defines no {name} event type")
    return event_type


# --- Reading an event -------------------------------------------------------


def lane_of(event: BaseEvent) -> Optional[str]:
    """The member lane an event is stamped with, or None for the top-level entity."""
    return getattr(event, "subagent_run_id", None)


def of_type(events: Sequence[BaseEvent], event_type: "EventType") -> List[BaseEvent]:
    return [event for event in events if event.type == event_type]


def short_type(event: BaseEvent) -> str:
    return str(event.type).removeprefix("EventType.")


def declared_fields_of(event_class: Any) -> Optional[Iterable[str]]:
    """The field names one event class declares, or None for a class with no model.

    A protocol event's model accepts attributes it does not declare, so the
    presence of an attribute on an instance says nothing about whether the wire
    format carries it. A class with no model at all, which is what a stand-in
    for a renamed event is, declares nothing to compare against.
    """
    return getattr(event_class, "model_fields", None)


def field_of(event: BaseEvent, name: str) -> Any:
    """One declared field of an event, refusing to read one its model does not declare.

    Defaulting a missing attribute to None makes a renamed or removed field
    compare equal to itself on both sides of an assertion, so the comparison
    passes while nothing is being compared. Declared, not merely present: the
    protocol models accept extra attributes, so a field the wire format no
    longer carries can still be read back off an event something set it on, and
    the comparison is then between a test's own writes.
    """
    declared = declared_fields_of(type(event))
    carried = hasattr(event, name) if declared is None else name in declared
    assert carried, f"{short_type(event)} declares no {name} field, so nothing here compares it"
    return getattr(event, name)


def _event_type(name: str) -> Optional["EventType"]:
    """One protocol event type, or None on a release that does not define it.

    The lineage event types arrived after this interface's minimum protocol
    release, so this module has to import on an install that lacks them.
    """
    return getattr(EventType, name, None)


SUBAGENT_STARTED = _event_type("SUBAGENT_STARTED")
SUBAGENT_FINISHED = _event_type("SUBAGENT_FINISHED")
SUBAGENT_ERROR = _event_type("SUBAGENT_ERROR")

_MEMBER_TERMINAL_TYPES = tuple(t for t in (SUBAGENT_FINISHED, SUBAGENT_ERROR) if t is not None)
# Every event kind that is about a member at all, read off the installed
# EventType rather than listed beside the three the interface writes today, so a
# release that adds a fourth is covered here without an edit.
_MEMBER_EVENT_TYPES = tuple(
    event_type
    for event_type in (_event_type(name) for name in dir(EventType) if name.startswith("SUBAGENT_"))
    if event_type is not None
)
_RUN_TERMINAL_TYPES = (EventType.RUN_FINISHED, EventType.RUN_ERROR)
# The lifecycle of the run itself. Derived from the terminals rather than listed
# beside them, so the two cannot come to disagree about what ends a run.
_RUN_LEVEL_TYPES = (EventType.RUN_STARTED,) + _RUN_TERMINAL_TYPES
_STATE_TYPES = (EventType.STATE_SNAPSHOT, EventType.STATE_DELTA)

# Each link an announcement can carry beyond its parent member: the field, the
# event that has to have put what it names on the wire, and that event's own id
# field. The parent member link is not here; it resolves against the
# announcements themselves, which is a different lookup and its own invariant.
_ANNOUNCEMENT_PARENT_LINKS: Tuple[Tuple[str, "EventType", str], ...] = (
    ("parent_tool_call_id", EventType.TOOL_CALL_START, "tool_call_id"),
    ("parent_message_id", EventType.TEXT_MESSAGE_START, "message_id"),
)

# Each span family: a label, the event that opens a span, the one that closes
# it, and the field both carry the span's id in.
_SPAN_FAMILIES: Tuple[Tuple[str, "EventType", "EventType", str], ...] = (
    ("text message", EventType.TEXT_MESSAGE_START, EventType.TEXT_MESSAGE_END, "message_id"),
    ("tool call", EventType.TOOL_CALL_START, EventType.TOOL_CALL_END, "tool_call_id"),
    ("reasoning", EventType.REASONING_START, EventType.REASONING_END, "message_id"),
    (
        "reasoning message",
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_END,
        "message_id",
    ),
)

# Each content event, and the span it has to arrive inside. TOOL_CALL_RESULT is
# absent on purpose: the interface emits a call's result after that call's end,
# which is the shape the protocol asks for and which
# ``_assert_every_tool_result_follows_its_calls_end`` holds it to.
_CONTENT_IN_SPAN: Tuple[Tuple[str, "EventType", "EventType", "EventType", str], ...] = (
    (
        "text message content",
        EventType.TEXT_MESSAGE_CONTENT,
        EventType.TEXT_MESSAGE_START,
        EventType.TEXT_MESSAGE_END,
        "message_id",
    ),
    (
        "tool call arguments",
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_END,
        "tool_call_id",
    ),
    (
        "reasoning content",
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_END,
        "message_id",
    ),
)


# --- Ordered comparison instead of id-keyed folding -------------------------

Projection = Union[str, Callable[[BaseEvent], Any]]


def in_emitted_order(
    events: Sequence[BaseEvent],
    event_type: "EventType",
    *projections: Projection,
) -> List[Tuple[Any, ...]]:
    """Ordered tuples of the named fields, one entry per event of that type.

    A mapping keyed by a wire id or by content is the wrong shape for comparing
    what was emitted: a second emission of the same id overwrites the first, and
    two members that produced identical text collapse into one key. The list
    this returns keeps both, so a duplicate is a diff rather than a silence.

    A projection is a field name, which the event has to declare, or a callable
    given the event. A single projection still yields one-tuples, so every
    comparison reads the same way.
    """
    assert projections, "in_emitted_order needs at least one projection to compare"
    rows: List[Tuple[Any, ...]] = []
    for event in of_type(events, event_type):
        row = tuple(
            projection(event) if callable(projection) else field_of(event, projection) for projection in projections
        )
        rows.append(row)
    return rows


def joined_text_in_emitted_order(events: Sequence[BaseEvent]) -> List[Tuple[Optional[str], str]]:
    """(lane, joined text) per text message, in the order the messages opened.

    Ordered rather than keyed by message id or by the text itself, so a message
    emitted twice and two lanes saying the same thing both stay visible.
    """
    deltas: Dict[str, str] = {}
    for event in of_type(events, EventType.TEXT_MESSAGE_CONTENT):
        message_id = field_of(event, "message_id")
        deltas[message_id] = deltas.get(message_id, "") + field_of(event, "delta")
    return [
        (lane_of(event), deltas.get(field_of(event, "message_id"), ""))
        for event in of_type(events, EventType.TEXT_MESSAGE_START)
    ]


# --- The fixture census -----------------------------------------------------


def assert_stream_contains(events: Sequence[BaseEvent], event_type: "EventType", at_least: int = 1) -> None:
    """The stream really carries the kind of event the test is about to reason about.

    An assertion about reasoning, or a pause, or a state change, run against a
    stream that emitted none of it passes no matter what the implementation
    does. Stating the subject up front is what makes deleting the code that
    produces it fail a test.

    A lower bound of zero is refused rather than allowed to read as a check: it
    holds for every stream ever emitted. A test whose subject is an absence
    states the count instead.
    """
    assert at_least >= 1, (
        f"a lower bound of {at_least} {short_type_name(event_type)} events holds for any stream at all; "
        "state the count with assert_stream_carries_exactly instead"
    )
    found = len(of_type(events, event_type))
    assert found >= at_least, (
        f"this stream carries {found} {short_type_name(event_type)} events, "
        f"but the test reasons about at least {at_least}: the assertions below "
        "cannot exercise what they claim to"
    )


def assert_stream_carries_exactly(events: Sequence[BaseEvent], event_type: "EventType", count: int) -> None:
    """The stream carries exactly this many of an event, zero included."""
    found = len(of_type(events, event_type))
    assert found == count, f"this stream carries {found} {short_type_name(event_type)} events, not {count}"


def short_type_name(event_type: "EventType") -> str:
    return str(event_type).removeprefix("EventType.")


def member_mentions(events: Sequence[BaseEvent]) -> List[Tuple[str, Optional[str]]]:
    """(event, member) for everything in this stream that names a member.

    For an assertion whose subject is a visibility that must name none. A member
    reaches a client two ways: an event of one of the member kinds, and a lane
    stamped on any event at all. Reading one of those kinds is a check that
    holds while the privacy it is about is broken, because a member announced
    and then closed as an error is named twice over and counted zero times.

    The lane is read for presence rather than truthiness, as the invariants read
    it: an empty lane is still a lane on the wire.
    """
    return [
        (short_type(event), lane_of(event))
        for event in events
        if event.type in _MEMBER_EVENT_TYPES or lane_of(event) is not None
    ]


# --- The named invariants ---------------------------------------------------

# One name per structural promise, so an exemption can waive exactly the one it
# was written for and nothing else.
NO_SPAN_OPENS_TWICE = "no_span_opens_twice"
NO_SPAN_CLOSES_TWICE = "no_span_closes_twice"
NO_SPAN_CLOSES_UNOPENED = "no_span_closes_unopened"
EVERY_SPAN_CLOSES = "every_span_closes"
NO_SPAN_CLOSES_BEFORE_IT_OPENS = "no_span_closes_before_it_opens"
CONTENT_LANDS_INSIDE_ITS_SPAN = "content_lands_inside_its_span"
CONTENT_CARRIES_ITS_SPANS_MEMBER = "content_carries_its_spans_member"
A_SPAN_CLOSES_IN_THE_MEMBER_IT_OPENED_IN = "a_span_closes_in_the_member_it_opened_in"
EVERY_TOOL_CALL_PARENT_MESSAGE_WAS_OPENED = "every_tool_call_parent_message_was_opened"
A_TOOL_CALL_SITS_IN_ITS_PARENT_MESSAGES_MEMBER = "a_tool_call_sits_in_its_parent_messages_member"
EVERY_TOOL_RESULT_NAMES_A_STARTED_CALL = "every_tool_result_names_a_started_call"
EVERY_TOOL_RESULT_FOLLOWS_ITS_CALLS_END = "every_tool_result_follows_its_calls_end"
A_TOOL_RESULT_CARRIES_ITS_CALLS_MEMBER = "a_tool_result_carries_its_calls_member"
ONE_RUN_TERMINAL_AND_NOTHING_AFTER_IT = "one_run_terminal_and_nothing_after_it"
NO_MEMBER_IS_ANNOUNCED_TWICE = "no_member_is_announced_twice"
EVERY_STAMP_NAMES_AN_ANNOUNCED_MEMBER = "every_stamp_names_an_announced_member"
EVERY_ANNOUNCED_PARENT_IS_ANNOUNCED_TOO = "every_announced_parent_is_announced_too"
AN_ANNOUNCED_PARENT_PRECEDES_ITS_CHILD = "an_announced_parent_precedes_its_child"
EVERY_ANNOUNCED_PARENT_LINK_RESOLVES = "every_announced_parent_link_resolves"
EVERY_ANNOUNCED_MEMBER_TERMINATES = "every_announced_member_terminates"
NOTHING_CARRIES_A_MEMBER_AFTER_ITS_TERMINAL = "nothing_carries_a_member_after_its_terminal"
A_CHILDS_TERMINAL_PRECEDES_ITS_PARENTS = "a_childs_terminal_precedes_its_parents"
STATE_EVENTS_ARE_NEVER_STAMPED = "state_events_are_never_stamped"
RUN_EVENTS_ARE_NEVER_STAMPED = "run_events_are_never_stamped"

INVARIANTS = (
    NO_SPAN_OPENS_TWICE,
    NO_SPAN_CLOSES_TWICE,
    NO_SPAN_CLOSES_UNOPENED,
    EVERY_SPAN_CLOSES,
    NO_SPAN_CLOSES_BEFORE_IT_OPENS,
    CONTENT_LANDS_INSIDE_ITS_SPAN,
    CONTENT_CARRIES_ITS_SPANS_MEMBER,
    A_SPAN_CLOSES_IN_THE_MEMBER_IT_OPENED_IN,
    EVERY_TOOL_CALL_PARENT_MESSAGE_WAS_OPENED,
    A_TOOL_CALL_SITS_IN_ITS_PARENT_MESSAGES_MEMBER,
    EVERY_TOOL_RESULT_NAMES_A_STARTED_CALL,
    EVERY_TOOL_RESULT_FOLLOWS_ITS_CALLS_END,
    A_TOOL_RESULT_CARRIES_ITS_CALLS_MEMBER,
    ONE_RUN_TERMINAL_AND_NOTHING_AFTER_IT,
    NO_MEMBER_IS_ANNOUNCED_TWICE,
    EVERY_STAMP_NAMES_AN_ANNOUNCED_MEMBER,
    EVERY_ANNOUNCED_PARENT_IS_ANNOUNCED_TOO,
    AN_ANNOUNCED_PARENT_PRECEDES_ITS_CHILD,
    EVERY_ANNOUNCED_PARENT_LINK_RESOLVES,
    EVERY_ANNOUNCED_MEMBER_TERMINATES,
    NOTHING_CARRIES_A_MEMBER_AFTER_ITS_TERMINAL,
    A_CHILDS_TERMINAL_PRECEDES_ITS_PARENTS,
    STATE_EVENTS_ARE_NEVER_STAMPED,
    RUN_EVENTS_ARE_NEVER_STAMPED,
)


# --- Exemptions -------------------------------------------------------------

# A stream that legitimately breaks one invariant names its exemption. Each
# exemption waives exactly one named invariant and is justified here and nowhere
# else, so an unexplained one cannot be introduced by passing a bare string and
# a waiver cannot quietly widen to cover a second promise.
TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL = "trailing_output_after_a_member_terminal"
ABANDONED_MID_STREAM = "abandoned_mid_stream"
ABANDONED_WITH_A_MEMBER_STILL_OPEN = "abandoned_with_a_member_still_open"

_EXEMPTIONS: Dict[str, Tuple[str, str]] = {
    TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL: (
        NOTHING_CARRIES_A_MEMBER_AFTER_ITS_TERMINAL,
        "something still carries the member after its terminal, from one of the "
        "two places that can. The source stream emits a chunk from a member "
        "whose own run already completed, and a terminal is final for the id it "
        "names, so the interface keeps that output attributed to the member "
        "rather than giving one invocation a second lifecycle. Or the run-end "
        "sweep writes the end of a tool call that member left open, because a "
        "member's terminal ends no tool call: only the call's own completion "
        "knows what it produced. Either way the terminal is still unique.",
    ),
    ABANDONED_MID_STREAM: (
        EVERY_SPAN_CLOSES,
        "the consumer walked away mid-message, so the collected events are a "
        "deliberate prefix of a stream: the spans open at that point are never "
        "closed, because there is no client left to write them to.",
    ),
    ABANDONED_WITH_A_MEMBER_STILL_OPEN: (
        EVERY_ANNOUNCED_MEMBER_TERMINATES,
        "the consumer walked away while a member was streaming, so the member "
        "announced in that prefix never reaches a terminal, for the same reason "
        "its spans never close: nothing is written to a client that left.",
    ),
}

EXEMPTIONS = tuple(_EXEMPTIONS)


class StreamInvariantCheckerFailure(Exception):
    """The checker could not reach a verdict, which is never a fact about the stream.

    An exemption nobody justified, an exemption the stream does not need, and
    anything raised inside an invariant that is not that invariant failing, all
    say the harness is wrong rather than the stream. Deliberately not an
    ``AssertionError``: the reporter returns those as the stream's violation, so
    a checker fault needs a channel of its own or it reaches the caller dressed
    as the verdict it prevented.
    """


def exemption_waives(exemption: str) -> str:
    """The single invariant one exemption waives."""
    return _EXEMPTIONS[exemption][0]


def _assert_exemptions_are_justified(exempt: Sequence[str]) -> None:
    for granted in exempt:
        if granted not in _EXEMPTIONS:
            raise StreamInvariantCheckerFailure(f"{granted!r} is not a justified stream invariant exemption")


def _waived(exempt: Sequence[str], invariant: str) -> bool:
    """Whether one named invariant is waived, refusing an exemption nobody justified."""
    _assert_exemptions_are_justified(exempt)
    return any(_EXEMPTIONS[granted][0] == invariant for granted in exempt)


# --- Streams this interface emits malformed today ---------------------------

# A stream the interface really emits that the invariants above reject, whose
# behaviour is deferred rather than agreed to be correct. Deliberately not an
# exemption: an exemption says a stream is well formed for a stated reason and
# stops one named invariant being checked on every later stream that claims it,
# and these streams are not well formed at all. Naming one here pins the
# violation instead. Nothing stops being checked, the caller states the
# disagreement where a reader sees it, and the day the behaviour changes the pin
# fails rather than going quiet.
A_CALL_PROMPTED_ONCE_PER_PAUSE_KIND = "a_call_prompted_once_per_pause_kind"

_DEFERRED_VIOLATIONS: Dict[str, Tuple[str, str]] = {
    A_CALL_PROMPTED_ONCE_PER_PAUSE_KIND: (
        "tool call ids opened more than once",
        "the pause prompt shows every pending call the pause listed, so two of "
        "them under one tool call id reach the client as one id opened, argued "
        "and closed twice. Three promises break at once there, not the one an "
        "exemption could waive: the span opens twice, it closes twice, and the "
        "second batch of arguments arrives after the first end. The prompt is "
        "what this interface has always emitted and no test here changes it. "
        "Two shapes reach it. A pause reporting one call under two pause-kind "
        "lists is the first, and asking for the interrupt outcome ends that run "
        "instead of prompting it only where the two kinds are one requirement "
        "nothing can answer. A run reports them as two entries under the call's "
        "own id and raises one answerable requirement, and a model is free to "
        "number two of its calls alike, so both reach the prompt under either "
        "setting.",
    ),
}


def deferred_violation(deferred: str) -> str:
    """The violation one deliberately malformed stream is pinned to."""
    assert deferred in _DEFERRED_VIOLATIONS, f"{deferred!r} is not a recorded deferred stream violation"
    return _DEFERRED_VIOLATIONS[deferred][0]


def assert_stream_is_malformed_as_recorded(events: Sequence[BaseEvent], deferred: str) -> None:
    """Hold a deliberately malformed stream to the violation recorded for it.

    A stream that is well formed now fails here, and so does one that breaks
    something other than what is recorded, so pinning a violation waives
    nothing: every invariant still runs, and what the run reports is compared
    against the one thing this stream is allowed to break.
    """
    recorded = deferred_violation(deferred)
    violation = stream_invariant_violation(events)
    assert violation is not None, (
        f"this stream is well formed now, so the {deferred} record is stale: "
        "delete the record and the pin that names it"
    )
    assert recorded in violation, f"this stream breaks {violation!r}, and not the recorded {recorded!r}"


# --- One executable definition of a well-formed stream ----------------------


def _assert_invariants(events: Sequence[BaseEvent], exempt: Sequence[str]) -> None:
    """The invariant set itself, run once per set of granted exemptions."""
    _assert_spans_open_once_and_close(events, exempt)
    _assert_content_lands_inside_its_span(events)
    _assert_content_carries_its_spans_member(events)
    _assert_a_span_closes_in_the_member_it_opened_in(events)
    _assert_every_tool_call_parent_message_was_opened(events)
    _assert_a_tool_call_sits_in_its_parent_messages_member(events)
    _assert_every_tool_result_names_a_started_call(events)
    _assert_every_tool_result_follows_its_calls_end(events)
    _assert_a_tool_result_carries_its_calls_member(events)
    _assert_nothing_follows_the_run_terminal(events)
    _assert_no_member_is_announced_twice(events)
    _assert_every_stamp_names_an_announced_member(events)
    _assert_every_announced_parent_is_announced_too(events)
    _assert_an_announced_parent_precedes_its_child(events)
    _assert_every_announced_parent_link_resolves(events)
    _assert_each_member_owns_exactly_one_terminal(events, exempt)
    _assert_a_childs_terminal_precedes_its_parents(events)
    _assert_state_events_are_never_stamped(events)
    _assert_run_events_are_never_stamped(events)


def assert_well_formed_stream(events: Sequence[BaseEvent], exempt: Sequence[str] = ()) -> None:
    """Every structural invariant the protocol and member attribution promise.

    Called by every collector in this module, and by every collector in the
    suites, so each test gets the whole set whether or not it thought to ask. A
    stream that breaks one of these for a correct reason names its exemption; a
    bare string is refused, and so is an exemption this stream turns out not to
    need: a waiver granted for a case that no longer arises silently stops the
    invariant from being checked on every later run of that same stream.
    """
    _assert_exemptions_are_justified(exempt)
    _assert_invariants(events, exempt)

    for granted in exempt:
        narrowed = [other for other in exempt if other != granted]
        try:
            _assert_invariants(events, narrowed)
        except AssertionError:
            continue
        raise StreamInvariantCheckerFailure(
            f"this stream is well formed without the {granted} exemption, so granting it waives "
            f"{exemption_waives(granted)} on a stream that does not break it"
        )


def stream_invariant_violation(events: Sequence[BaseEvent], exempt: Sequence[str] = ()) -> Optional[str]:
    """The first invariant a stream breaks, or None when it is well formed.

    For the few callers that have to state, and pin, that a stream is NOT well
    formed today. Everything else asserts well-formedness directly.

    Three outcomes, not two: the string, ``None``, or a raised
    ``StreamInvariantCheckerFailure`` when the checker never reached a verdict.
    Callers read the returned string as the thing this stream breaks, so a fault
    in the checker has to arrive as a raise or it is filed against the stream.
    """
    try:
        assert_well_formed_stream(events, exempt)
    except AssertionError as violation:
        return str(violation)
    except StreamInvariantCheckerFailure:
        raise
    except BaseException as raised:
        raise StreamInvariantCheckerFailure(
            f"an invariant raised {type(raised).__name__} instead of failing: {raised}"
        ) from raised
    return None


def _assert_spans_open_once_and_close(events: Sequence[BaseEvent], exempt: Sequence[str]) -> None:
    allow_open = _waived(exempt, EVERY_SPAN_CLOSES)
    for label, start_type, end_type, id_field in _SPAN_FAMILIES:
        opened = [field_of(event, id_field) for event in of_type(events, start_type)]
        closed = [field_of(event, id_field) for event in of_type(events, end_type)]

        repeated = sorted(span_id for span_id, count in Counter(opened).items() if count > 1)
        assert not repeated, f"{label} ids opened more than once: {repeated}"

        # Counted before the two set comparisons below, which cannot see a
        # duplicate at all: a span opened once and closed twice subtracts to a
        # balance of zero, and reporting the leftover close as a span that never
        # opened names the wrong fault on an id the stream did open.
        closed_twice = sorted(span_id for span_id, count in Counter(closed).items() if count > 1)
        assert not closed_twice, f"{label} ids closed more than once: {closed_twice}"

        # Sets, now that neither side can hold a duplicate: a count difference
        # here could only restate the two assertions above.
        unopened = sorted(set(closed) - set(opened))
        assert not unopened, f"{label} ids closed without ever being opened: {unopened}"

        if not allow_open:
            unclosed = sorted(set(opened) - set(closed))
            assert not unclosed, f"{label} ids opened and never closed: {unclosed}"

        # Ordering is checked whether or not a span is allowed to stay open: a
        # close that precedes its own open is malformed in either stream.
        first_close: Dict[Any, int] = {}
        for index, event in enumerate(events):
            if event.type == end_type:
                first_close.setdefault(field_of(event, id_field), index)
        for index, event in enumerate(events):
            if event.type != start_type:
                continue
            span_id = field_of(event, id_field)
            closed_at = first_close.get(span_id)
            assert closed_at is None or closed_at > index, f"{label} {span_id} was closed before it opened"


def _assert_content_lands_inside_its_span(events: Sequence[BaseEvent]) -> None:
    """A delta belongs to a span the client has a start for and not yet an end.

    Without this, a delta naming an id that was never opened, and one arriving
    after that id's own end, are both accepted as well formed, and a client has
    nowhere to put either.
    """
    for label, content_type, start_type, end_type, id_field in _CONTENT_IN_SPAN:
        opened: Dict[Any, int] = {}
        closed: Dict[Any, int] = {}
        for index, event in enumerate(events):
            if event.type == start_type:
                opened.setdefault(field_of(event, id_field), index)
            elif event.type == end_type:
                closed.setdefault(field_of(event, id_field), index)
            elif event.type == content_type:
                span_id = field_of(event, id_field)
                assert span_id in opened, (
                    f"{label} at index {index} names {span_id}, which no earlier {short_type_name(start_type)} opened"
                )
                assert span_id not in closed, (
                    f"{label} at index {index} names {span_id}, whose "
                    f"{short_type_name(end_type)} already went out at index {closed[span_id]}"
                )


def _assert_content_carries_its_spans_member(events: Sequence[BaseEvent]) -> None:
    """A delta is stamped with the member whose span it belongs to.

    A client routes an event by the span it names and renders it in the member
    it is stamped with. Those two disagreeing puts one member's words inside
    another member's bubble, which no other check here would notice: the delta
    names an open span, and its lane names an announced member.
    """
    for label, content_type, start_type, _end_type, id_field in _CONTENT_IN_SPAN:
        lane_of_span: Dict[Any, Optional[str]] = {}
        for event in events:
            if event.type == start_type:
                lane_of_span.setdefault(field_of(event, id_field), lane_of(event))
            elif event.type == content_type:
                span_id = field_of(event, id_field)
                if span_id not in lane_of_span:
                    # The span itself was never opened, which the check above reports.
                    continue
                assert lane_of(event) == lane_of_span[span_id], (
                    f"{label} for {span_id} is stamped with member {lane_of(event)}, while the "
                    f"{short_type_name(start_type)} that opened it named {lane_of_span[span_id]}"
                )


def _assert_a_span_closes_in_the_member_it_opened_in(events: Sequence[BaseEvent]) -> None:
    """A span's end is stamped with the member its start named.

    The end is what tells a client the bubble is finished, so an end stamped
    with another member, or with none, closes a bubble in a lane that never
    opened one and leaves the real one open forever. The delta check above
    compares content against its start and would not notice either.
    """
    for label, start_type, end_type, id_field in _SPAN_FAMILIES:
        lane_of_span: Dict[Any, Optional[str]] = {}
        for event in events:
            if event.type == start_type:
                lane_of_span.setdefault(field_of(event, id_field), lane_of(event))
            elif event.type == end_type:
                span_id = field_of(event, id_field)
                if span_id not in lane_of_span:
                    # The span was closed without ever opening, which the span
                    # check above reports.
                    continue
                assert lane_of(event) == lane_of_span[span_id], (
                    f"the {short_type_name(end_type)} for {label} {span_id} is stamped with member "
                    f"{lane_of(event)}, while the {short_type_name(start_type)} that opened it named "
                    f"{lane_of_span[span_id]}"
                )


def _assert_every_tool_call_parent_message_was_opened(events: Sequence[BaseEvent]) -> None:
    """A call's parent message is one this stream opened.

    A conforming client attaches a call to the assistant message its
    ``parent_message_id`` names, so a call naming a message the stream never
    opened is one the client has nowhere to attach and no way to render in
    place. The lane rule below compares the pair only where both halves are
    present, which is exactly what an unresolvable parent is not.
    """
    opened = {field_of(event, "message_id") for event in of_type(events, EventType.TEXT_MESSAGE_START)}
    for event in of_type(events, EventType.TOOL_CALL_START):
        parent = field_of(event, "parent_message_id")
        if parent is None:
            # A call parented to nothing is rendered on its own, which is a
            # shape the protocol allows and this rule has no subject in.
            continue
        assert parent in opened, (
            f"tool call {field_of(event, 'tool_call_id')} names parent message {parent}, which no "
            "TEXT_MESSAGE_START in this stream opened, so a client has nothing to attach it to"
        )


def _assert_a_tool_call_sits_in_its_parent_messages_member(events: Sequence[BaseEvent]) -> None:
    """A tool call is stamped with the member of the message it names as its parent.

    A conforming client attaches a call to the assistant message its
    ``parent_message_id`` names and renders each of the two in the member it is
    stamped with, so a call and its parent message disagreeing puts the call in
    a lane where its own message was never drawn. Every other lane check
    compares an event against its own span, and a call's parent message is
    another span, so none of them looks at this pair.
    """
    lane_of_message: Dict[Any, Optional[str]] = {}
    for event in events:
        if event.type == EventType.TEXT_MESSAGE_START:
            lane_of_message.setdefault(field_of(event, "message_id"), lane_of(event))

    for event in of_type(events, EventType.TOOL_CALL_START):
        parent = field_of(event, "parent_message_id")
        if parent is None or parent not in lane_of_message:
            # A call parented to no message has no pair here to disagree, and
            # one parented to a message this stream never opened is refused by
            # the check above rather than by comparing it against nothing.
            continue
        assert lane_of(event) == lane_of_message[parent], (
            f"tool call {field_of(event, 'tool_call_id')} is stamped with member {lane_of(event)}, while the "
            f"message {parent} it names as its parent was opened in member {lane_of_message[parent]}"
        )


def _assert_every_tool_result_names_a_started_call(events: Sequence[BaseEvent]) -> None:
    """A result belongs to a call the client already has a start for.

    The result arrives outside its call's span, so the in-span check deliberately
    skips it, which left a result naming a call that was never started, and one
    arriving ahead of its own start, as well-formed streams: in both the client
    has no card to put the result in at the moment it arrives.
    """
    started_at: Dict[Any, int] = {}
    for index, event in enumerate(events):
        if event.type == EventType.TOOL_CALL_START:
            started_at.setdefault(field_of(event, "tool_call_id"), index)

    orphans = [
        field_of(event, "tool_call_id")
        for event in of_type(events, EventType.TOOL_CALL_RESULT)
        if field_of(event, "tool_call_id") not in started_at
    ]
    assert not orphans, f"tool call results name calls no TOOL_CALL_START opened: {orphans}"

    for index, event in enumerate(events):
        if event.type != EventType.TOOL_CALL_RESULT:
            continue
        call_id = field_of(event, "tool_call_id")
        assert started_at[call_id] < index, (
            f"the result for tool call {call_id} went out at index {index}, ahead of the "
            f"TOOL_CALL_START that opened it at index {started_at[call_id]}"
        )


def _assert_every_tool_result_follows_its_calls_end(events: Sequence[BaseEvent]) -> None:
    """A result goes out after its own call's end, not inside the call's span.

    The result is the reason TOOL_CALL_RESULT is left out of the in-span table:
    it belongs after the end rather than between the start and the end. Holding
    it only to the start is a weaker promise than that, and it accepts the shape
    the table is written around, a result delivered while the client still has
    the call open and its arguments still streaming.
    """
    started_at: Dict[Any, int] = {}
    ended_at: Dict[Any, int] = {}
    for index, event in enumerate(events):
        if event.type == EventType.TOOL_CALL_START:
            started_at.setdefault(field_of(event, "tool_call_id"), index)
        elif event.type == EventType.TOOL_CALL_END:
            ended_at.setdefault(field_of(event, "tool_call_id"), index)

    for index, event in enumerate(events):
        if event.type != EventType.TOOL_CALL_RESULT:
            continue
        call_id = field_of(event, "tool_call_id")
        if call_id not in started_at or index < started_at[call_id]:
            # No start, or a result ahead of it, which the check above reports.
            continue
        if call_id not in ended_at:
            # The call never closed, which the span check reports, except on the
            # abandoned prefix where it is waived and there is no end to follow.
            continue
        assert ended_at[call_id] < index, (
            f"the result for tool call {call_id} went out at index {index}, inside the call's own span: "
            f"the TOOL_CALL_END that closed it is at index {ended_at[call_id]}"
        )


def _assert_a_tool_result_carries_its_calls_member(events: Sequence[BaseEvent]) -> None:
    """A result is stamped with the member whose call produced it.

    A result stamped with another member puts one member's tool output in
    another member's card. The result sits outside its call's span, so neither
    the in-span check nor the span-lane check above looks at it.
    """
    lane_of_call: Dict[Any, Optional[str]] = {}
    for event in events:
        if event.type == EventType.TOOL_CALL_START:
            lane_of_call.setdefault(field_of(event, "tool_call_id"), lane_of(event))
            continue
        if event.type != EventType.TOOL_CALL_RESULT:
            continue
        call_id = field_of(event, "tool_call_id")
        if call_id not in lane_of_call:
            # No start for this result, which the check above reports.
            continue
        assert lane_of(event) == lane_of_call[call_id], (
            f"the result for tool call {call_id} is stamped with member {lane_of(event)}, while the "
            f"TOOL_CALL_START that opened it named {lane_of_call[call_id]}"
        )


def _assert_nothing_follows_the_run_terminal(events: Sequence[BaseEvent]) -> None:
    terminals = [index for index, event in enumerate(events) if event.type in _RUN_TERMINAL_TYPES]
    assert len(terminals) <= 1, (
        f"a run carries at most one terminal, got {[short_type(events[index]) for index in terminals]}"
    )
    if terminals:
        following = [short_type(event) for event in events[terminals[0] + 1 :]]
        assert not following, f"events followed the run terminal: {following}"
        return

    # A run the client was told began owes it an end. No terminal at all is
    # nonetheless well formed for a list that is a fragment of a response body
    # rather than a whole one: the router writes RUN_STARTED and owns the
    # terminal when the source stream raises, and a source that never says the
    # run completed gets no terminal written for it. What the fragment must not
    # do is announce a start and stop, which leaves a client waiting forever.
    started = of_type(events, EventType.RUN_STARTED)
    assert not started, (
        f"this stream carries {len(started)} RUN_STARTED and no terminal, so a client is left "
        "waiting on a run it was told had begun"
    )


def announcements(events: Sequence[BaseEvent]) -> List[BaseEvent]:
    """Every member announcement in order, of which an old install can carry none.

    An install without the lineage events cannot put a SUBAGENT_STARTED on the
    wire, so an empty list is the truth there rather than a waived check. A test
    that needs the event type itself asks ``event_type_named`` and skips.
    """
    if SUBAGENT_STARTED is None:
        return []
    return of_type(events, SUBAGENT_STARTED)


def announced_lane(announcement: BaseEvent) -> Any:
    """The member one announcement names, read as a declared field.

    Every check that resolves a stamp, a parent link or a terminal against the
    announcements reads the announced id through here. The permissive lookup
    would default a renamed field to None, which leaves every announcement
    naming the top-level entity: stamps stop resolving to anything, parent links
    and terminals resolve to each other, and the checks pass while nothing about
    member attribution is being compared.
    """
    return field_of(announcement, "subagent_run_id")


def _assert_no_member_is_announced_twice(events: Sequence[BaseEvent]) -> None:
    """One announcement per member.

    A member id is one invocation, and Agno mints a fresh one per delegation, so
    a second announcement of the same id either restarts a lane the client has
    already drawn or splits one invocation across two. Its own promise rather
    than a line inside the stamp check: a stamp resolves against the announced
    ids either way, so the stamp check cannot be what holds this.
    """
    seen: Dict[Any, int] = {}
    for index, event in enumerate(announcements(events)):
        lane = announced_lane(event)
        assert lane not in seen, f"member {lane} was announced more than once"
        seen[lane] = index


def _assert_every_stamp_names_an_announced_member(events: Sequence[BaseEvent]) -> None:
    announced: Dict[Optional[str], int] = {}
    for index, event in enumerate(events):
        lane = lane_of(event)
        if SUBAGENT_STARTED is not None and event.type == SUBAGENT_STARTED:
            announced.setdefault(announced_lane(event), index)
            continue
        if lane is None:
            continue
        assert lane in announced, (
            f"{short_type(event)} at index {index} is stamped with member {lane}, "
            "which no earlier announcement named, so a client cannot resolve it"
        )


def _assert_every_announced_parent_is_announced_too(events: Sequence[BaseEvent]) -> None:
    """A member's parent link names a member this stream also announces.

    Left unchecked, an announcement can hand the client a parent id that appears
    nowhere on the wire, which is a lane the client can neither draw nor resolve.

    Announced anywhere in the stream, which is the floor: it refuses the case no
    ordering can rescue, a parent the stream never announces at all.
    ``_assert_an_announced_parent_precedes_its_child`` holds the rest, that the
    announcement comes first.
    """
    announced = {announced_lane(event) for event in announcements(events)}
    for event in announcements(events):
        # Read as a declared field: defaulting a renamed one to None would make
        # every announcement look parentless and this check pass on anything.
        parent = field_of(event, "parent_subagent_run_id")
        if parent is None:
            continue
        assert parent in announced, (
            f"member {announced_lane(event)} names parent {parent}, which this stream never "
            "announces, so a client cannot place it under anything"
        )


def _assert_an_announced_parent_precedes_its_child(events: Sequence[BaseEvent]) -> None:
    """A parent link names a member this stream has already announced.

    A client reads the stream in order and resolves a parent link when it
    arrives, so a link to a member announced further down is one it cannot place
    at the moment it is handed it. The check above is the floor under this and
    refuses only a parent the stream never announces at all; this one refuses
    the forward reference the interface avoids by announcing a parent before any
    child that names it.
    """
    announced_at: Dict[Any, int] = {}
    in_order = [
        (index, event)
        for index, event in enumerate(events)
        if SUBAGENT_STARTED is not None and event.type == SUBAGENT_STARTED
    ]
    for index, event in in_order:
        announced_at.setdefault(announced_lane(event), index)

    for index, event in in_order:
        parent = field_of(event, "parent_subagent_run_id")
        if parent is None or parent not in announced_at:
            # A parent this stream never announces, which the check above reports.
            continue
        assert announced_at[parent] < index, (
            f"member {announced_lane(event)} announced at index {index} names parent {parent}, which this "
            f"stream does not announce until index {announced_at[parent]}, so a client reading in order "
            "cannot place it when it arrives"
        )


def _assert_every_announced_parent_link_resolves(events: Sequence[BaseEvent]) -> None:
    """The call and the message an announcement names are ones this stream carries.

    An announcement places the member under a delegating tool call and under the
    assistant message that call hangs off, which is what a client nests the
    member's lane inside. Either of those naming something the stream never put
    on the wire leaves the client a lane it cannot place, exactly as a parent
    member it never announced does, and only the member link was resolved.
    """
    for field, start_type, id_field in _ANNOUNCEMENT_PARENT_LINKS:
        carried = {field_of(event, id_field) for event in of_type(events, start_type)}
        for event in announcements(events):
            named = field_of(event, field)
            if named is None:
                # A member announced under no call or no message: a top-level
                # delegation the interface reports without either, which is a
                # lane the client draws at the top rather than nested.
                continue
            assert named in carried, (
                f"member {announced_lane(event)} names {field} {named}, which no "
                f"{short_type_name(start_type)} in this stream carries, so a client cannot place it"
            )


def _assert_each_member_owns_exactly_one_terminal(events: Sequence[BaseEvent], exempt: Sequence[str]) -> None:
    announced = [announced_lane(event) for event in announcements(events)]
    terminals: Dict[Optional[str], List[int]] = {}
    for index, event in enumerate(events):
        if event.type in _MEMBER_TERMINAL_TYPES:
            terminals.setdefault(lane_of(event), []).append(index)

    # A member may always own at most one terminal. Owning none is what the
    # abandonment exemption waives, and nothing else.
    at_most_one_only = _waived(exempt, EVERY_ANNOUNCED_MEMBER_TERMINATES)
    for lane in announced:
        count = len(terminals.get(lane, []))
        if at_most_one_only:
            assert count <= 1, f"member {lane} owns {count} terminals, expected at most one"
        else:
            assert count == 1, f"member {lane} owns {count} terminals, expected exactly one"

    # A terminal naming a member nothing announced is not checked here. It
    # carries that member's lane, so the stamp check above already refuses it,
    # and a second assertion for it can never be reached to be trusted.

    if _waived(exempt, NOTHING_CARRIES_A_MEMBER_AFTER_ITS_TERMINAL):
        return
    for lane in announced:
        indexes = terminals.get(lane, [])
        if not indexes:
            continue
        after = [
            short_type(event) for index, event in enumerate(events) if index > indexes[0] and lane_of(event) == lane
        ]
        assert not after, f"events carrying member {lane} followed its terminal: {after}"


def _assert_a_childs_terminal_precedes_its_parents(events: Sequence[BaseEvent]) -> None:
    # The parent link is read as a declared field: defaulting a renamed one to
    # None would leave every lane parentless and this check ordering nothing.
    parent_of = {announced_lane(event): field_of(event, "parent_subagent_run_id") for event in announcements(events)}
    # The first terminal a lane owns, as every other helper here keeps the first
    # of anything: a member owning a second one is refused by the check above,
    # and under the waiver that permits owning none this ordering would
    # otherwise be read off whichever terminal happened to come last.
    first_terminal_at: Dict[Optional[str], int] = {}
    for index, event in enumerate(events):
        if event.type in _MEMBER_TERMINAL_TYPES:
            first_terminal_at.setdefault(lane_of(event), index)
    for lane, parent in parent_of.items():
        if parent is None or parent not in first_terminal_at or lane not in first_terminal_at:
            continue
        assert first_terminal_at[lane] < first_terminal_at[parent], (
            f"member {lane} terminated after its parent {parent}, so a client would "
            "see a child resolve inside a member it had already closed"
        )


def _assert_state_events_are_never_stamped(events: Sequence[BaseEvent]) -> None:
    # Presence, not truthiness: an empty lane is still a lane on the wire, and a
    # client filtering by member drops the document just as surely.
    stamped = [
        (short_type(event), lane_of(event))
        for event in events
        if event.type in _STATE_TYPES and lane_of(event) is not None
    ]
    assert not stamped, (
        f"state events carry a member lane: {stamped}. A team's session state is one "
        "shared document, so a client filtering by member must not lose it"
    )


def _assert_run_events_are_never_stamped(events: Sequence[BaseEvent]) -> None:
    """The run's own lifecycle belongs to the run, not to a member.

    A member lane on RUN_STARTED or on a run terminal tells a client the run
    itself began or ended inside one member, which a client filtering by member
    either misplaces or drops: the start it needs to open the run, or the
    terminal it needs to stop waiting for one. Read for presence, as the state
    rule is, because an empty lane is still a lane on the wire.
    """
    stamped = [
        (short_type(event), lane_of(event))
        for event in events
        if event.type in _RUN_LEVEL_TYPES and lane_of(event) is not None
    ]
    assert not stamped, (
        f"run lifecycle events carry a member lane: {stamped}. A run begins and ends once, "
        "for the whole stream, so no member owns either end of it"
    )


# --- The protocol release member attribution needs --------------------------

# The release the subagent lineage events arrived in. Nothing gates on it: what
# ``attributed`` needs is feature-detected, above and in the interface itself.
# It is here to be recomputed against those features by
# ``test_agui_stream_invariants``, which is what keeps the number in the comment
# at the head of this module, and in the interface's own documentation, from
# drifting away from the release that actually carries them.
LINEAGE_EVENTS_PROTOCOL_FLOOR = (0, 1, 21)

# Every field this checker reads off an announcement. The parent links come from
# the table the invariant reads, so a link added there is one the floor is
# recomputed against too.
LINEAGE_ANNOUNCEMENT_FIELDS_READ_HERE = ("subagent_run_id", "parent_subagent_run_id") + tuple(
    field for field, _start_type, _id_field in _ANNOUNCEMENT_PARENT_LINKS
)


def installed_protocol_release() -> Tuple[int, ...]:
    """The installed ag-ui-protocol release, as its leading numeric components.

    Parsed rather than compared as a string, where 0.1.9 sorts above 0.1.21, and
    truncated at the first component that is not a plain number, so a
    pre-release or a local build compares as the release it is built from.
    """
    try:
        raw = installed_version("ag-ui-protocol")
    except PackageNotFoundError as missing:  # pragma: no cover - ag_ui imported from somewhere else
        raise AssertionError(f"ag_ui is importable but its distribution metadata is not: {missing}")
    components: List[int] = []
    for piece in raw.split("."):
        digits = ""
        for character in piece:
            if not character.isdigit():
                break
            digits += character
        if not digits:
            break
        components.append(int(digits))
    return tuple(components)


def announcement_fields_missing_from(event_class: Any) -> List[str]:
    """The fields this checker reads that one announcement class does not declare."""
    declared = declared_fields_of(event_class) or ()
    return sorted(field for field in LINEAGE_ANNOUNCEMENT_FIELDS_READ_HERE if field not in declared)


def lineage_announcement_fields_missing() -> List[str]:
    """Those fields the installed announcement omits, of which an old release omits all."""
    announcement = getattr(ag_ui.core, "SubagentStartedEvent", None)
    if announcement is None:
        return sorted(LINEAGE_ANNOUNCEMENT_FIELDS_READ_HERE)
    return announcement_fields_missing_from(announcement)


# --- What the protocol's own encoder can put on a wire ----------------------


def encoding_failures(events: Sequence[BaseEvent]) -> List[Tuple[str, str]]:
    """(event type, failure) for every event the protocol's encoder refuses.

    The interface hands its events to this same encoder, so an event it cannot
    serialize reaches no client at all: the response body stops there, with
    whatever was written before it and no run terminal.
    """
    encoder = EventEncoder()
    refused: List[Tuple[str, str]] = []
    for event in events:
        try:
            encoder.encode(event)
        except Exception as error:
            refused.append((short_type(event), type(error).__name__))
    return refused


# --- Log capture at the loggers this codebase writes through ----------------

# ``log_error`` and ``log_warning`` write to whichever of these the last agent,
# team or workflow run selected, and agno's level setters run on every one of
# those runs, so any of the three can be sitting at a level that drops the
# records a test is about to assert on.
AGNO_LOGGER_NAMES = (LOGGER_NAME, TEAM_LOGGER_NAME, WORKFLOW_LOGGER_NAME)


@contextmanager
def captured_agno_logs(caplog: Any, level: str) -> Iterator[None]:
    """Capture at every logger agno's log helpers can write through, never above it.

    ``caplog.at_level`` sets the level it is given on the logger it names, so
    asking for ERROR on a logger sitting at INFO RAISES that logger's threshold
    and drops every warning underneath. The threshold entered here is therefore
    the most permissive of the level asked for and the levels the three loggers
    already have, which can only widen what a test sees.
    """
    # Looked up with a default so a name that is not a level is reported as one
    # rather than raising AttributeError out of a context manager's entry. A
    # bool is refused explicitly: it passes an int check, and the module holds
    # bool settings, so a true one would enter capture at level 1 and quietly
    # read as the widest capture there is.
    wanted = getattr(logging, level, None)
    assert isinstance(wanted, int) and not isinstance(wanted, bool), f"{level!r} is not a logging level name"
    floor = min([wanted, *(logging.getLogger(name).getEffectiveLevel() for name in AGNO_LOGGER_NAMES)])
    with ExitStack() as stack:
        for name in AGNO_LOGGER_NAMES:
            stack.enter_context(caplog.at_level(floor, logger=name))
        yield


# --- The same chunks through both mappers -----------------------------------

Collected = Tuple[List[BaseEvent], Optional[BaseException]]
MalformedCollected = Tuple[List[BaseEvent], Optional[BaseException], Optional[str]]


class SideEffect:
    """A chunk list entry the source runs for its effect, emitting nothing.

    A fixture that changes the session state partway through a run only produces
    the delta the client should see if the change happens while the stream is
    being consumed, not while the chunk list is being built.
    """

    def __init__(self, action: Callable[[], Any]) -> None:
        self.action = action


def sse_events(body: str) -> List[Dict[str, Any]]:
    """The events of an SSE response body, decoded in the order they arrived.

    Shared, because a suite that drives the mounted route reads its result this
    way and a second copy of the decoding is a second thing that can be wrong
    about what the wire carried.
    """
    return [json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")]


class ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id) or ('content', text)."""

    def __init__(self, model_id: str, script: List[tuple], fail_with: Optional[str] = None):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0
        self._fail_with = fail_with

    def _next(self) -> ModelResponse:
        if self._fail_with:
            raise RuntimeError(self._fail_with)
        if not self._script:
            raise AssertionError(f"{self.id} was asked for a turn but was given an empty script")
        # Refused rather than clamped to the last turn: a test that asks for more
        # turns than it scripted is asserting about a turn it never wrote.
        assert self._i < len(self._script), (
            f"{self.id} was asked for turn {self._i} of a {len(self._script)}-turn script"
        )
        turn = self._script[self._i]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, tcid = turn
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            ]
            return response
        response = ModelResponse(content=turn[1], role="assistant")
        response.event = ModelResponseEvent.assistant_response.value
        return response

    def invoke(self, *args, **kwargs):
        return self._next()

    async def ainvoke(self, *args, **kwargs):
        return self._next()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def sync_source(chunks: Iterable[Any]) -> Iterator[Any]:
    """A sync source stream that raises any exception placed in the chunk list."""
    for chunk in chunks:
        if isinstance(chunk, BaseException):
            raise chunk
        if isinstance(chunk, SideEffect):
            chunk.action()
            continue
        yield chunk


async def async_source(chunks: Iterable[Any]) -> AsyncIterator[Any]:
    """An async source stream that raises any exception placed in the chunk list."""
    for chunk in chunks:
        if isinstance(chunk, BaseException):
            raise chunk
        if isinstance(chunk, SideEffect):
            chunk.action()
            continue
        yield chunk


def _servable(visibility: Optional[str]) -> Optional[str]:
    """The visibility to drive with, keeping a configuration error out of the stream.

    A setting this install cannot serve skips, and an invalid one is raised from
    here rather than from inside the drivers below, where it would be collected
    as though the source stream itself had failed.
    """
    if visibility == SUBAGENT_VISIBILITY_ATTRIBUTED:
        require_lineage_events()
    validate_subagent_visibility(visibility)
    return visibility


def _recorded(raised: BaseException, chunks: Sequence[Any]) -> BaseException:
    """The failure a driver collects, re-raising an interruption no chunk placed.

    The sources above raise whatever the chunk list holds, and a chunk list may
    hold any ``BaseException``. Catching ``Exception`` alone let one of those
    out of the driver, which returned nothing: no invariant ran on the events it
    had already collected, and the test read a raise where it had asked for a
    recorded failure. What still has to pass through is an interruption from
    outside the run, which is why this is by identity against the list rather
    than a wider except.
    """
    if isinstance(raised, Exception) or any(raised is chunk for chunk in chunks):
        return raised
    raise raised


def _drive_sync(
    chunks: Iterable[Any],
    visibility: Optional[str],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]],
    emit_interrupt_outcome: bool,
) -> Collected:
    resolved = _servable(visibility)
    driving = list(chunks)
    events: List[BaseEvent] = []
    error: Optional[BaseException] = None
    try:
        for event in stream_agno_response_as_agui_events(
            sync_source(driving),
            thread_id=thread_id,
            run_id=run_id,
            run_state=run_state,
            subagent_visibility=resolved,
            emit_interrupt_outcome=emit_interrupt_outcome,
        ):
            events.append(event)
    except BaseException as raised:
        error = _recorded(raised, driving)
    return events, error


async def _drive_async(
    chunks: Iterable[Any],
    visibility: Optional[str],
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]],
    emit_interrupt_outcome: bool,
) -> Collected:
    resolved = _servable(visibility)
    driving = list(chunks)
    events: List[BaseEvent] = []
    error: Optional[BaseException] = None
    try:
        async for event in async_stream_agno_response_as_agui_events(
            async_source(driving),
            thread_id=thread_id,
            run_id=run_id,
            run_state=run_state,
            subagent_visibility=resolved,
            emit_interrupt_outcome=emit_interrupt_outcome,
        ):
            events.append(event)
    except BaseException as raised:
        error = _recorded(raised, driving)
    return events, error


async def collect_sync(
    chunks: Iterable[Any],
    visibility: Optional[str] = None,
    *,
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
    exempt: Sequence[str] = (),
    emit_interrupt_outcome: bool = False,
) -> Collected:
    events, error = _drive_sync(chunks, visibility, thread_id, run_id, run_state, emit_interrupt_outcome)
    assert_well_formed_stream(events, exempt)
    return events, error


async def collect_async(
    chunks: Iterable[Any],
    visibility: Optional[str] = None,
    *,
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
    exempt: Sequence[str] = (),
    emit_interrupt_outcome: bool = False,
) -> Collected:
    events, error = await _drive_async(chunks, visibility, thread_id, run_id, run_state, emit_interrupt_outcome)
    assert_well_formed_stream(events, exempt)
    return events, error


async def collect_sync_recording_violations(
    chunks: Iterable[Any],
    visibility: Optional[str] = None,
    *,
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
    exempt: Sequence[str] = (),
    emit_interrupt_outcome: bool = False,
) -> MalformedCollected:
    """As ``collect_sync``, reporting the invariant a stream broke instead of failing.

    For the callers whose subject is a stream that is not well formed today. The
    invariants still run, on exactly the same definition, so a stream that stops
    being malformed is a diff rather than a silence.
    """
    events, error = _drive_sync(chunks, visibility, thread_id, run_id, run_state, emit_interrupt_outcome)
    return events, error, stream_invariant_violation(events, exempt)


async def collect_async_recording_violations(
    chunks: Iterable[Any],
    visibility: Optional[str] = None,
    *,
    thread_id: str,
    run_id: str,
    run_state: Optional[Dict[str, Any]] = None,
    exempt: Sequence[str] = (),
    emit_interrupt_outcome: bool = False,
) -> MalformedCollected:
    events, error = await _drive_async(chunks, visibility, thread_id, run_id, run_state, emit_interrupt_outcome)
    return events, error, stream_invariant_violation(events, exempt)


# --- The lineage fields a source chunk carries ------------------------------

# The id the suites give the top-level entity's own run. Shared, because a
# member chunk's ``parent_run_id`` has to name it for the chunk to be a
# member's at all.
TOP_LEVEL_RUN = "top-level-run"


def member_chunk_kwargs(member: str, run: str, parent: str = TOP_LEVEL_RUN) -> Dict[str, Any]:
    """The lineage fields Agno stamps on one member Agent's chunks."""
    return {"agent_id": member, "agent_name": member.capitalize(), "run_id": run, "parent_run_id": parent}


def team_chunk_kwargs(team_id: str, name: str, run: str, parent: Optional[str] = None) -> Dict[str, Any]:
    """The lineage fields Agno stamps on one Team's chunks, top-level or nested."""
    kwargs: Dict[str, Any] = {"team_id": team_id, "team_name": name, "run_id": run}
    if parent is not None:
        kwargs["parent_run_id"] = parent
    return kwargs


def agent_said(content: Any, **kwargs: Any) -> RunContentEvent:
    """One Agent content chunk carrying whatever a run's content can hold.

    The content is assigned rather than passed to the constructor, so a value
    the field's own type refuses still reaches the mapper.
    """
    chunk = RunContentEvent(**kwargs)
    chunk.content = content
    return chunk


def team_said(content: Any, **kwargs: Any) -> TeamRunContentEvent:
    """One Team content chunk carrying whatever a run's content can hold."""
    chunk = TeamRunContentEvent(**kwargs)
    chunk.content = content
    return chunk


# --- Hostile values ---------------------------------------------------------


class RaisesOnSerialization:
    """A value every serialization route refuses, as a partly-built object can be."""

    def model_dump_json(self) -> str:
        raise RuntimeError("dump exploded")

    def __repr__(self) -> str:
        raise RuntimeError("repr exploded")

    def to_dict(self) -> Dict[str, Any]:
        raise RuntimeError("to_dict exploded")


class UnrenderableError(Exception):
    """A failure that raises while being described, as one carrying a value does.

    An exception built out of the thing that failed holds that thing, so
    rendering the exception runs the same code the read did. Every guard that
    interpolates a caught exception into its own record is running this.
    """

    def __str__(self) -> str:
        raise RuntimeError("the exception cannot render itself")


class RaisesAnUnreadableError(RaisesOnSerialization):
    """A value whose serialization raises a failure that cannot be rendered either.

    One level past ``RaisesOnSerialization``, which raises a failure that does
    render: a guard can catch that one and still write its record. This value is
    the case where catching is not enough, so it drives what a recovery path
    does with the exception it caught rather than what it does with the value.
    """

    def model_dump_json(self) -> str:
        raise UnrenderableError("dump exploded")

    def __repr__(self) -> str:
        raise UnrenderableError("repr exploded")

    def to_dict(self) -> Dict[str, Any]:
        raise UnrenderableError("to_dict exploded")


def circular() -> Dict[str, Any]:
    """A mapping that holds itself, which the JSON encoder refuses."""
    cycle: Dict[str, Any] = {}
    cycle["self"] = cycle
    return cycle


# The values a run's content can hold that serialization handles badly, driven
# through every boundary that builds an AG-UI event out of run content. Not all
# of them are unserializable: ``not_a_number`` and ``none`` are the two most
# serializers do handle, and what they are here for is that the boundaries
# disagree about them, which the hostile suite's own table records.
# ``raises_an_unreadable_error`` is not about serialization at all: it is the
# level past a value that raises, where the failure raised cannot be rendered
# either, so it drives the recovery paths rather than the reads they guard.
HOSTILE_VALUES: Tuple[Tuple[str, Callable[[], Any]], ...] = (
    ("circular", circular),
    ("raises_on_serialization", RaisesOnSerialization),
    ("raises_an_unreadable_error", RaisesAnUnreadableError),
    ("set", lambda: {"a", "b"}),
    ("not_a_number", lambda: float("nan")),
    ("none", lambda: None),
)
