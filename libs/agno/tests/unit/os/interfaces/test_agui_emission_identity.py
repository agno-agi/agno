"""What a client receives with the interrupt outcome off, against what it received before it existed.

The whole feature rests on one promise: ``emit_interrupt_outcome`` is off by
default, and with it off a released client sees the stream it has always seen.
That promise is what makes the change safe to ship, and until this module nothing
held it. It was checked by hand after each wave of work, which is exactly as good
as the last time somebody remembered to check.

So the interface as it stood before the round trip is checked in beside this one
(see ``agui_baseline_tree``) and run. Every stream below is driven through both,
encoded with the protocol's own encoder, and compared as JSON. Not the events in
memory: what a client receives is the encoded body, and an event the models
accept but the encoder writes differently is a difference to a client and no
difference at all in memory.

Three things keep the comparison from passing for the wrong reason.

The streams are enumerated rather than listed. They come from the tables the
other sweeps in this directory already keep: every place the interface builds an
event out of run content, driven with benign content and with every hostile
value, and every shape of pause. A stream added to either table is compared here
with nothing to opt in, which is the property a hand-written list does not have.
Three more are written here, and only because they are shared-path changes no
stream in those tables reaches; each says so where it is defined.

The normalisation is one rule. A minted identifier is aliased to the order it
was first seen in, so an interface that mints one more, or reuses one where it
used to mint, still fails. Nothing else is normalised, timestamps included: a
timestamp on the wire is copied off the chunk it came from, and one chunk list is
driven through both trees, so the two sides carry the same value rather than one
that has to be normalised away.

And the differences that are real are stated, not waived. The branch fixed
defects on the path both settings share, so some streams legitimately differ. Each
one is named in ``INTENDED_DIFFERENCES`` with the exact divergence it produces and
the reason it is intended, and a stream that is not named there has to be
identical. A stated difference that changes shape fails just as loudly as a new
one, because what is stated is where the two streams part and what each does
after.

The line this draws is the emission. It is not drawn around the route, and the
last class here says why: the route makes two decisions differently now, and both
are about what it asks the entity to do rather than about what it writes, so they
are driven and pinned as decisions.
"""

import copy
import json
import re
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import RunAgentInput, ToolMessage, UserMessage
from ag_ui.encoder import EventEncoder

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.response import ToolExecution
from agno.os.interfaces.agui import stream as live_stream_module
from agno.os.interfaces.agui.router import run_entity as live_run_entity
from agno.os.interfaces.agui.state import SUBAGENT_VISIBILITY_ATTRIBUTED, SUBAGENT_VISIBILITY_VALUES
from agno.run.agent import RunCompletedEvent, RunOutput, RunStartedEvent
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent
from agno.session.agent import AgentSession

from . import agui_baseline_tree
from .agui_stream_invariants import (
    ATTRIBUTED_IS_SERVABLE,
    TOP_LEVEL_RUN,
    member_chunk_kwargs,
    team_chunk_kwargs,
)
from .test_agui_hostile_run_content import _BOUNDARIES as CONTENT_BOUNDARIES
from .test_agui_hostile_run_content import _HOSTILE as HOSTILE_VALUES
from .test_agui_interrupts import _PAUSE_SHAPES, _PAUSES_NOTHING_CAN_ANSWER

baseline_stream_module = agui_baseline_tree.module("stream")
baseline_run_entity = agui_baseline_tree.module("router").run_entity

THREAD_ID = "emission-identity"

# The setting under test, spelled out so every drive below reads as the claim it
# makes: this is the default, and the default is what has to be unchanged.
THE_OUTCOME_IS_OFF = False


# --- What a client receives --------------------------------------------------

# A minted identifier, which is the one thing on the wire this interface makes up
# rather than copies. Matched by shape and nothing else: a value that is not one
# of these is compared as it is.
_MINTED = re.compile(r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")

MINTED_ALIAS = "minted-{}"


def aliased(value: Any, minted: Dict[str, str]) -> Any:
    """One decoded event with its minted ids replaced by the order they appeared in.

    Narrow on purpose. Only a value shaped like a minted id is touched, and each
    distinct one gets its own alias, assigned when it is first seen, so the
    result still carries how many ids the stream minted, which events shared one
    and in what order they arrived. A stream that mints one id more than it used
    to, or reuses one where it used to mint a fresh one, differs here even though
    no literal value survives the rewrite.
    """
    if isinstance(value, str):
        return minted.setdefault(value, MINTED_ALIAS.format(len(minted) + 1)) if _MINTED.match(value) else value
    if isinstance(value, dict):
        return {key: aliased(item, minted) for key, item in value.items()}
    if isinstance(value, list):
        return [aliased(item, minted) for item in value]
    return value


UNSENDABLE = "the encoder refused this event"


def _failure(error: Optional[BaseException]) -> Optional[Tuple[str, str]]:
    """A failure the mapper let out, as the two things about it a client can see.

    The class, because the route reports a failure it catches by name in its own
    log, and the text, because the same route puts ``str(error)`` on the wire as
    the run's error message. So a failure that changed its wording changed what a
    client is shown.

    Read through a guard, since rendering a failure runs the value that failed:
    the read this comparison is about is one of the reads that can raise.
    """
    if error is None:
        return None
    try:
        return type(error).__name__, str(error)
    except BaseException:
        return type(error).__name__, UNSENDABLE


class Received(NamedTuple):
    """One whole stream as a client receives it: the encoded events, then the end.

    ``failure`` is what the mapper raised out, which a client sees as a body that
    stops without a run terminal.
    """

    events: List[Any]
    failure: Optional[Tuple[str, str]]


def received(events: Sequence[Any], error: Optional[BaseException]) -> Received:
    """Encode a stream the way the route does, and normalise only its minted ids.

    An event the encoder refuses is recorded as refused rather than dropped: on a
    real wire the body stops there, so a stream that refuses one event where the
    other refuses none is not the same stream at all.
    """
    encoder = EventEncoder()
    minted: Dict[str, str] = {}
    encoded: List[Any] = []
    for event in events:
        try:
            body = encoder.encode(event)
        except Exception as refusal:
            encoded.append({UNSENDABLE: type(refusal).__name__})
            continue
        encoded.append(aliased(json.loads(body.removeprefix("data: ").strip()), minted))
    return Received(encoded, _failure(error))


# --- Driving one stream through both trees -----------------------------------


def _sync_source(chunks: Sequence[Any]) -> Iterator[Any]:
    for chunk in chunks:
        yield chunk


async def _async_source(chunks: Sequence[Any]) -> AsyncIterator[Any]:
    for chunk in chunks:
        yield chunk


def _drive_sync(mapper: Callable[..., Iterator[Any]], chunks: Sequence[Any], **kwargs: Any) -> Received:
    events: List[Any] = []
    error: Optional[BaseException] = None
    try:
        for event in mapper(_sync_source(chunks), **kwargs):
            events.append(event)
    except BaseException as raised:
        error = raised
    return received(events, error)


async def _drive_async(mapper: Callable[..., AsyncIterator[Any]], chunks: Sequence[Any], **kwargs: Any) -> Received:
    events: List[Any] = []
    error: Optional[BaseException] = None
    try:
        async for event in mapper(_async_source(chunks), **kwargs):
            events.append(event)
    except BaseException as raised:
        error = raised
    return received(events, error)


SYNC = "sync"
ASYNC = "async"
MAPPERS = (SYNC, ASYNC)


async def through_both_trees(
    chunks: Sequence[Any],
    run_state: Optional[Dict[str, Any]],
    visibility: Optional[str],
    mapper: str,
) -> Tuple[Received, Received]:
    """The same chunk list through the baseline and through this interface.

    The same list, not two builds of one: a chunk carries the moment it was made,
    and that value is copied onto the wire, so two builds would differ by when
    they happened and the comparison would need a rule to forgive it. One list
    removes the question instead of normalising an answer to it.
    """
    common = dict(thread_id=THREAD_ID, run_id=TOP_LEVEL_RUN, run_state=run_state, subagent_visibility=visibility)
    if mapper == SYNC:
        before = _drive_sync(baseline_stream_module.stream_agno_response_as_agui_events, chunks, **common)
        after = _drive_sync(
            live_stream_module.stream_agno_response_as_agui_events,
            chunks,
            emit_interrupt_outcome=THE_OUTCOME_IS_OFF,
            **common,
        )
        return before, after
    before = await _drive_async(baseline_stream_module.async_stream_agno_response_as_agui_events, chunks, **common)
    after = await _drive_async(
        live_stream_module.async_stream_agno_response_as_agui_events,
        chunks,
        emit_interrupt_outcome=THE_OUTCOME_IS_OFF,
        **common,
    )
    return before, after


# --- How two streams are said to differ --------------------------------------

IDENTICAL = "identical"


def _ending(stream: Received) -> str:
    if stream.failure is None:
        return f"sent {len(stream.events)} and reached its terminal"
    return f"sent {len(stream.events)} and raised {stream.failure[0]}"


def divergence(before: Received, after: Received) -> str:
    """Where two streams part, and what each of them did from there.

    Stated rather than counted, because the table below is read by whoever has to
    decide whether a change was meant. The point they agree up to is what says a
    difference is confined to the end of a stream rather than running through the
    whole of it, and an entry whose agreement point moves is a different change
    from the one that was blessed.
    """
    if before == after:
        return IDENTICAL
    common = min(len(before.events), len(after.events))
    agreed = next(
        (index for index in range(common) if before.events[index] != after.events[index]),
        common,
    )
    return f"agree on {agreed}; baseline {_ending(before)}; now {_ending(after)}"


def _at(stream: Received, index: int) -> str:
    return json.dumps(stream.events[index]) if index < len(stream.events) else "nothing, the stream ended here"


def where_they_part(before: Received, after: Received) -> str:
    """The two events a comparison first disagreed on, for the failure to be read by.

    The divergence above is the signature the table states, which is deliberately
    coarse: whoever has to act on a failure needs the events themselves, and
    printing two whole streams buries the one line that matters.
    """
    common = min(len(before.events), len(after.events))
    index = next((position for position in range(common) if before.events[position] != after.events[position]), common)
    return (
        f"they first differ at event {index}\n  before: {_at(before, index)}\n  now:    {_at(after, index)}\n"
        f"  baseline failure: {before.failure}\n  failure now:      {after.failure}"
    )


# --- The streams this compares -----------------------------------------------

# Every visibility a caller can set, plus the absence of one, which is what a
# caller who sets nothing gets and is therefore the setting most streams run
# under.
VISIBILITIES: Tuple[Optional[str], ...] = (None,) + tuple(SUBAGENT_VISIBILITY_VALUES)

BENIGN = "benign"


def _content_streams() -> List[Tuple[str, Callable[[], Any]]]:
    """Every event-building boundary, with benign content and with each hostile value.

    Read off the table the hostile-content suite keeps, so a boundary added there
    is compared here without being mentioned here, and so is a value added to the
    shared list of them. Both halves matter: the benign column is where the
    promise is really made, and the hostile one is where every difference this
    branch introduced turns out to live.
    """
    streams = []
    for boundary in CONTENT_BOUNDARIES:
        streams.append((f"{boundary.name}/{BENIGN}", lambda b=boundary: b.builder(b.benign())))
        for value_name, value in HOSTILE_VALUES.items():
            streams.append((f"{boundary.name}/{value_name}", lambda b=boundary, v=value: b.builder(v())))
    return streams


class Stream(NamedTuple):
    chunks: List[Any]
    run_state: Optional[Dict[str, Any]] = None


def _pause_streams() -> List[Tuple[str, Callable[[], Any]]]:
    """Every shape of pause the interrupt suite enumerates, continuable or not.

    A pause is the only run whose terminal the setting changes, so these are the
    streams the promise is most exposed on: with the outcome off, each of them has
    to reach a client as the plain prompt and plain terminal it always did.
    """
    shapes = {**_PAUSE_SHAPES, **_PAUSES_NOTHING_CAN_ANSWER}
    return [(f"pause/{name}", lambda s=shape: Stream([s()])) for name, shape in shapes.items()]


class _NoCopy:
    """A session state value with no copy of its own, as one holding a live handle is."""

    def __deepcopy__(self, memo: Dict[int, Any]) -> Any:
        raise RuntimeError("this state has no copy")


def _a_failed_run_whose_chunk_names_a_member() -> Stream:
    """A failed team run whose own chunk carries a member's identity inside it.

    Written here because no boundary in the reused table reaches it. The terminal
    of a failed run embeds the chunk verbatim, and this branch made that embed
    conditional on whether the chunk names a member under a visibility that names
    none. Every existing test of that condition drives it with the outcome on,
    where a pause can reach the failed terminal; with the outcome off only a real
    failure gets there, and the framework's failure chunks carry a member only in
    the free-form field used here.
    """
    failed = TeamRunErrorEvent(
        content="the run failed", **team_chunk_kwargs("research-team", "Research Team", TOP_LEVEL_RUN)
    )
    failed.additional_data = {"member_id": "scout"}
    return Stream(
        [
            TeamRunStartedEvent(**team_chunk_kwargs("research-team", "Research Team", TOP_LEVEL_RUN)),
            RunStartedEvent(**member_chunk_kwargs("scout", "run-scout")),
            failed,
        ]
    )


def _a_session_state_that_cannot_be_copied() -> Stream:
    """A run ending on a session state with no copy of its own.

    Written here for the reason above: the terminal's own state snapshot is
    copied, and the copy is only reached when the request carried state, which is
    a property of the request rather than of any chunk the content table builds.
    The state the run ends holding is the chunk's, and the one it started with is
    left copyable so the difference is about the terminal's copy and not the
    stream's opening one.
    """
    done = RunCompletedEvent(content="done", run_id=TOP_LEVEL_RUN)
    done.session_state = {"held": _NoCopy()}
    return Stream([RunStartedEvent(run_id=TOP_LEVEL_RUN), done], run_state={})


# Streams for changes on the shared path that none of the reused tables reach.
# Each one's own docstring says why it cannot come from there.
SHARED_PATH_STREAMS: Tuple[Tuple[str, Callable[[], Stream]], ...] = (
    ("shared-path/a_failed_run_whose_chunk_names_a_member", _a_failed_run_whose_chunk_names_a_member),
    ("shared-path/a_session_state_that_cannot_be_copied", _a_session_state_that_cannot_be_copied),
)


STREAMS: List[Tuple[str, Callable[[], Any]]] = (
    _content_streams() + _pause_streams() + [(name, builder) for name, builder in SHARED_PATH_STREAMS]
)


# --- The differences that are intended ---------------------------------------

A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN = (
    "A value the interface could not render or serialize used to raise out of the mapper, so the body "
    "stopped where it raised and the client was left with no run terminal at all. It is now recorded and "
    "dropped, and the run reaches its terminal. Every one of these is a stream that was broken before."
)

A_PENDING_CALL_WITH_AN_UNUSABLE_ID_FAILS_UNDER_A_DIFFERENT_NAME = (
    "A pause listing a call whose id is not a string still ends the run, and the client still receives the "
    "same events, but the failure reaching the route has a different class and text: the pause is now read "
    "through a mapping keyed by that id before the protocol's own model is asked to refuse it. The route "
    "puts the failure's text on the wire, so the wording a client is shown changes even though nothing "
    "before it does."
)

THE_VERBATIM_CHUNK_IS_WITHHELD_WHERE_NO_MEMBER_MAY_BE_NAMED = (
    "A failed run's terminal embeds the chunk it died on. Under the visibility that names no member, a "
    "chunk naming one is now withheld and recorded for the operator instead. Passing it through published "
    "the member identity the setting exists to withhold."
)

THE_TERMINAL_STATE_SNAPSHOT_IS_DROPPED_RATHER_THAN_ENDING_THE_RUN = (
    "Copying the session state a run ends holding is the last thing the terminal builds. A state with no "
    "copy of its own raised there, which discarded the closing sweep and the terminal with it. The snapshot "
    "is now dropped with a record and the run reaches its terminal."
)


class Intended(NamedTuple):
    """One stream that legitimately differs, and the account of why.

    ``divergence`` is per visibility, because a change on the shared path can be
    reachable under one setting and not another, and a table that stated one
    verdict for all of them would pass on a stream that started differing
    somewhere new.
    """

    reason: str
    divergence: Dict[Optional[str], str]


def _everywhere(divergence_text: str) -> Dict[Optional[str], str]:
    return {visibility: divergence_text for visibility in VISIBILITIES}


# Every stream that differs, with the exact divergence it produces. A stream not
# named here has to be identical, and a stream named here has to differ in the
# way it says, so a further change to one of these is as loud as a new one.
INTENDED_DIFFERENCES: Dict[str, Intended] = {
    "member_identity/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            SUBAGENT_VISIBILITY_ATTRIBUTED: "agree on 1; baseline sent 1 and raised RuntimeError; now sent 8 and reached its terminal"
        },
    ),
    "paused_member_name/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            SUBAGENT_VISIBILITY_ATTRIBUTED: "agree on 1; baseline sent 1 and raised RuntimeError; now sent 9 and reached its terminal"
        },
    ),
    "pause_prompt_args/circular": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        _everywhere("agree on 1; baseline sent 1 and raised ValueError; now sent 7 and reached its terminal"),
    ),
    "pause_prompt_args/raises_on_serialization": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        _everywhere("agree on 1; baseline sent 1 and raised TypeError; now sent 7 and reached its terminal"),
    ),
    "pause_prompt_args/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        _everywhere("agree on 1; baseline sent 1 and raised TypeError; now sent 7 and reached its terminal"),
    ),
    "pause_prompt_args/set": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        _everywhere("agree on 1; baseline sent 1 and raised TypeError; now sent 7 and reached its terminal"),
    ),
    "pause_prompt_content/raises_on_serialization": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        _everywhere("agree on 1; baseline sent 1 and raised RuntimeError; now sent 7 and reached its terminal"),
    ),
    "pause_prompt_content/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        _everywhere("agree on 1; baseline sent 1 and raised UnrenderableError; now sent 7 and reached its terminal"),
    ),
    "run_error_message/raises_on_serialization": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            None: "agree on 4; baseline sent 4 and raised RuntimeError; now sent 6 and reached its terminal",
            "inline": "agree on 4; baseline sent 4 and raised RuntimeError; now sent 6 and reached its terminal",
            "attributed": "agree on 5; baseline sent 5 and raised RuntimeError; now sent 8 and reached its terminal",
            "hidden": "agree on 1; baseline sent 1 and raised RuntimeError; now sent 2 and reached its terminal",
        },
    ),
    "run_error_message/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            None: "agree on 4; baseline sent 4 and raised UnrenderableError; now sent 6 and reached its terminal",
            "inline": "agree on 4; baseline sent 4 and raised UnrenderableError; now sent 6 and reached its terminal",
            "attributed": "agree on 5; baseline sent 5 and raised UnrenderableError; now sent 8 and reached its terminal",
            "hidden": "agree on 1; baseline sent 1 and raised UnrenderableError; now sent 2 and reached its terminal",
        },
    ),
    "run_error_lane_message/raises_on_serialization": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            None: "agree on 4; baseline sent 4 and raised RuntimeError; now sent 6 and reached its terminal",
            "inline": "agree on 4; baseline sent 4 and raised RuntimeError; now sent 6 and reached its terminal",
            "attributed": "agree on 5; baseline sent 5 and raised RuntimeError; now sent 8 and reached its terminal",
            "hidden": "agree on 1; baseline sent 1 and raised RuntimeError; now sent 2 and reached its terminal",
        },
    ),
    "run_error_lane_message/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            None: "agree on 4; baseline sent 4 and raised UnrenderableError; now sent 6 and reached its terminal",
            "inline": "agree on 4; baseline sent 4 and raised UnrenderableError; now sent 6 and reached its terminal",
            "attributed": "agree on 5; baseline sent 5 and raised UnrenderableError; now sent 8 and reached its terminal",
            "hidden": "agree on 1; baseline sent 1 and raised UnrenderableError; now sent 2 and reached its terminal",
        },
    ),
    "subagent_error_message/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            "attributed": "agree on 3; baseline sent 4 and raised RuntimeError; now sent 5 and reached its terminal",
            "hidden": "agree on 1; baseline sent 1 and raised RuntimeError; now sent 2 and reached its terminal",
        },
    ),
    "subagent_error_correlation/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            "attributed": "agree on 3; baseline sent 3 and raised RuntimeError; now sent 5 and reached its terminal",
            "hidden": "agree on 1; baseline sent 1 and raised RuntimeError; now sent 2 and reached its terminal",
        },
    ),
    "subagent_cancellation_reason/raises_an_unreadable_error": Intended(
        A_VALUE_THAT_CANNOT_BE_READ_NO_LONGER_ENDS_THE_RUN,
        {
            "attributed": "agree on 3; baseline sent 4 and raised RuntimeError; now sent 5 and reached its terminal",
            "hidden": "agree on 1; baseline sent 1 and raised RuntimeError; now sent 2 and reached its terminal",
        },
    ),
    "pause_tool_id/circular": Intended(
        A_PENDING_CALL_WITH_AN_UNUSABLE_ID_FAILS_UNDER_A_DIFFERENT_NAME,
        _everywhere("agree on 1; baseline sent 1 and raised ValidationError; now sent 1 and raised TypeError"),
    ),
    "pause_tool_id/set": Intended(
        A_PENDING_CALL_WITH_AN_UNUSABLE_ID_FAILS_UNDER_A_DIFFERENT_NAME,
        _everywhere("agree on 1; baseline sent 1 and raised ValidationError; now sent 1 and raised TypeError"),
    ),
    "shared-path/a_failed_run_whose_chunk_names_a_member": Intended(
        THE_VERBATIM_CHUNK_IS_WITHHELD_WHERE_NO_MEMBER_MAY_BE_NAMED,
        {"hidden": "agree on 1; baseline sent 2 and reached its terminal; now sent 2 and reached its terminal"},
    ),
    "shared-path/a_session_state_that_cannot_be_copied": Intended(
        THE_TERMINAL_STATE_SNAPSHOT_IS_DROPPED_RATHER_THAN_ENDING_THE_RUN,
        _everywhere("agree on 1; baseline sent 1 and raised RuntimeError; now sent 2 and reached its terminal"),
    ),
}


def _expected(name: str, visibility: Optional[str]) -> str:
    intended = INTENDED_DIFFERENCES.get(name)
    if intended is None:
        return IDENTICAL
    return intended.divergence.get(visibility, IDENTICAL)


def _servable(visibility: Optional[str]) -> bool:
    return visibility != SUBAGENT_VISIBILITY_ATTRIBUTED or ATTRIBUTED_IS_SERVABLE


_CASES = [pytest.param(name, builder, id=name) for name, builder in STREAMS]


# --- The sweep ---------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("name,builder", _CASES)
async def test_the_client_receives_what_it_received_before_the_outcome_existed(name, builder):
    """One stream, every visibility, both mappers, against the released interface.

    The visibilities and the mappers are walked inside one test rather than
    parametrized out, because what has to hold is that they all say the same
    thing: the setting is about a run's terminal and never about which mapper
    drove it, so the two mappers disagreeing is itself a defect and is reported
    as one here rather than as two unrelated failures.
    """
    for visibility in VISIBILITIES:
        if not _servable(visibility):
            continue
        stated = _expected(name, visibility)
        for mapper in MAPPERS:
            stream = builder()
            before, after = await through_both_trees(stream.chunks, stream.run_state, visibility, mapper)

            assert divergence(before, after) == stated, (
                f"the {mapper} mapper now sends something else for {name} under subagent_visibility="
                f"{visibility!r} with emit_interrupt_outcome off. With the outcome off a client has to "
                "receive the stream it received before the outcome existed. If this difference is meant, "
                f"state it in INTENDED_DIFFERENCES with the reason it is meant.\n"
                f"{where_they_part(before, after)}"
            )


class TestTheSweepCannotGoQuiet:
    """The sweep's own guards, since a comparison that stopped comparing looks green."""

    def test_every_stated_difference_names_a_stream_the_sweep_drives(self):
        """A stated difference for a stream nobody drives forgives nothing and hides that it does."""
        driven = {name for name, _ in STREAMS}
        assert sorted(set(INTENDED_DIFFERENCES) - driven) == []

    def test_every_stated_difference_gives_a_reason(self):
        for name, intended in INTENDED_DIFFERENCES.items():
            assert intended.reason.strip(), f"{name} is exempted from the comparison with no reason given"
            assert intended.divergence, f"{name} is listed as differing and names no visibility it differs under"

    def test_no_stated_difference_says_two_streams_are_identical(self):
        """``identical`` in the table is a difference blessed into invisibility."""
        said_twice = sorted(
            name for name, intended in INTENDED_DIFFERENCES.items() if IDENTICAL in intended.divergence.values()
        )
        assert said_twice == []

    def test_every_stream_the_reused_tables_hold_is_swept(self):
        """The enumerations are read, not listed, so an empty one would sweep nothing and pass.

        Counted against the tables rather than against a floor: a floor passes
        while a table is halved, and the whole reason these are read rather than
        listed is that the set has to follow them.
        """
        from_content = len(CONTENT_BOUNDARIES) * (1 + len(HOSTILE_VALUES))
        from_pauses = len(_PAUSE_SHAPES) + len(_PAUSES_NOTHING_CAN_ANSWER)
        assert len(STREAMS) == from_content + from_pauses + len(SHARED_PATH_STREAMS)
        assert len({name for name, _ in STREAMS}) == len(STREAMS), "two streams share a name, so one is unstated"

    def test_the_two_trees_are_not_the_same_module(self):
        """Every assertion above is vacuous if the baseline resolved to the live package."""
        assert baseline_stream_module is not live_stream_module
        assert baseline_run_entity is not live_run_entity
        assert baseline_stream_module.stream_agno_response_as_agui_events.__module__.startswith(
            agui_baseline_tree.BASELINE_PACKAGE
        )


class TestTheNormalisationIsNarrow:
    """What the one rewrite does and does not equate.

    A normalisation wide enough to hide a change is the way a comparison like this
    stops meaning anything, so the rule is held to what it claims: shape, and
    first-seen order.
    """

    def test_nothing_but_a_minted_id_is_rewritten(self):
        original = {"tool": "send_email", "count": 3, "flag": True, "nothing": None, "list": ["tc-a", 1.5]}
        assert aliased(copy.deepcopy(original), {}) == original

    def test_one_id_keeps_one_alias_wherever_it_appears(self):
        minted: Dict[str, str] = {}
        identifier = "11111111-2222-3333-4444-555555555555"
        assert aliased({"a": identifier, "b": [identifier]}, minted) == {"a": "minted-1", "b": ["minted-1"]}

    def test_two_ids_never_collapse_into_one(self):
        first = "11111111-2222-3333-4444-555555555555"
        second = "66666666-7777-8888-9999-000000000000"
        assert aliased([first, second, first], {}) == ["minted-1", "minted-2", "minted-1"]

    def test_a_stream_that_minted_one_more_id_is_not_equal_to_one_that_reused_it(self):
        """Which is what an interface minting an id where it used to reuse one looks like."""
        first = "11111111-2222-3333-4444-555555555555"
        second = "66666666-7777-8888-9999-000000000000"
        assert aliased([first, first], {}) != aliased([first, second], {})


class TestTheBaselineIsTheReleasedInterface:
    """The snapshot held against the commit it was taken from.

    Everything above compares this interface with a copy of the old one, which is
    worth exactly what that copy is worth. So the copy is checked back against the
    commit, whenever the checkout can still reach it. It will not always: this
    branch's history is not guaranteed to survive the way it lands. That is why
    the snapshot is checked in rather than read out of the commit at run time, and
    why this check skips where it cannot run instead of taking the comparison down
    with it.
    """

    def _at_the_baseline_commit(self, module: str) -> str:
        import subprocess

        path = f"{agui_baseline_tree.PACKAGE_PATH_IN_REPO}/{module}.py"
        found = subprocess.run(
            ["git", "show", f"{agui_baseline_tree.BASELINE_COMMIT}:{path}"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[5],
        )
        if found.returncode != 0:
            pytest.skip(f"this checkout cannot read {path} at {agui_baseline_tree.BASELINE_COMMIT}")
        return found.stdout

    def test_every_snapshot_module_is_the_file_that_was_released(self):
        for module, source in agui_baseline_tree.snapshot_sources().items():
            assert source == self._at_the_baseline_commit(module), (
                f"the checked-in baseline of {module}.py is not what {agui_baseline_tree.BASELINE_COMMIT} "
                "released, so the comparison above is against something nobody shipped"
            )

    def test_the_snapshot_covers_the_whole_package(self):
        """A module left out would resolve to today's, and compare it with itself."""
        live = {path.stem for path in Path(live_stream_module.__file__).parent.glob("*.py")}
        snapshot = set(agui_baseline_tree.snapshot_sources())
        assert sorted(live - snapshot) == ["interrupts"], (
            "the package gained a module the baseline does not have a copy of, so the baseline imports today's"
        )

    def test_the_rewrite_touches_only_this_packages_own_imports(self):
        """The one edit made on the way in, held to being the one it claims."""
        for module, source in agui_baseline_tree.snapshot_sources().items():
            rewritten = agui_baseline_tree.rewritten(source)
            assert agui_baseline_tree.LIVE_PACKAGE not in rewritten, f"{module}.py still imports the live package"
            assert rewritten == source.replace(agui_baseline_tree.LIVE_PACKAGE, agui_baseline_tree.BASELINE_PACKAGE), (
                f"the rewrite of {module}.py changed something other than the package it names"
            )


# --- A terminal that cannot be built at all ----------------------------------


class _TerminalBoom(Exception):
    pass


def _the_terminal_explodes(*_: Any, **__: Any) -> Any:
    raise _TerminalBoom("terminal exploded")


def _a_run_that_pauses_mid_message() -> List[Any]:
    """A run holding an open message and an open tool call when its terminal is built."""
    from .test_agui_interrupts import _mid_message_pause_chunks

    return _mid_message_pause_chunks()


class TestATerminalThatCannotBeBuilt:
    """The one shared-path change that no stream reaches without a fault injected.

    The terminal used to sit outside the guard that closes what the stream opened,
    so a raise from it sent no span end and no terminal. Reaching that needs the
    terminal to raise, which is a fault rather than a value, so it is driven by
    the same injection in both trees rather than written into the table above.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mapper", MAPPERS)
    async def test_the_spans_the_run_left_open_are_now_closed_before_the_failure(self, mapper, monkeypatch, caplog):
        monkeypatch.setattr(live_stream_module, "process_completion", _the_terminal_explodes)
        monkeypatch.setattr(baseline_stream_module, "process_completion", _the_terminal_explodes)

        before, after = await through_both_trees(_a_run_that_pauses_mid_message(), None, None, mapper)

        assert before.failure == after.failure, "the failure a client is told about changed"
        assert [event["type"] for event in after.events[len(before.events) :]] == [
            "TOOL_CALL_END",
            "TEXT_MESSAGE_END",
        ], "the spans the baseline left open are not the ones this interface closes"
        assert after.events[: len(before.events)] == before.events, (
            "closing the open spans changed something the baseline had already sent"
        )


# --- Where the line falls: the route ------------------------------------------

PAUSED_REQUIREMENT_ID = "11111111-2222-3333-4444-555555555555"
PAUSED_CALL_ID = "tc-paused"


class _RecordingEntity(Agent):
    """An Agent that answers the route and records what it was asked to do.

    The route's own decisions are what this class is here to read. Its run is a
    fixed chunk list, so the body is the same on both trees by construction and
    the only thing left to compare is the call the route made.
    """

    def __init__(self) -> None:
        super().__init__(name="Recorder", id="recorder", db=InMemoryDb())
        self.asked: List[Tuple[str, Dict[str, Any]]] = []

    def _one_run(self) -> Any:
        async def source() -> AsyncIterator[Any]:
            yield RunStartedEvent(run_id="paused-run")
            yield RunCompletedEvent(content="done", run_id="paused-run")

        return source()

    def _record(self, call: str, kwargs: Dict[str, Any]) -> Any:
        # Only what the route decided, not the objects it built: a RunContext and
        # a requirement list are compared by identity and would report every call
        # as different.
        readable = {key: value for key, value in kwargs.items() if isinstance(value, (str, bool, int, type(None)))}
        self.asked.append((call, readable))
        return self._one_run()

    def arun(self, **kwargs: Any) -> Any:
        return self._record("arun", kwargs)

    def acontinue_run(self, **kwargs: Any) -> Any:
        return self._record("acontinue_run", kwargs)

    async def aget_session(self, session_id: Optional[str] = None, **_: Any) -> Any:
        requirement = RunRequirement(
            tool_execution=ToolExecution(
                tool_call_id=PAUSED_CALL_ID, tool_name="send_email", requires_confirmation=True
            )
        )
        requirement.id = PAUSED_REQUIREMENT_ID
        return AgentSession(
            session_id=session_id,
            runs=[RunOutput(run_id="paused-run", status=RunStatus.paused, requirements=[requirement])],
        )


def _request(**overrides: Any) -> RunAgentInput:
    fields: Dict[str, Any] = dict(
        thread_id=THREAD_ID,
        run_id="request-1",
        state={},
        messages=[UserMessage(id="m1", role="user", content="go")],
        tools=[],
        context=[],
        forwarded_props={},
    )
    fields.update(overrides)
    return RunAgentInput(**fields)


_CARRIES_CONTEXT = [{"description": "the caller's own context", "value": "kept"}]
_ANSWERS_THE_CALL = ToolMessage(id="t1", role="tool", tool_call_id=PAUSED_CALL_ID, content='{"accepted": true}')


async def _through_both_routes(request: RunAgentInput) -> Tuple[Tuple[Received, List[Any]], Tuple[Received, List[Any]]]:
    """One request through both routes, each against its own recorder."""
    results = []
    for route in (baseline_run_entity, live_run_entity):
        entity = _RecordingEntity()
        kwargs: Dict[str, Any] = {}
        if route is live_run_entity:
            kwargs["emit_interrupt_outcome"] = THE_OUTCOME_IS_OFF
        events = [event async for event in route(entity, request, **kwargs)]
        results.append((received(events, None), entity.asked))
    return results[0], results[1]


class TestTheRouteChoosesWhatItChose:
    """Where identity stops being about emission.

    The two things the route now decides differently are decisions rather than
    events: they change what the entity is asked to do, which a scripted entity's
    stream cannot show and a real run would. So they are read off the call the
    route made, and both are stated here rather than left to be noticed.
    """

    @pytest.mark.asyncio
    async def test_a_fresh_run_is_asked_for_in_the_same_words(self):
        (before_body, before_asked), (after_body, after_asked) = await _through_both_routes(_request())

        assert after_asked == before_asked
        assert after_body == before_body

    @pytest.mark.asyncio
    async def test_a_fresh_run_carrying_context_still_gets_the_dependency_option(self):
        """The option belongs to the branch that builds a user message, which this is."""
        (_, before_asked), (_, after_asked) = await _through_both_routes(_request(context=_CARRIES_CONTEXT))

        assert before_asked[0][1]["add_dependencies_to_context"] is True
        assert after_asked == before_asked

    @pytest.mark.asyncio
    async def test_a_resume_is_continued_in_the_same_words(self):
        request = _request(messages=[UserMessage(id="m1", role="user", content="go"), _ANSWERS_THE_CALL])

        (before_body, before_asked), (after_body, after_asked) = await _through_both_routes(request)

        assert [call for call, _ in after_asked] == ["acontinue_run"]
        assert after_asked == before_asked
        assert after_body == before_body

    @pytest.mark.asyncio
    async def test_a_resume_carrying_context_no_longer_gets_the_fresh_run_option(self):
        """The first of the two intended route differences.

        A continue replays the paused run's stored messages instead of building a
        user message, so the option that decides how one is built had nothing to
        act on there. The request's context still reaches the resumed run through
        the run context, which is why dropping the option takes nothing away.
        """
        request = _request(
            messages=[UserMessage(id="m1", role="user", content="go"), _ANSWERS_THE_CALL],
            context=_CARRIES_CONTEXT,
        )

        (_, before_asked), (_, after_asked) = await _through_both_routes(request)

        assert before_asked[0][1]["add_dependencies_to_context"] is True
        assert "add_dependencies_to_context" not in after_asked[0][1]
        # Nothing else about the call moved with it.
        assert [call for call, _ in after_asked] == [call for call, _ in before_asked]
        assert {key: value for key, value in before_asked[0][1].items() if key != "add_dependencies_to_context"} == (
            after_asked[0][1]
        )

    @pytest.mark.asyncio
    async def test_an_answer_in_the_resume_array_now_continues_the_run(self):
        """The second, and the one a released client cannot reach.

        The array is how a client answers the interrupts a terminal advertised,
        and with the outcome off this interface advertises none, so nothing it
        sends can prompt one. A client that sends one anyway used to get a fresh
        run, with its answers silently unread.
        """
        request = _request(
            resume=[{"interrupt_id": PAUSED_REQUIREMENT_ID, "status": "resolved", "payload": {"accepted": True}}]
        )

        (_, before_asked), (_, after_asked) = await _through_both_routes(request)

        assert [call for call, _ in before_asked] == ["arun"]
        assert [call for call, _ in after_asked] == ["acontinue_run"]
