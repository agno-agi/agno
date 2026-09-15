"""The AG-UI interrupt round trip over the AGUI interface.

The failure this covers is a pause that looks convincing and then continues
nothing, so the suite is written in two halves that have to agree.

Out: a paused run's terminal says the run is waiting, once per requirement it
still needs answered, each naming the tool call it is bound to and the shape of
the answer it wants. Off by default, where the stream stays exactly what it was.

In: the answers come back in the request's resume array and the paused run
continues from them. That half is driven over a real ``POST /agui`` against a
real Agent and Team, because the only proof that a resume continued the run is
the tool body running and its result reaching the wire under the id the pause
reported.
"""

import ast
import asyncio
import importlib
import inspect
import json
import logging
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, get_args, get_type_hints
from uuid import uuid4

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import BaseEvent, Event, EventType, RunAgentInput, RunFinishedEvent, UserMessage
from pydantic import BaseModel, TypeAdapter, create_model

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.response import ToolExecution, UserInputField
from agno.os.interfaces.agui import interrupts
from agno.os.interfaces.agui import resume as resume_module
from agno.os.interfaces.agui import stream as stream_module
from agno.os.interfaces.agui.handlers import on_run_completed as _build_the_run_terminal
from agno.os.interfaces.agui.resume import (
    ADVERTISED_KEYWORDS_READ,
    CANCELLED_NOTE,
    SCHEMA_ADVERTISED_ONLY,
    ensure_requirements_resolved,
    resolve_requirements_from_resume_entries,
    resolve_requirements_from_tool_messages,
)

# Every source of a stream is wrapped below, under the name this suite calls it
# by, so the unwrapped one must not also be reachable under that name. Which
# names those are is derived from these imports rather than listed, at the end
# of this file.
from agno.os.interfaces.agui.router import run_entity as _run_entity
from agno.os.interfaces.agui.state import (
    SUBAGENT_VISIBILITY_ATTRIBUTED,
    SUBAGENT_VISIBILITY_VALUES,
    StreamState,
)
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunEvent,
    RunPausedEvent,
    RunStartedEvent,
    ToolCallStartedEvent,
)
from agno.run.requirement import RunRequirement
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent
from agno.team import Team
from agno.tools import tool
from agno.tools.function import Function, UserFeedbackOption, UserFeedbackQuestion
from agno.tools.user_feedback import UserFeedbackTools

from .agui_stream_invariants import (
    A_CALL_PROMPTED_ONCE_PER_PAUSE_KIND,
    ABANDONED_MID_STREAM,
    RaisesOnSerialization,
    ScriptedModel,
    assert_stream_contains,
    assert_stream_is_malformed_as_recorded,
    assert_well_formed_stream,
    attributed,
    captured_agno_logs,
    circular,
    in_emitted_order,
    member_mentions,
    of_type,
    require_lineage_events,
    short_type,
    sse_events,
)
from .agui_stream_invariants import collect_async as _collect_async
from .agui_stream_invariants import collect_sync as _collect_sync

THREAD_ID = "interrupt-session"
RUN_ID = "interrupt-run"


def on_run_completed(
    chunk: Any,
    state: StreamState,
    *,
    malformed: Optional[str] = None,
    encoder_refuses: Sequence[str] = (),
) -> List[Any]:
    """The interface's own run terminal, with the stream it built held to the invariants.

    Named over the import so that every call in this suite, and every call a
    later test adds, reaches the shared definition of a well-formed stream
    without opting in. Which helper a test happened to reach for is what decided
    that before: the route harness checked its bodies and this path checked
    nothing, so one guard in this directory could bless a stream the other
    rejects with nothing saying so.

    ``malformed`` names the record for a stream this interface really does emit
    malformed today, which pins the violation rather than waiving it.

    A stream recorded as malformed is still held to what it encoded: the
    violations recorded there are about the order and pairing of events, and a
    key no model declares is a defect under any ordering.

    ``encoder_refuses`` names the paths of the values the protocol's encoder
    refuses in this stream, for a caller whose subject is a run holding one.
    """
    events = _build_the_run_terminal(chunk, state)
    if malformed is None:
        assert_well_formed_stream(events)
    else:
        assert_stream_is_malformed_as_recorded(events, malformed)
    _assert_nothing_undeclared_reached_the_client(events, encoder_refuses)
    return events


async def collect_async(chunks: Any, *args: Any, encoder_refuses: Sequence[str] = (), **kwargs: Any) -> Any:
    """The shared async driver, with the stream it produced held to what it encoded.

    Named over the import for the reason the run terminal above is: a test
    reaching the driver directly gets a stream nothing checks the encoded keys
    of, and the whole point of that check is that no call site can skip it.
    """
    events, error = await _collect_async(chunks, *args, **kwargs)
    _assert_nothing_undeclared_reached_the_client(events, encoder_refuses)
    return events, error


async def collect_sync(chunks: Any, *args: Any, encoder_refuses: Sequence[str] = (), **kwargs: Any) -> Any:
    """The shared sync-mapper driver, wrapped for the same reason as the async one."""
    events, error = await _collect_sync(chunks, *args, **kwargs)
    _assert_nothing_undeclared_reached_the_client(events, encoder_refuses)
    return events, error


async def run_entity(*args: Any, encoder_refuses: Sequence[str] = (), **kwargs: Any) -> List[Any]:
    """The route's own mapping of an entity's run, collected and held to both checks.

    The fourth way this suite obtains a stream, and the one that reached only
    half of them: it was driven under the interface's own name, so no wrapper
    stood between it and a caller, and a body the route really sends went unheld
    to the keys it encoded while every other stream here was held to them.

    The whole body rather than each event as it arrives, because a stream is
    well formed or not only once it has ended.
    """
    events = [event async for event in _run_entity(*args, **kwargs)]
    assert_well_formed_stream(events)
    _assert_nothing_undeclared_reached_the_client(events, encoder_refuses)
    return events


# The three pieces of the round trip reached the protocol in three separate
# releases, and the package's own extra permits a release older than all of
# them, so each is gated on its own. Every gate asks the probe the interface
# decides that one piece by: the import flag for the lifecycle, which is what
# the builders check, and the field tables for the two later pieces, because a
# release can declare a type and still omit the field this module writes on it.
needs_interrupt_outcome = pytest.mark.skipif(
    not interrupts.INTERRUPT_OUTCOME_AVAILABLE,
    reason="the installed ag_ui.core has no interrupt-aware run lifecycle",
)
needs_member_attribution = pytest.mark.skipif(
    not interrupts.interrupt_attribution_available(),
    reason="the installed ag_ui.core cannot name the member an interrupt was raised inside",
)
needs_suspended_outcome = pytest.mark.skipif(
    not interrupts.subagent_suspension_available(),
    reason="the installed ag_ui.core cannot serve the suspended subagent outcome",
)


def _resume_array_is_readable() -> bool:
    """Whether a request can carry a client's answers at all.

    The interface reads the array off the parsed request through an attribute
    lookup, so on a release that does not declare the field the answers arrive
    as an unknown key and are dropped. The field's presence is therefore the
    probe, which is how the interrupt floor reads it too, and it is a piece of
    its own: an install can declare it without the interrupt types, and that is
    the install the tests below prove the array is read on.
    """
    from ag_ui.core import RunAgentInput

    return "resume" in RunAgentInput.model_fields


RESUME_ARRAY_IS_READABLE = _resume_array_is_readable()

needs_resume_array = pytest.mark.skipif(
    not RESUME_ARRAY_IS_READABLE,
    reason="the installed ag_ui.core has no resume array for a client's answers to arrive in",
)


# --- Building a pause the way a real run reports one -------------------------


def _confirmation(tool_call_id: str = "tc-confirm", tool_name: str = "send_email") -> ToolExecution:
    return ToolExecution(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_args={"to": "ops@example.com"},
        requires_confirmation=True,
    )


def _external(tool_call_id: str = "tc-external", tool_name: str = "change_background") -> ToolExecution:
    return ToolExecution(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_args={"color": "blue"},
        external_execution_required=True,
    )


def _user_input(fields: Optional[List[UserInputField]] = None) -> ToolExecution:
    return ToolExecution(
        tool_call_id="tc-input",
        tool_name="write_post",
        tool_args={},
        requires_user_input=True,
        user_input_schema=fields
        if fields is not None
        else [UserInputField(name="topic", field_type=str, description="What to write about")],
    )


def _user_feedback(multi_select: bool = False) -> ToolExecution:
    return ToolExecution(
        tool_call_id="tc-feedback",
        tool_name="ask_user",
        tool_args={},
        requires_user_input=True,
        user_feedback_schema=[
            UserFeedbackQuestion(
                question="What budget?",
                header="Budget",
                options=[UserFeedbackOption(label="low"), UserFeedbackOption(label="high")],
                multi_select=multi_select,
            )
        ],
    )


def _two_pause_kinds() -> ToolExecution:
    """One pending call flagged for two pause kinds, which the prompt lists twice.

    The prompt has always shown it once per list it appears on. Nothing can
    answer it: the resume channel runs one resolver per requirement, picked by
    pause kind, and whichever it picks leaves the other kind open.
    """
    return ToolExecution(
        tool_call_id="tc-both",
        tool_name="send_email",
        tool_args={"to": "ops@example.com"},
        requires_confirmation=True,
        requires_user_input=True,
        user_input_schema=[UserInputField(name="body", field_type=str)],
    )


def _answered_its_questions_and_still_waits_on_a_decision() -> ToolExecution:
    """A pause whose kind picks the one resolver that has nothing left to give it.

    ``pause_type`` reads the feedback schema first and its questions are answered
    already, so the resolver the resume channel runs is the one Agno refuses to
    run at all, while the decision it is really waiting on stays open.
    """
    answered = UserFeedbackQuestion(question="What budget?", options=[UserFeedbackOption(label="low")])
    answered.selected_options = ["low"]
    return ToolExecution(
        tool_call_id="tc-answered-feedback",
        tool_name="send_email",
        tool_args={},
        requires_confirmation=True,
        user_feedback_schema=[answered],
    )


def _asks_a_question_while_a_field_it_needs_stays_empty() -> ToolExecution:
    """One call waiting on a selection and on a value, which one answer cannot give.

    Agno marks a call answered once its questions are, and that one flag stands
    for both structured kinds, so the feedback resolver clears the input the
    tool is still missing without anything having filled it.
    """
    return ToolExecution(
        tool_call_id="tc-feedback-and-input",
        tool_name="book_trip",
        tool_args={},
        requires_user_input=True,
        user_feedback_schema=[UserFeedbackQuestion(question="What budget?", options=[UserFeedbackOption(label="low")])],
        user_input_schema=[UserInputField(name="city", field_type=str)],
    )


def _filled_a_field_no_answer_could_name() -> ToolExecution:
    """A pause whose one field cannot be named and already carries a value.

    Nothing of it is still empty, so a census of the empty fields finds nothing
    to report, while the field itself is one no payload can be keyed to and the
    schema built from it describes nothing at all.
    """
    unnameable = UserInputField(name="", field_type=str)
    unnameable.value = "prefilled"
    return _user_input([unnameable])


def _waits_on_two_fields_no_answer_could_name() -> ToolExecution:
    """A pause with one field a client can fill and two it cannot name."""
    return _user_input(
        [
            UserInputField(name="topic", field_type=str),
            UserInputField(name="", field_type=str),
            UserInputField(name="", field_type=str),
        ]
    )


def _user_feedback_offering(*options: UserFeedbackOption) -> ToolExecution:
    """A feedback pause asking one question over exactly these options."""
    return ToolExecution(
        tool_call_id="tc-feedback",
        tool_name="ask_user",
        tool_args={},
        requires_user_input=True,
        user_feedback_schema=[UserFeedbackQuestion(question="What budget?", options=list(options))],
    )


def _paused(*tools: ToolExecution, content: Optional[str] = None) -> RunPausedEvent:
    """An Agent pause reported the way a real run reports one.

    A real pause carries the pending calls on the terminal's own lists AND a
    requirement per call, which is what says the pause kind and the answer shape.
    A pause built from the tool list alone is a different subject, and the tests
    whose subject that is build it themselves.
    """
    return RunPausedEvent(
        tools=list(tools),
        requirements=[RunRequirement(tool_execution=tool) for tool in tools],
        content=content,
    )


def _member_paused(*tools: ToolExecution, member_run_id: str, member_id: str = "mailer") -> TeamRunPausedEvent:
    """A Team pause whose pending calls belong to a member, as a real one reports it."""
    requirements = []
    for pending in tools:
        requirement = RunRequirement(tool_execution=pending)
        requirement.member_agent_id = member_id
        requirement.member_agent_name = "Mailer"
        requirement.member_run_id = member_run_id
        requirements.append(requirement)
    return TeamRunPausedEvent(tools=[], requirements=requirements)


def _member_paused_on_something_nothing_can_answer() -> TeamRunPausedEvent:
    """A Team pause waiting on a member, on a call no client could ever answer.

    One pending call flagged for two pause kinds, which is the shape that ends
    the run instead of prompting for it. The terminal is then a failed run
    reporting the chunk it ended on, and that chunk is the leader's own while
    carrying the member's id, name and run id inside it.
    """
    return _member_paused(_two_pause_kinds(), member_run_id="member-run")


def _how_a_pause_names_its_member(chunk: Any) -> List[str]:
    """Every value the pause itself names its member by.

    Read off the fixture rather than written out beside it, so an assertion that
    none of them reached a client cannot pass by looking for a string this pause
    never carried.
    """
    named = [
        str(value)
        for requirement in chunk.requirements or []
        for value in (requirement.member_agent_id, requirement.member_agent_name, requirement.member_run_id)
        if value
    ]
    assert named, "this pause names no member, so an assertion that nothing named one proves nothing"
    return named


def _paused_inside_an_inner_agent(member_run_id: str = "inner-run") -> RunPausedEvent:
    """An Agent pause whose only pending call arrives on the requirement list.

    An agent that ran an inner agent reports a pending call exactly as a team
    reports a member's: the terminal's own tool lists carry nothing, and the
    requirement names the run that is really waiting.
    """
    requirement = RunRequirement(tool_execution=_confirmation("tc-inner"))
    requirement.member_agent_id = "inner"
    requirement.member_agent_name = "Inner"
    requirement.member_run_id = member_run_id
    return RunPausedEvent(tools=[], requirements=[requirement])


def _paused_where_two_requirements_share_one_id() -> RunPausedEvent:
    """A pause whose two open requirements are keyed by the same interrupt id.

    One correlation key for two answers: the resume channel looks an answer up
    by id, so it would resolve whichever requirement the lookup found and leave
    the other open. A release that stores no requirement id keys by the tool call
    instead, which is where two requirements waiting on one call collide.
    """
    decide = _confirmation("tc-shared")
    run_it = _external("tc-shared", "change_background")
    requirements = [RunRequirement(tool_execution=decide), RunRequirement(tool_execution=run_it)]
    for requirement in requirements:
        requirement.id = None
    return RunPausedEvent(tools=[decide, run_it], requirements=requirements)


def _paused_listing_a_call_with_nothing_open_behind_it() -> RunPausedEvent:
    """A pause listing a pending call whose answer the run already holds.

    The terminal's own lists are the record of what the client is shown, and a
    call on one of them can have no open requirement behind it. There is then
    nothing for the resume channel to look an answer up by.
    """
    open_call = _confirmation("tc-open")
    decided = _confirmation("tc-decided", "archive_email")
    decided.confirmed = True
    return RunPausedEvent(
        tools=[open_call, decided],
        requirements=[RunRequirement(tool_execution=open_call), RunRequirement(tool_execution=decided)],
    )


def _run_finished(events: List[Any]) -> Any:
    finished = [event for event in events if type(event).__name__ == "RunFinishedEvent"]
    assert len(finished) == 1, f"expected exactly one run terminal, got {[type(e).__name__ for e in events]}"
    return finished[0]


def _encoded(event: Any) -> Dict[str, Any]:
    """One event as the bytes a client receives, read back as the keys they carry.

    Through the protocol's own encoder, which is what the route hands the client:
    a field the models do not declare still sets an attribute, so reading the
    object cannot tell what reached the client from what did not.
    """
    from ag_ui.encoder import EventEncoder

    return json.loads(EventEncoder().encode(event)[len("data: ") :])


def _outcome_on_the_wire(event: Any) -> Any:
    """The outcome as a client reads it, which is the encoded event and not the object."""
    return _encoded(event).get("outcome", "absent")


def _everything_the_client_received(events: List[Any]) -> str:
    """A whole stream as the bytes a client receives, for an assertion about an absence.

    Read off the encoded events and not the objects, and off all of them rather
    than the fields a test thought to look at: a value nested anywhere inside an
    event's payload is on the wire whether or not a field of that event names it.
    """
    return json.dumps([_encoded(event) for event in events])


# --- The invariant over what the stream encoded ------------------------------

# Eight times now this interface has written a protocol field the installed
# models do not declare, three of them while fixing the last round of the same
# thing. The models keep such a key as untyped extra data and serialize it, so
# it leaves the server under a name the wire format has no place for and a
# client reads a field that is not one. Per-field vigilance is what failed
# eight times, so what follows is a property of the encoded output instead: it
# holds over every stream this suite produces and cannot be forgotten at a call
# site nobody thought to check.


def _declared_wire_keys(model: Any) -> Dict[str, str]:
    """Serialized key -> field name, for every field this model declares.

    Both spellings, because a producer chooses between the field name and its
    alias and a key under either is one the model declares.
    """
    keys: Dict[str, str] = {}
    for name, field in type(model).model_fields.items():
        keys[name] = name
        for alias in (field.alias, field.serialization_alias):
            if alias:
                keys[alias] = name
    return keys


def _undeclared_keys_under(model: BaseModel, encoded: Dict[str, Any], path: str) -> List[str]:
    declared = _declared_wire_keys(model)
    found: List[str] = []
    for key, value in encoded.items():
        if key not in declared:
            found.append(f"{path}.{key}")
            continue
        found += _undeclared_keys_in(getattr(model, declared[key], None), value, f"{path}.{key}")
    return found


def _undeclared_keys_in(written: Any, encoded: Any, path: str) -> List[str]:
    """Every undeclared key under one written value, paired with what it encoded to.

    The written object is what says which model a nested payload belongs to. A
    value that is not a protocol model carries no declaration to be held to, so
    it ends the descent: an open-by-key metadata object is data the client reads
    whole, not a schema.
    """
    if isinstance(written, BaseModel) and isinstance(encoded, dict):
        return _undeclared_keys_under(written, encoded, path)
    if isinstance(written, (list, tuple)) and isinstance(encoded, list):
        return [
            entry
            for index, (one, its) in enumerate(zip(written, encoded))
            for entry in _undeclared_keys_in(one, its, f"{path}[{index}]")
        ]
    if isinstance(written, dict) and isinstance(encoded, dict):
        return [
            entry
            for key, value in encoded.items()
            if key in written
            for entry in _undeclared_keys_in(written[key], value, f"{path}.{key}")
        ]
    return []


# A value the protocol's encoder refuses never reaches a client: the response
# body dies where that event should have been. The keys around such a value are
# still this interface's to get right, and an event the check gives up on is a
# check that stops reading exactly where a run's content turns hostile. So an
# event the encoder refuses is encoded a second time with those values stood in
# for. A stand-in sits at a leaf and can neither add nor remove a key, so the
# walk still reads the key set the client would have seen, and the paths the
# stand-ins sat at are reported so nothing is passed over in silence.


def _paths_the_encoder_refused(encoded: Any, stood_in_for: str, path: str) -> List[str]:
    if isinstance(encoded, str):
        return [path] if encoded == stood_in_for else []
    if isinstance(encoded, dict):
        # A key can be stood in for as readily as a value, and a key the encoder
        # refuses is the case that changes the key set the walk reads.
        return [
            found
            for key, value in encoded.items()
            for found in (
                [f"{path}.<a key the encoder refused>"]
                if key == stood_in_for
                else _paths_the_encoder_refused(value, stood_in_for, f"{path}.{key}")
            )
        ]
    if isinstance(encoded, list):
        return [
            found
            for index, value in enumerate(encoded)
            for found in _paths_the_encoder_refused(value, stood_in_for, f"{path}[{index}]")
        ]
    return []


def _encoded_as_far_as_it_reads(event: Any) -> Tuple[Dict[str, Any], List[str]]:
    """One event's encoded keys, and the path of every value the encoder refused.

    The protocol's own encoder first, so a stream with nothing hostile in it is
    read exactly as a client reads it. Only an event that encoder refuses is
    re-encoded with stand-ins, and an event that cannot be read even that way is
    named whole rather than counted clean.
    """
    try:
        return _encoded(event), []
    except Exception:
        pass
    stood_in_for = f"<a value the encoder refused {uuid4()}>"
    try:
        payload = json.loads(event.model_dump_json(by_alias=True, fallback=lambda _: stood_in_for))
    except Exception as refused_outright:
        # Named by type: rendering this exception reads the value that raised.
        return {}, [f"{type(event).__name__}: no key of this event could be read ({type(refused_outright).__name__})"]
    return payload, _paths_the_encoder_refused(payload, stood_in_for, type(event).__name__)


def _what_the_stream_encoded(events: Sequence[Any]) -> Tuple[List[str], List[str]]:
    """(keys no model declares, paths the encoder refused) over one stream."""
    undeclared: List[str] = []
    refused: List[str] = []
    for event in events:
        encoded, paths = _encoded_as_far_as_it_reads(event)
        undeclared += _undeclared_keys_under(event, encoded, type(event).__name__)
        refused += paths
    return undeclared, refused


def undeclared_keys_on_the_wire(events: Sequence[Any]) -> List[str]:
    """Every key this stream encoded that the model it came from does not declare.

    What it cannot see: a declared field carrying a wrong or null value, and
    anything inside an open-by-key object such as an interrupt's metadata, whose
    keys are this interface's own and are declared nowhere. It reads the models
    the installed release presents, so it says what this install would send and
    not what an older one would.

    A value the encoder refuses is stood in for, so the keys around it are read.
    Which keys went unread is the other half of the answer, and
    ``values_the_encoder_refused`` is where a caller gets it.
    """
    return _what_the_stream_encoded(events)[0]


def values_the_encoder_refused(events: Sequence[Any]) -> List[str]:
    """Every path in this stream holding a value the protocol's encoder refuses."""
    return _what_the_stream_encoded(events)[1]


def _assert_nothing_undeclared_reached_the_client(events: Sequence[Any], encoder_refuses: Sequence[str] = ()) -> None:
    """Held to the keys the stream encoded, and to the values it could not encode.

    A refused value is not a clean bill of health: the keys around it were read,
    the subtree under it was not, and the client is served no such event at all.
    So it fails here unless the caller names the paths its stream means to
    produce, which pins the refusal where a reader can see it. Named and refused
    have to match both ways, so a pin that stops being true fails too.
    """
    undeclared, refused = _what_the_stream_encoded(events)
    assert undeclared == [], f"the encoded stream carries keys no protocol model declares: {undeclared}"
    assert sorted(refused) == sorted(encoder_refuses), (
        "this stream holds values the protocol's encoder refuses, which are not the ones it says it holds: "
        f"refused {sorted(refused)}, named {sorted(encoder_refuses)}"
    )


def _subagent_terminals(events: List[Any]) -> List[Any]:
    """The member terminals that closed as finished, for a test that reads one.

    Not what a privacy assertion asks: a stream that named a member some other
    way carries none of these. That question is ``member_mentions``, which reads
    every way one stream can name a member.
    """
    return [event for event in events if type(event).__name__ == "SubagentFinishedEvent"]


# --- The default: a pause reaches the client as it always has ----------------


class TestOutcomeIsOffByDefault:
    def test_a_pause_carries_no_outcome(self):
        events = on_run_completed(_paused(_confirmation()), StreamState())
        assert _outcome_on_the_wire(_run_finished(events)) == "absent"

    @pytest.mark.parametrize(
        "pending",
        [_confirmation(), _external(), _user_input(), _user_feedback()],
        ids=["confirmation", "external_execution", "user_input", "user_feedback"],
    )
    def test_no_pause_kind_carries_an_outcome(self, pending):
        events = on_run_completed(_paused(pending), StreamState())
        assert _outcome_on_the_wire(_run_finished(events)) == "absent"

    @pytest.mark.parametrize(
        ("pending", "malformed"),
        [
            (_two_pause_kinds(), A_CALL_PROMPTED_ONCE_PER_PAUSE_KIND),
            (_user_input([]), None),
        ],
        ids=["one_call_for_two_pause_kinds", "no_field_to_answer_in"],
    )
    def test_a_pause_nothing_can_answer_still_finishes(self, pending, malformed):
        """A pause no client could answer reaches this default unchanged.

        With the outcome on it ends the run, because nothing would continue it.
        With it off this interface advertises nothing and makes no claim about
        what a resume must carry, so the pause reaches the client as the finished
        run it always did. Which for the call listed by two pause kinds is a
        stream this directory's own invariants reject, pinned to the violation it
        breaks rather than passing unseen.
        """
        events = on_run_completed(_paused(pending), StreamState(), malformed=malformed)

        assert _outcome_on_the_wire(_run_finished(events)) == "absent"

    def test_the_prompt_a_call_listed_twice_produces_is_unchanged(self):
        """A call flagged for two pause kinds is listed by each, and prompted twice.

        With the outcome off, which is the stream this interface has always sent,
        that pause reaches the client exactly as it did: the terminal makes no
        claim about what a resume must carry, so nothing about the pause is
        refused. With the outcome on, no answer resolves such a call and the run
        ends instead, which the section on a pause no answer could resolve
        drives.

        Which is a stream the directory's own definition of a well-formed one
        rejects, and says so here rather than passing because this test builds
        its events by a path that used to reach no checker.
        """
        events = on_run_completed(
            _paused(_two_pause_kinds()),
            StreamState(),
            malformed=A_CALL_PROMPTED_ONCE_PER_PAUSE_KIND,
        )

        started = [event.tool_call_id for event in events if type(event).__name__ == "ToolCallStartEvent"]
        assert started == ["tc-both", "tc-both"]
        assert _outcome_on_the_wire(_run_finished(events)) == "absent"

    def test_the_interface_defaults_to_off(self):
        from agno.os.interfaces.agui import AGUI

        assert AGUI(agent=Agent(name="A")).emit_interrupt_outcome is False

    @pytest.mark.asyncio
    async def test_a_suspended_member_still_finishes_plainly(self):
        """With the outcome off, a member the run paused inside closes as it always did.

        The two halves are one setting: a lane closed as suspended beside a run
        terminal that reports a completion tells a client the member is waiting
        on a run that says it finished.

        Gated on the lineage events it needs a member terminal from, and on
        nothing else: an install that cannot serve the suspended outcome is one
        where this promise still holds and is still worth proving.
        """
        require_lineage_events()
        events, error = await collect_async(
            [_member_paused(_confirmation(), member_run_id="member-run")],
            attributed(),
            thread_id=THREAD_ID,
            run_id=RUN_ID,
        )
        assert error is None
        # Both halves, because the promise is about the pair: a member closing
        # as waiting is only wrong beside a run terminal that says it finished.
        assert [_outcome_on_the_wire(terminal) for terminal in _subagent_terminals(events)] == ["absent"]
        assert _outcome_on_the_wire(_run_finished(events)) == "absent"


# --- The outcome a pause carries when it is asked for ------------------------


@needs_interrupt_outcome
class TestInterruptOutcome:
    def test_a_completed_run_still_carries_no_outcome(self):
        """The setting speaks about pauses only, exactly as the reference bridges do."""
        events = on_run_completed(RunCompletedEvent(), StreamState(emit_interrupt_outcome=True))
        assert _outcome_on_the_wire(_run_finished(events)) == "absent"

    def test_a_pause_says_the_run_is_waiting(self):
        chunk = _paused(_confirmation())
        events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True))

        outcome = _outcome_on_the_wire(_run_finished(events))
        assert outcome["type"] == "interrupt"
        assert [interrupt["id"] for interrupt in outcome["interrupts"]] == _accepted_by_the_resume_side(chunk)

    def test_the_paused_runs_own_words_are_the_message_the_pending_call_hangs_from(self):
        """Which is why no interrupt carries a message of its own.

        The words the run paused on are already an assistant message, and the
        pending call is parented to it, so a client renders the prompt beside
        the call it is about. A message on the interrupt as well would be the
        same prompt a second time, in a place a renderer shows on its own.
        """
        said = "I need your approval before I send this."
        chunk = _paused(_confirmation(), content=said)

        events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True))

        spoken = [event for event in events if type(event).__name__ == "TextMessageContentEvent"]
        assert [event.delta for event in spoken] == [said]
        prompted = [event for event in events if type(event).__name__ == "ToolCallStartEvent"]
        assert [event.parent_message_id for event in prompted] == [spoken[0].message_id]
        assert "message" not in _advertised_interrupts(events)[0]

    @pytest.mark.parametrize(
        ("pending", "reason"),
        [
            (_confirmation(), interrupts.REASON_TOOL_CALL),
            (_external(), interrupts.REASON_TOOL_CALL),
            (_user_input(), interrupts.REASON_INPUT_REQUIRED),
            (_user_feedback(), interrupts.REASON_INPUT_REQUIRED),
        ],
        ids=["confirmation", "external_execution", "user_input", "user_feedback"],
    )
    def test_each_pause_kind_reports_its_reason_and_its_call(self, pending, reason):
        """A decision about one proposed call, or a request for data the model needs.

        Both are spec-defined reason values a client switches on, and both carry
        the tool call the interrupt is bound to, because that call is what the
        client was shown and what the resume is answered against.
        """
        events = on_run_completed(_paused(pending), StreamState(emit_interrupt_outcome=True))

        interrupt = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]
        assert interrupt["reason"] == reason
        assert interrupt["toolCallId"] == pending.tool_call_id

    @pytest.mark.parametrize(
        ("pending", "pause_type"),
        [
            (_confirmation(), "confirmation"),
            (_external(), "external_execution"),
            (_user_input(), "user_input"),
            (_user_feedback(), "user_feedback"),
        ],
        ids=["confirmation", "external_execution", "user_input", "user_feedback"],
    )
    def test_the_exact_pause_kind_stays_readable(self, pending, pause_type):
        """Two kinds share a reason and ask for opposite things: approve, or run it.

        The reason is the routing hint the protocol defines, so what tells those
        two apart travels beside it, with the name of the tool that is waiting.
        """
        events = on_run_completed(_paused(pending), StreamState(emit_interrupt_outcome=True))

        described = dict(self._described_pause(events))
        # Where a failure is reported is owned by the checks below. What every
        # kind carries is the pause kind and the tool that is waiting.
        described.pop(interrupts.ERROR_REPORT_PATH_KEY, None)
        assert described == {"pause_type": pause_type, "tool_name": pending.tool_name}

    def _described_pause(self, events: List[Any]) -> Dict[str, Any]:
        """What the interrupt says about the pause, under this interface's own key.

        Read through the namespace the resume channel reads its own metadata
        under, because it is one key: an emit site spelling it out as a literal
        is how the two sides come to disagree about where this interface's data
        lives.
        """
        interrupt = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]
        return interrupt["metadata"][interrupts.RESUME_METADATA_NAMESPACE]

    def test_a_pause_recording_no_tool_name_says_nothing_about_one(self):
        """An absent name is left out, not published as an explicit null.

        The key is this interface's own, so a client reading it reads what is
        there: a null under it says the pause named its tool and the name is
        nothing, which is a different claim from the pause not recording one.
        """
        nameless = ToolExecution(tool_call_id="tc-nameless", tool_name=None, requires_confirmation=True)

        events = on_run_completed(_paused(nameless), StreamState(emit_interrupt_outcome=True))

        described = self._described_pause(events)
        assert "tool_name" not in described
        assert described["pause_type"] == "confirmation"

    def test_an_external_execution_asks_for_no_particular_answer(self):
        """The client runs the tool and hands back whatever it returned.

        There is no shape to describe, and describing one would tell a client to
        validate a tool result against it.
        """
        events = on_run_completed(_paused(_external()), StreamState(emit_interrupt_outcome=True))

        assert "responseSchema" not in _outcome_on_the_wire(_run_finished(events))["interrupts"][0]

    def test_a_client_run_tool_is_told_where_to_report_that_it_failed(self):
        """A client can only find the convention by reading Agno's source otherwise.

        The answer to this pause is whatever the client's tool returned, so a
        tool that raised has nowhere in the payload to say so without reaching
        the model as output it never produced. Where it says so instead is
        envelope data about the response, so the interrupt names the path rather
        than describing an answer shape.
        """
        events = on_run_completed(_paused(_external()), StreamState(emit_interrupt_outcome=True))

        interrupt = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]
        assert interrupt["metadata"]["agno"][interrupts.ERROR_REPORT_PATH_KEY] == [
            "metadata",
            interrupts.RESUME_METADATA_NAMESPACE,
            interrupts.RESUME_ERROR_KEY,
        ]

    @pytest.mark.parametrize(
        "pending",
        [_confirmation(), _user_input(), _user_feedback()],
        ids=["confirmation", "user_input", "user_feedback"],
    )
    def test_no_other_pause_kind_advertises_that_path(self, pending):
        """Only an opaque tool result has no way of its own to say answering failed.

        A decision says no through the schema it advertises, and a request for
        input cannot be resumed from a failure at all, so naming the path on
        either would advertise a report that is either redundant or refused.
        """
        events = on_run_completed(_paused(pending), StreamState(emit_interrupt_outcome=True))

        described = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]["metadata"]["agno"]
        assert interrupts.ERROR_REPORT_PATH_KEY not in described

    def test_every_pending_call_gets_its_own_interrupt(self):
        """In the order the pause prompt shows them, which is the order of the
        terminal's own pending-call lists rather than the order the tools were
        given: a client renders the two side by side and the outcome has to name
        the same two, in the same order, as the calls it was shown."""
        chunk = _paused(_confirmation("tc-a", "send_email"), _external("tc-b", "change_background"))
        events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True))

        outcome = _outcome_on_the_wire(_run_finished(events))
        prompted = [event.tool_call_id for event in events if type(event).__name__ == "ToolCallStartEvent"]
        assert [interrupt["toolCallId"] for interrupt in outcome["interrupts"]] == prompted
        # Which requirement each interrupt is keyed by, with both sides sorted
        # because the terminal advertises in the order it prompts the calls and
        # not in the order the requirements are listed. The order is the line
        # above, against the order it really is in.
        assert sorted(interrupt["id"] for interrupt in outcome["interrupts"]) == _accepted_by_the_resume_side(chunk)

    def test_a_pause_the_client_cannot_be_shown_stays_a_plain_terminal(self, caplog):
        """The protocol refuses an interrupt outcome with nothing in it.

        A pending call with no id is one a client can neither render nor resolve,
        so the run reaches it as the finished run it reached before the outcome
        existed, and the interface says so rather than dropping it quietly.
        """
        unshowable = ToolExecution(tool_call_id=None, tool_name="send_email", requires_confirmation=True)
        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(RunPausedEvent(tools=[unshowable]), StreamState(emit_interrupt_outcome=True))

        assert _outcome_on_the_wire(_run_finished(events)) == "absent"
        assert "no interrupt the terminal can carry" in caplog.text

    def test_a_pause_with_no_pending_call_at_all_stays_a_plain_terminal(self):
        events = on_run_completed(RunPausedEvent(), StreamState(emit_interrupt_outcome=True))

        assert _outcome_on_the_wire(_run_finished(events)) == "absent"

    @pytest.mark.parametrize(
        "pending",
        [_confirmation(), _external(), _user_input(), _user_feedback()],
        ids=["confirmation", "external_execution", "user_input", "user_feedback"],
    )
    def test_a_pause_reported_without_requirements_still_reports_its_call(self, pending):
        """A pause carrying only the terminal's tool lists is keyed by the call.

        Every kind of pending call reaches this, because the requirements are
        what say which kind it is and this pause reports none. What is left is a
        proposed call the client was shown, which is the reason it carries and
        the id it is answered under.
        """
        events = on_run_completed(RunPausedEvent(tools=[pending]), StreamState(emit_interrupt_outcome=True))

        interrupt = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]
        assert (interrupt["id"], interrupt["reason"], interrupt["toolCallId"]) == (
            pending.tool_call_id,
            interrupts.REASON_TOOL_CALL,
            pending.tool_call_id,
        )

    @pytest.mark.parametrize(
        "pending",
        [_confirmation(), _external(), _user_input(), _user_feedback()],
        ids=["confirmation", "external_execution", "user_input", "user_feedback"],
    )
    def test_a_pause_reported_without_requirements_claims_no_pause_kind(self, pending):
        """Naming a kind here would be inventing one, and each invention is a lie
        a client acts on: an approval published as external execution is a tool
        the client runs itself, and the path for reporting that a client-run tool
        raised is answerable on no other kind. The tool that is waiting is still
        named, because the terminal really did report it.
        """
        events = on_run_completed(RunPausedEvent(tools=[pending]), StreamState(emit_interrupt_outcome=True))

        described = self._described_pause(events)
        assert "pause_type" not in described
        assert interrupts.ERROR_REPORT_PATH_KEY not in described
        assert described == {"tool_name": pending.tool_name}


# --- The one property the two halves have to agree on ------------------------


class _Entry:
    """One resume entry, in the shape the protocol model presents."""

    def __init__(
        self,
        interrupt_id: str,
        status: str = "resolved",
        payload: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.interrupt_id = interrupt_id
        self.status = status
        self.payload = payload
        self.metadata = metadata


def _requirement(pending: ToolExecution) -> RunRequirement:
    return RunRequirement(tool_execution=pending)


def _needs_answering(requirement: RunRequirement) -> Any:
    """The one entry the interface's own computation returns for this requirement.

    Both halves of the round trip read that computation, so a test driving one
    builder directly hands it what the interface would have handed it.
    """
    needed = interrupts.answers_a_pause_needs([requirement])
    assert len(needed) == 1, f"one open requirement, {len(needed)} answers needed"
    return needed[0]


def _accepted_by_the_resume_side(chunk: Any) -> List[str]:
    """The interrupt ids the resume side would take for this paused run.

    Read off the run's own open requirements, keyed exactly as
    ``resolve_requirements_from_resume_entries`` keys them, so the property
    below compares the terminal against the channel that has to answer it and
    not against a second opinion about what the pause meant.
    """
    return sorted(interrupts.interrupt_id_of(requirement) for requirement in chunk.active_requirements)


def _failed_terminal(events: List[Any]) -> Any:
    """The run's failed terminal, or None when the run finished.

    A body carrying both is refused: which of the two a client acted on is not
    something to guess at.
    """
    failed = [event for event in events if type(event).__name__ == "RunErrorEvent"]
    finished = [event for event in events if type(event).__name__ == "RunFinishedEvent"]
    assert len(failed) + len(finished) == 1, (
        f"expected exactly one run terminal, got {[type(event).__name__ for event in events]}"
    )
    return failed[0] if failed else None


# What a terminal that carries no outcome at all reads as. Its own value rather
# than an empty list: a terminal with no outcome and a terminal carrying an
# outcome with an empty interrupt list are different things on the wire, the
# second is one the protocol refuses, and a helper that returns [] for both lets
# a test that means the first pass on the second.
NO_OUTCOME_AT_ALL = "the terminal carried no outcome"


def _advertised_interrupts(events: List[Any]) -> Any:
    """The interrupts the terminal advertised in order, or NO_OUTCOME_AT_ALL.

    A run that failed carries no outcome to advertise one in, and neither does a
    finished run with the emission off. Both read as no outcome at all, which is
    not the same wire shape as an outcome whose interrupt list is empty.
    """
    if _failed_terminal(events) is not None:
        return NO_OUTCOME_AT_ALL
    outcome = _outcome_on_the_wire(_run_finished(events))
    return NO_OUTCOME_AT_ALL if outcome == "absent" else list(outcome["interrupts"])


def _advertised_interrupt_ids(events: List[Any]) -> Any:
    """Every id the terminal advertised in the order it advertised them, or NO_OUTCOME_AT_ALL.

    Emitted order, duplicates included, because that is what the terminal put on
    the wire. Sorted here instead, it was compared against a list in emission
    order: the terminal advertises in the order it prompts the calls, which is
    not the order a pause lists its requirements in, so that comparison was
    neither an order check nor a set one, and held by how two ids happened to
    sort.
    """
    advertised = _advertised_interrupts(events)
    if advertised == NO_OUTCOME_AT_ALL:
        return NO_OUTCOME_AT_ALL
    return [interrupt["id"] for interrupt in advertised]


def _advertised_interrupt_ids_keyed_as_the_resume_side_keys_them(events: List[Any]) -> Any:
    """The same ids in the order ``_accepted_by_the_resume_side`` returns them.

    For the comparisons whose subject is which ids reached the terminal rather
    than the order it advertised them in, which the emitted order above is what
    says. Keyed here rather than sorted at the call site so that a terminal
    carrying no outcome still reads as that and not as a sorted string.
    """
    advertised = _advertised_interrupt_ids(events)
    return advertised if advertised == NO_OUTCOME_AT_ALL else sorted(advertised)


def _an_answer_to(interrupt: Dict[str, Any]) -> Any:
    """A payload that answers one advertised interrupt.

    Built from what the interrupt itself advertised: the pause kind says which
    envelope the answer travels in and the response schema says what goes in it.
    So a client that read only the terminal could have sent this, which is what
    makes answering it evidence about the terminal rather than about the test.
    """
    pause_type = interrupt["metadata"]["agno"]["pause_type"]
    if pause_type == "confirmation":
        return {interrupts.CONFIRMATION_ACCEPTED_KEY: True}
    if pause_type == "external_execution":
        return "the client ran it"
    described = interrupt["responseSchema"]["properties"]
    if pause_type == "user_input":
        values = described[interrupts.USER_INPUT_VALUES_KEY]
        return {interrupts.USER_INPUT_VALUES_KEY: {name: "answered" for name in values.get("required", [])}}
    selections = described[interrupts.USER_FEEDBACK_SELECTIONS_KEY]
    return {
        interrupts.USER_FEEDBACK_SELECTIONS_KEY: {
            question: [asked["items"]["enum"][0]] for question, asked in selections["properties"].items()
        }
    }


def _answering_everything_advertised(chunk: Any, advertised: List[Dict[str, Any]]) -> None:
    """Answer exactly what the terminal advertised, through the resume side itself.

    On a copy of the paused run, because the answers are written onto the
    requirements. Raises whatever the route would: the resume side, guard
    included, is what decides whether the run continues, so it is driven rather
    than second-guessed here.
    """
    requirements = deepcopy(list(chunk.requirements or []))
    resolve_requirements_from_resume_entries(
        requirements,
        [_Entry(interrupt["id"], payload=_an_answer_to(interrupt)) for interrupt in advertised],
    )


# Every shape of pause that reports its requirements and can be continued. A
# pause reporting none has no requirement id to be keyed by and keeps the tool
# call as its key, which is pinned separately.
_PAUSE_SHAPES = {
    "one_call": lambda: _paused(_confirmation()),
    "two_calls": lambda: _paused(_confirmation("tc-a"), _external("tc-b")),
    "structured_input": lambda: _paused(_user_input()),
    "structured_feedback": lambda: _paused(_user_feedback()),
    "an_inner_agents_call": _paused_inside_an_inner_agent,
    "a_members_call": lambda: _member_paused(_confirmation(), member_run_id="member-run"),
    "a_call_with_nothing_open_behind_it": _paused_listing_a_call_with_nothing_open_behind_it,
}

# Every shape of pause that cannot be continued at all, because one of the
# requirements it left open is one no answer resolves. The run ends on those, so
# the same property reads the other way: nothing is advertised, and the terminal
# says why.
_PAUSES_NOTHING_CAN_ANSWER = {
    "one_call_for_two_pause_kinds": lambda: _paused(_two_pause_kinds()),
    "no_field_to_answer_in": lambda: _paused(_user_input([])),
    "one_answerable_beside_one_that_is_not": lambda: _paused(_two_pause_kinds(), _confirmation("tc-answerable")),
    "two_requirements_under_one_id": _paused_where_two_requirements_share_one_id,
    "a_question_that_answers_for_an_empty_field": lambda: _paused(
        _asks_a_question_while_a_field_it_needs_stays_empty()
    ),
    "no_field_an_answer_could_be_keyed_to": lambda: _paused(_filled_a_field_no_answer_could_name()),
    "a_members_call_nothing_can_answer": _member_paused_on_something_nothing_can_answer,
}

_EVERY_PAUSE_SHAPE = [pytest.param(shape, True, id=name) for name, shape in _PAUSE_SHAPES.items()] + [
    pytest.param(shape, False, id=name) for name, shape in _PAUSES_NOTHING_CAN_ANSWER.items()
]


@needs_interrupt_outcome
class TestTheTerminalAdvertisesWhatTheResumeSideAccepts:
    """The property the two halves of the round trip stand or fall on.

    A pause's terminal advertises the ids a client answers under, and the resume
    channel looks each answer up by the same id. Those two sets have to be the
    same set, and answering the advertised set has to continue the run. An id the
    resume side cannot place stops the entire resume array, stranding the run; an
    open requirement the terminal never advertised is one nobody answers, which
    the partial-resume guard then stops; and an id advertised twice is one
    correlation key standing for two things.

    A subset is not good enough, which is the hole this closes. A terminal that
    advertised only the requirements it could describe left the resume side
    demanding one it had not mentioned: the client answered everything it was
    told about and the guard refused the resume, with nothing on the wire saying
    what was missing. So a pause holding one requirement no answer resolves ends
    the run here, saying so, and advertises nothing at all.
    """

    @pytest.mark.parametrize("visibility", SUBAGENT_VISIBILITY_VALUES)
    @pytest.mark.parametrize(("shape", "continuable"), _EVERY_PAUSE_SHAPE)
    def test_a_pause_is_continuable_exactly_when_its_terminal_advertised_it(self, shape, visibility, continuable):
        """Across every visibility, because a setting decides what the client is
        shown and never what the run is still waiting on."""
        if visibility == SUBAGENT_VISIBILITY_ATTRIBUTED:
            require_lineage_events()
        chunk = shape()

        events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True, subagent_visibility=visibility))

        advertised = _advertised_interrupts(events)
        if not continuable:
            assert advertised == NO_OUTCOME_AT_ALL
            assert "cannot be continued" in _failed_terminal(events).message
            return
        assert _failed_terminal(events) is None
        assert sorted(interrupt["id"] for interrupt in advertised) == _accepted_by_the_resume_side(chunk)
        # Which is the half a matching set of ids does not prove: the resume side
        # has to take those answers and leave nothing open behind them.
        _answering_everything_advertised(chunk, advertised)

    def test_answering_all_but_one_of_them_is_refused(self):
        """The advertised set is the whole demand, not a menu.

        Every id on it is one the run cannot continue without, which is what
        makes the set the terminal sends the thing a client has to answer in
        full.
        """
        chunk = _paused(_confirmation("tc-a"), _external("tc-b"))
        advertised = _advertised_interrupts(
            on_run_completed(chunk, StreamState(emit_interrupt_outcome=True)),
        )

        with pytest.raises(ValueError, match="still unresolved"):
            _answering_everything_advertised(chunk, advertised[:1])

    def test_a_requirement_the_prompt_never_read_still_reaches_the_terminal(self):
        """The default visibility reads no member lane, and the pause is still open.

        A client answering only what it was shown fails the partial-resume guard
        on the requirement nobody told it about.
        """
        chunk = _paused_inside_an_inner_agent()

        events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True))

        # Both sides keyed alike, because the two orders are not the same one:
        # the terminal advertises in the order it prompts the calls, and a pause
        # lists its requirements in its own.
        assert _advertised_interrupt_ids_keyed_as_the_resume_side_keys_them(events) == _accepted_by_the_resume_side(
            chunk
        )
        # Unattributed: the default visibility names no member, and the terminal
        # carrying the requirement must not start naming one.
        assert "subagentRunId" not in _outcome_on_the_wire(_run_finished(events))["interrupts"][0]

    @pytest.mark.asyncio
    async def test_an_unannounced_member_is_not_named_by_the_interrupt_it_owns(self):
        """A member whose every pending call was dropped is never announced.

        Its requirement is still open, so the terminal still has to carry it.
        Naming the member there would leave the client an interrupt from a
        subagent it never saw start.
        """
        require_lineage_events()
        nameless = ToolExecution(tool_call_id="tc-ghost", tool_name=None, requires_confirmation=True)
        chunk = _member_paused(nameless, member_run_id="ghost-run")

        events, error = await collect_async(
            [chunk],
            attributed(),
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            emit_interrupt_outcome=True,
        )

        assert error is None
        assert _advertised_interrupt_ids_keyed_as_the_resume_side_keys_them(events) == _accepted_by_the_resume_side(
            chunk
        )
        interrupt = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]
        assert "subagentRunId" not in interrupt
        # Every way this stream could name the member, not one terminal kind: a
        # member announced and then closed as an error is named twice over.
        assert member_mentions(events) == []

    def test_a_listed_call_with_nothing_open_behind_it_is_not_advertised(self):
        """Advertising it hands the client an id the resume side refuses.

        One refused entry stops the whole array, so the run is stranded by an
        interrupt it never needed answered.

        Which call each advertised interrupt stands for, because every id on the
        wire is a minted one: a tool call id can reach the id field only where
        the run recorded no requirement id, so naming the settled call there
        pins nothing this pause can produce.
        """
        chunk = _paused_listing_a_call_with_nothing_open_behind_it()

        events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True))

        assert _advertised_interrupt_ids_keyed_as_the_resume_side_keys_them(events) == _accepted_by_the_resume_side(
            chunk
        )
        assert [interrupt["toolCallId"] for interrupt in _advertised_interrupts(events)] == ["tc-open"]


# --- The answer shapes the outcome advertises --------------------------------


class _UnmappedType:
    """A declared field type that no JSON Schema type maps, as a real tool can carry."""


# The values a client could put in one field: one per JSON type, and the
# integral float that is how JSON spells a whole number. A field the advertised
# schema leaves open permits nearly all of them, and every value it permits has
# to resolve the pause.
_EVERY_JSON_SHAPE: List[Any] = [None, "otters", 0, 1.5, 2.0, True, ["a"], {"a": 1}]


def _is_of_json_type(value: Any, json_type: str) -> bool:
    if json_type == "null":
        return value is None
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "integer":
        # JSON has one number type, so a whole number can arrive as a float and
        # is still the integer the schema named.
        if isinstance(value, float):
            return value.is_integer()
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "object":
        return isinstance(value, dict)
    raise AssertionError(f"the advertised schema names the type {json_type!r}, which this check cannot read")


def _permits(described: Dict[str, Any], value: Any) -> bool:
    """Whether one advertised field schema accepts this value.

    Only the keywords this interface emits are read, and any other one fails the
    check loudly: a constraint silently skipped here would let a schema be
    tested against a meaning it does not carry.
    """
    for keyword, constraint in described.items():
        if keyword in ("description", "title"):
            continue
        if keyword == "type":
            if not _is_of_json_type(value, constraint):
                return False
        elif keyword == "not":
            if _permits(constraint, value):
                return False
        else:
            raise AssertionError(f"the advertised schema uses {keyword!r}, which this check cannot read")
    return True


def _the_interrupt_advertised_for(pending: ToolExecution) -> Dict[str, Any]:
    """The one interrupt a pause on this call reaches a client as."""
    events = on_run_completed(_paused(pending), StreamState(emit_interrupt_outcome=True))
    return _outcome_on_the_wire(_run_finished(events))["interrupts"][0]


def _the_schema_advertised_for(pending: ToolExecution) -> Dict[str, Any]:
    """The answer shape a client is told to send, read off the wire and not rebuilt.

    One reader for both halves: the schemas are asserted through it, and the
    payloads the resume side is held to are derived from what it returns, so a
    test cannot hold the resume side to a shape the client was never shown.
    """
    return _the_interrupt_advertised_for(pending)["responseSchema"]


def _keywords_in(described: Dict[str, Any]) -> Set[str]:
    """Every JSON Schema keyword one advertised schema is built out of.

    Schema-aware rather than a plain walk: the keys under ``properties`` are the
    names of an answer's fields, and reading those as keywords would let any
    field name pass for a constraint somebody checks.
    """
    found = set(described)
    for keyword, constraint in described.items():
        if keyword == "properties":
            for child in constraint.values():
                found |= _keywords_in(child)
        elif keyword in ("items", "not"):
            found |= _keywords_in(constraint)
    return found


@needs_interrupt_outcome
class TestResponseSchemas:
    def _schema_for(self, pending: ToolExecution) -> Dict[str, Any]:
        return _the_schema_advertised_for(pending)

    def _described_field(self, pending: ToolExecution, name: str) -> Dict[str, Any]:
        return self._schema_for(pending)["properties"][interrupts.USER_INPUT_VALUES_KEY]["properties"][name]

    def test_a_decision_asks_for_the_key_agno_reads(self):
        """One payload shape has to work on both resume channels."""
        schema = self._schema_for(_confirmation())

        assert schema["required"] == [interrupts.CONFIRMATION_ACCEPTED_KEY]
        assert schema["properties"][interrupts.CONFIRMATION_ACCEPTED_KEY]["type"] == "boolean"

    def test_a_decision_offers_no_edited_arguments(self):
        """Advertising the field is what tells a client it may offer edit UI."""
        properties = self._schema_for(_confirmation())["properties"]

        # Named beside the absence, so a schema that describes nothing at all
        # cannot read as one that merely declines to offer the field.
        assert interrupts.CONFIRMATION_ACCEPTED_KEY in properties
        assert "editedArgs" not in properties

    def test_user_input_describes_every_field_it_is_waiting_on(self):
        schema = self._schema_for(_user_input())["properties"][interrupts.USER_INPUT_VALUES_KEY]

        assert schema["properties"]["topic"] == {"type": "string", "description": "What to write about"}
        assert schema["required"] == ["topic"]

    def test_a_field_the_model_already_filled_is_not_required(self):
        """The run continues once the fields still missing arrive."""
        pre_filled = UserInputField(name="topic", field_type=str)
        pre_filled.value = "otters"
        fields = [pre_filled, UserInputField(name="tone", field_type=str)]

        schema = self._schema_for(_user_input(fields))["properties"][interrupts.USER_INPUT_VALUES_KEY]

        assert sorted(schema["properties"]) == ["tone", "topic"]
        assert schema["required"] == ["tone"]

    def test_user_input_maps_each_declared_type(self):
        fields = [
            UserInputField(name="count", field_type=int),
            UserInputField(name="ratio", field_type=float),
            UserInputField(name="agreed", field_type=bool),
            UserInputField(name="tags", field_type=list),
        ]

        schema = self._schema_for(_user_input(fields))["properties"][interrupts.USER_INPUT_VALUES_KEY]

        assert {name: described["type"] for name, described in schema["properties"].items()} == {
            "count": "integer",
            "ratio": "number",
            "agreed": "boolean",
            "tags": "array",
        }

    def test_a_type_nothing_recognises_is_left_unconstrained(self):
        """A wrong type in the schema makes a client refuse an answer Agno accepts."""
        described = self._described_field(
            _user_input([UserInputField(name="thing", field_type=_UnmappedType)]), "thing"
        )

        assert "type" not in described

    def test_a_field_left_unconstrained_still_cannot_be_null(self):
        """Not naming the type is not the same as accepting anything at all.

        A null leaves the field unfilled: the resume writes it on, the field
        counts as unanswered, and the run the client was told to resume dies on
        the partial-resume guard. So the one constraint that is known is stated
        without the type that is not.
        """
        described = self._described_field(
            _user_input([UserInputField(name="thing", field_type=_UnmappedType)]), "thing"
        )

        assert described == {"not": {"type": "null"}}
        assert _permits(described, None) is False

    def test_every_value_the_advertised_schema_permits_resolves_the_pause(self):
        """The client did what it was told, so the run has to continue.

        Read off the schema rather than written by hand: what a client may send
        is exactly what is advertised, and the pause must be resolvable by any
        of it.
        """

        def unmapped() -> ToolExecution:
            return _user_input([UserInputField(name="thing", field_type=_UnmappedType)])

        described = self._described_field(unmapped(), "thing")
        permitted = [value for value in _EVERY_JSON_SHAPE if _permits(described, value)]

        assert permitted, f"the advertised field schema {described} permits no answer at all"
        for value in permitted:
            requirement = _requirement(unmapped())

            _answer_by_resume_entry(requirement, {interrupts.USER_INPUT_VALUES_KEY: {"thing": value}})

            assert requirement.is_resolved() is True, value

    def test_two_declarations_that_agree_on_nothing_still_cannot_be_null(self):
        """The merge drops the type the two disagree on, which leaves the same hole."""
        fields = [
            UserInputField(name="topic", field_type=str),
            UserInputField(name="topic", field_type=_UnmappedType),
        ]

        assert self._described_field(_user_input(fields), "topic") == {"not": {"type": "null"}}

    def test_user_feedback_offers_only_the_labels_the_question_declared(self):
        schema = self._schema_for(_user_feedback())["properties"][interrupts.USER_FEEDBACK_SELECTIONS_KEY]

        answered = schema["properties"]["What budget?"]
        assert answered["items"]["enum"] == ["low", "high"]
        assert schema["required"] == ["What budget?"]

    def _question_asked_by(self, pending: ToolExecution) -> Dict[str, Any]:
        """What the one question of this feedback pause asks a client for."""
        asked = self._schema_for(pending)["properties"][interrupts.USER_FEEDBACK_SELECTIONS_KEY]["properties"]
        (text,) = asked
        return asked[text]

    def test_a_label_of_another_kind_is_offered_as_the_text_of_itself(self):
        """A choice list holding a value the type beside it excludes satisfies nothing.

        The label reaches the enum as its display text, which is the one form
        the resume side accepts for it: the item type is enforced there, so the
        label as the tool wrote it is refused and its text is taken. Offering
        the text is therefore offering the only answer that choice has, and a
        client that validates before it submits, which the protocol says it
        should, can build one.
        """
        offered = self._question_asked_by(
            _user_feedback_offering(UserFeedbackOption(label=3), UserFeedbackOption(label="high"))
        )["items"]

        assert [label for label in offered["enum"] if not _is_of_json_type(label, offered["type"])] == []
        assert offered["enum"] == ["3", "high"]

    def test_a_converted_label_is_one_the_resume_side_takes(self):
        """The choice is advertised because answering with it continues the run.

        Which is what makes converting the label better than leaving it out: the
        label as the tool wrote it is refused for its type, so the text is the
        only answer that choice ever had, and a pause that offers it is a pause
        whose every advertised choice can be picked.
        """
        pending = _user_feedback_offering(UserFeedbackOption(label=3))

        assert self._question_asked_by(pending)["items"]["enum"] == ["3"]

        requirement = _requirement(pending)
        _answer_by_resume_entry(requirement, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {"What budget?": ["3"]}})
        assert requirement.is_resolved() is True

    def test_a_label_that_cannot_be_offered_at_all_is_reported(self, caplog):
        """A choice list short of what the tool offered is one nothing recorded.

        An empty label is nothing to show and reaches no client, so the question
        is advertised without it. Left unsaid, the pause reads as one the tool
        declared fewer choices for than it did.
        """
        with captured_agno_logs(caplog, "WARNING"):
            offered = self._question_asked_by(
                _user_feedback_offering(UserFeedbackOption(label=""), UserFeedbackOption(label="high"))
            )["items"]

        assert offered["enum"] == ["high"]
        assert "without 1 of its options" in caplog.text

    def test_a_question_left_with_no_usable_label_still_asks_its_question(self):
        """Leaving out every label gives the shape a question with no options has.

        Which is one a client can answer and Agno resolves: a selection is
        written onto the question as it arrives, matched against no label. So
        the pause is advertised rather than refused, and answering it continues
        the run.
        """
        pending = _user_feedback_offering(UserFeedbackOption(label=""))

        assert "enum" not in self._question_asked_by(pending)["items"]

        requirement = _requirement(pending)
        _answer_by_resume_entry(requirement, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {"What budget?": ["low"]}})
        assert requirement.is_resolved() is True

    def test_a_single_select_question_caps_the_answer_at_one(self):
        """Otherwise a client offers a choice Agno would then have to refuse."""
        single = self._schema_for(_user_feedback(multi_select=False))
        multi = self._schema_for(_user_feedback(multi_select=True))

        key = interrupts.USER_FEEDBACK_SELECTIONS_KEY
        assert single["properties"][key]["properties"]["What budget?"]["maxItems"] == 1
        assert "maxItems" not in multi["properties"][key]["properties"]["What budget?"]

    @pytest.mark.parametrize("multi_select", [False, True], ids=["single_select", "multi_select"])
    def test_a_question_asks_for_at_least_one_selection(self, multi_select):
        """An empty array is a payload that satisfies the schema and answers nothing."""
        schema = self._schema_for(_user_feedback(multi_select=multi_select))

        answered = schema["properties"][interrupts.USER_FEEDBACK_SELECTIONS_KEY]["properties"]["What budget?"]
        assert answered["minItems"] == 1

    def test_two_fields_sharing_a_name_are_advertised_once(self):
        """Two keys of one name in the payload are one key, and Agno fills both.

        Where the two declarations disagree the key is described by what they
        agree on: a constraint one of them would fail is a client refusing an
        answer Agno accepts.
        """
        fields = [
            UserInputField(name="topic", field_type=str, description="What to write about"),
            UserInputField(name="topic", field_type=str),
        ]

        schema = self._schema_for(_user_input(fields))["properties"][interrupts.USER_INPUT_VALUES_KEY]

        assert list(schema["properties"]) == ["topic"]
        assert schema["properties"]["topic"] == {"type": "string"}
        assert schema["required"] == ["topic"]

    def test_two_questions_sharing_their_text_are_advertised_once(self):
        """One key per question text, because that is what Agno matches by."""
        asked_twice = ToolExecution(
            tool_call_id="tc-feedback",
            tool_name="ask_user",
            tool_args={},
            requires_user_input=True,
            user_feedback_schema=[
                UserFeedbackQuestion(question="What budget?", options=[UserFeedbackOption(label="low")]),
                UserFeedbackQuestion(question="What budget?", options=[UserFeedbackOption(label="high")]),
            ],
        )

        schema = self._schema_for(asked_twice)["properties"][interrupts.USER_FEEDBACK_SELECTIONS_KEY]

        assert list(schema["properties"]) == ["What budget?"]
        assert schema["required"] == ["What budget?"]
        # The two offer different labels, so no label list is advertised: one
        # naming only what the other offers would refuse a valid answer.
        assert "enum" not in schema["properties"]["What budget?"]["items"]


class TestThePayloadsThoseSchemasAdvertise:
    """The resume-side half of a claim the schemas above make.

    It is the reason a schema is shaped the way it is, and it touches no
    interrupt type: it answers a requirement through the resume channel, which
    every install has. Kept out of the class above so a gate written for the
    schemas does not skip it on an install where it still holds.
    """

    def test_one_value_answers_every_field_of_that_name(self):
        """Why the collapsed key is a shape that can be satisfied and not a loss."""
        fields = [UserInputField(name="topic", field_type=str), UserInputField(name="topic", field_type=str)]
        requirement = _requirement(_user_input(fields))

        _answer_by_resume_entry(requirement, {interrupts.USER_INPUT_VALUES_KEY: {"topic": "otters"}})

        assert [input_field.value for input_field in requirement.user_input_schema] == ["otters", "otters"]
        assert requirement.is_resolved() is True


# --- The advertised shape is the shape that is accepted ----------------------


# Every pause kind that tells a client the shape of the answer it wants. A
# client-run tool is not one: it hands back whatever its tool returned, which
# this interface never described.
_PAUSES_THAT_ADVERTISE_A_SHAPE = {
    "decision": _confirmation,
    "input": _user_input,
    "single_select": lambda: _user_feedback(multi_select=False),
    "multi_select": lambda: _user_feedback(multi_select=True),
}


@needs_interrupt_outcome
class TestOnlyTheAdvertisedShapeIsAccepted:
    """A value under a described key has to be of the kind the key was described as.

    Every payload here is derived from what the terminal advertised rather than
    written out, so each test is evidence about the interface's own promise: the
    constraint is read off the emitted schema, and the answer that violates it is
    built from that constraint. A value of another kind under a described key
    reaches the tool as an argument it never asked for, which is worse than the
    refusal.

    What is checked is narrower than what is advertised, deliberately, and the
    class below pins what that gives up.
    """

    @pytest.mark.parametrize(
        "pending", list(_PAUSES_THAT_ADVERTISE_A_SHAPE.values()), ids=list(_PAUSES_THAT_ADVERTISE_A_SHAPE)
    )
    def test_an_answer_the_advertised_schema_asked_for_resolves_the_pause(self, pending):
        """The strictness has to keep taking what the client was told to send."""
        requirement = _requirement(pending())

        _answer_by_resume_entry(requirement, _an_answer_to(_the_interrupt_advertised_for(pending())))

        assert requirement.is_resolved() is True

    def test_every_constraint_it_advertises_is_one_this_side_accounts_for(self):
        """Enforced, an annotation, or described for the client alone: nothing else.

        A keyword outside those is one the interface publishes and no side of the
        round trip decided anything about, which is how a constraint ends up
        enforced nowhere and written down as enforced. The check itself also
        passes over a keyword it cannot read rather than refusing an answer over
        a constraint it does not understand, so this is what keeps that case
        hypothetical.
        """
        advertised: Set[str] = set()
        for build in (
            _confirmation,
            _user_input,
            lambda: _user_input(
                [
                    UserInputField(name="count", field_type=int),
                    UserInputField(name="thing", field_type=_UnmappedType),
                ]
            ),
            lambda: _user_feedback(multi_select=False),
            lambda: _user_feedback(multi_select=True),
        ):
            advertised |= _keywords_in(_the_schema_advertised_for(build()))

        assert advertised, "no schema keyword was read at all, so this check proves nothing"
        accounted_for = set(ADVERTISED_KEYWORDS_READ) | set(SCHEMA_ADVERTISED_ONLY)
        assert advertised <= accounted_for, sorted(advertised - accounted_for)
        # And the two halves are really two: a schema stating only what is
        # enforced would pass the line above while describing nothing extra,
        # which is the arrangement the class below exists to pin.
        assert advertised & set(SCHEMA_ADVERTISED_ONLY)

    def test_a_field_resolves_on_exactly_the_values_its_declared_type_permits(self):
        """Both directions off one description, so neither strictness nor leniency drifts.

        A field advertised as one type used to resolve with any other, which
        reaches the tool as an argument of a type it never asked for.
        """

        def declared_as_a_number() -> ToolExecution:
            return _user_input([UserInputField(name="count", field_type=int)])

        described = _the_schema_advertised_for(declared_as_a_number())["properties"][interrupts.USER_INPUT_VALUES_KEY][
            "properties"
        ]["count"]
        permitted = [value for value in _EVERY_JSON_SHAPE if _permits(described, value)]
        assert permitted and len(permitted) < len(_EVERY_JSON_SHAPE), described

        for value in _EVERY_JSON_SHAPE:
            requirement = _requirement(declared_as_a_number())
            answer = {interrupts.USER_INPUT_VALUES_KEY: {"count": value}}

            if value in permitted:
                _answer_by_resume_entry(requirement, answer)
                assert requirement.is_resolved() is True, value
            else:
                with pytest.raises(ValueError, match="user_input expects"):
                    _answer_by_resume_entry(requirement, answer)
                assert requirement.is_resolved() is False, value

    def test_a_note_of_a_shape_the_schema_never_offered_is_refused(self):
        """The note is what the model reads as the reason a call was refused.

        Taken untyped, a structured object lands where the run records a string,
        so a client's own object reaches the model as that reason. The null is
        left out of this: an optional key a client sent nothing under is the
        subject of the test below.
        """
        described = _the_schema_advertised_for(_confirmation())["properties"][interrupts.CONFIRMATION_NOTE_KEY]
        refused = [value for value in _EVERY_JSON_SHAPE if value is not None and not _permits(described, value)]
        assert refused, described

        for value in refused:
            requirement = _requirement(_confirmation())
            answer = {interrupts.CONFIRMATION_ACCEPTED_KEY: False, interrupts.CONFIRMATION_NOTE_KEY: value}

            with pytest.raises(ValueError, match="confirmation expects"):
                _answer_by_resume_entry(requirement, answer)

            assert requirement.is_resolved() is False, value

    def test_a_selection_of_a_kind_the_question_never_offered_is_refused(self):
        """A label is the text of an option, and the run stores the list as text.

        ``selected_options`` is typed as text and the run serialises it straight
        back to the model as the selection somebody made, so a number arriving
        where a label belongs is a value of another kind reaching a tool, which
        is the one thing this side checks for. Which labels a question offers,
        and how many it takes, are not checked and the class below pins that:
        the entry's declared type is what separates the two.
        """
        pending = _user_feedback(multi_select=True)
        asked = _the_schema_advertised_for(pending)["properties"][interrupts.USER_FEEDBACK_SELECTIONS_KEY]
        (text,) = asked["properties"]
        entry = asked["properties"][text]["items"]
        refused = [value for value in _EVERY_JSON_SHAPE if not _permits({"type": entry["type"]}, value)]
        assert refused, entry

        for value in refused:
            requirement = _requirement(_user_feedback(multi_select=True))
            answer = {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {text: [value]}}

            with pytest.raises(ValueError, match="user_feedback expects"):
                _answer_by_resume_entry(requirement, answer)

            assert requirement.is_resolved() is False, value
            assert requirement.user_feedback_schema[0].selected_options is None, value

    def test_a_selection_the_question_offered_still_resolves_it(self):
        """The strictness above has to keep taking the labels a client was shown."""
        pending = _user_feedback(multi_select=True)
        asked = _the_schema_advertised_for(pending)["properties"][interrupts.USER_FEEDBACK_SELECTIONS_KEY]
        (text,) = asked["properties"]
        offered = asked["properties"][text]["items"]["enum"]
        requirement = _requirement(pending)

        _answer_by_resume_entry(requirement, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {text: offered}})

        assert requirement.is_resolved() is True
        assert requirement.user_feedback_schema[0].selected_options == offered

    def test_a_key_the_schema_leaves_out_of_required_may_arrive_empty(self):
        """A client that had no value for an optional key sent no value, not a wrong one.

        Which is the same reading that lets a decision written under the spec's
        own field resolve past a null under Agno's. Refusing it instead would
        turn away a resume that answered the question it was asked.
        """
        schema = _the_schema_advertised_for(_confirmation())
        assert interrupts.CONFIRMATION_NOTE_KEY not in schema["required"]
        requirement = _requirement(_confirmation())

        _answer_by_resume_entry(
            requirement,
            {interrupts.CONFIRMATION_ACCEPTED_KEY: True, interrupts.CONFIRMATION_NOTE_KEY: None},
        )

        assert requirement.tool_execution.confirmed is True
        assert requirement.confirmation_note is None


@needs_interrupt_outcome
class TestWhatTheSchemaDescribesAndThisSideDoesNotCheck:
    """Known limitations: what a client is told and holds itself to, and nothing here enforces.

    The round trip is written this way on purpose. The interrupt describes the
    answer fully, so a client can validate before it submits, and this side
    checks only that a value is of the kind its key was described as. These are
    the payloads that arrangement lets through, each pinned so the giving-up is a
    decision on the record rather than something to be discovered by a run that
    acted on one.

    Each reads the constraint off the emitted schema and then breaks it, so the
    pair is the evidence: the interrupt still publishes the constraint, and the
    answer that violates it still resolves the pause.
    """

    def _question(self, pending: ToolExecution) -> Tuple[str, Dict[str, Any]]:
        """The one question a feedback pause advertised, and what it asks for."""
        asked = _the_schema_advertised_for(pending)["properties"][interrupts.USER_FEEDBACK_SELECTIONS_KEY]
        (text,) = asked["properties"]
        return text, asked["properties"][text]

    def test_an_empty_selection_resolves_the_question_that_asked_for_one(self):
        """Agno counts a list it was handed as the answer, empty or not.

        So the tool runs on no selection at all. Refusing it here is not the fix:
        what counts as answered is Agno's own rule, across every question at
        once, and reaching into that from this interface is a separate change.
        """
        pending = _user_feedback()
        text, answered = self._question(pending)
        assert answered["minItems"] == 1
        requirement = _requirement(pending)

        _answer_by_resume_entry(requirement, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {text: []}})

        assert requirement.is_resolved() is True
        assert requirement.user_feedback_schema[0].selected_options == []

    def test_more_selections_than_a_single_select_question_offers_resolve_it(self):
        pending = _user_feedback(multi_select=False)
        text, answered = self._question(pending)
        too_many = answered["items"]["enum"][: answered["maxItems"] + 1]
        assert len(too_many) > answered["maxItems"], "the question offers too few labels to overrun its own cap"
        requirement = _requirement(pending)

        _answer_by_resume_entry(requirement, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {text: too_many}})

        assert requirement.user_feedback_schema[0].selected_options == too_many

    def test_a_label_the_question_never_offered_resolves_it(self):
        pending = _user_feedback(multi_select=True)
        text, answered = self._question(pending)
        never_offered = "-".join(answered["items"]["enum"]) + "-none-of-these"
        assert never_offered not in answered["items"]["enum"]
        requirement = _requirement(pending)

        _answer_by_resume_entry(requirement, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {text: [never_offered]}})

        assert requirement.user_feedback_schema[0].selected_options == [never_offered]

    def test_a_null_under_a_required_field_the_schema_left_untyped_reaches_the_guard(self):
        """The one advertised-only constraint that still refuses the resume.

        Nothing checks the null out of the payload, so it is written onto the
        field, the field counts as unfilled, and the resolved-set guard is what
        stops the run. A client is refused either way; which check refuses it
        decides only what the refusal says.
        """
        pending = _user_input([UserInputField(name="thing", field_type=_UnmappedType)])
        described = _the_schema_advertised_for(pending)["properties"][interrupts.USER_INPUT_VALUES_KEY]
        assert described["properties"]["thing"] == {"not": {"type": "null"}}
        assert described["required"] == ["thing"]
        requirement = _requirement(pending)

        with pytest.raises(ValueError, match="still unresolved"):
            _answer_by_resume_entry(requirement, {interrupts.USER_INPUT_VALUES_KEY: {"thing": None}})

        assert requirement.is_resolved() is False


# --- A member the run paused inside -----------------------------------------


@needs_interrupt_outcome
class TestSuspendedMember:
    @needs_member_attribution
    @pytest.mark.asyncio
    async def test_the_interrupt_names_the_member_that_asked(self):
        require_lineage_events()
        chunk = _member_paused(_confirmation(), member_run_id="member-run")
        events, error = await collect_async(
            [chunk],
            attributed(),
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            emit_interrupt_outcome=True,
        )

        assert error is None
        interrupt = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]
        assert interrupt["subagentRunId"] == "member-run"

    @needs_suspended_outcome
    @pytest.mark.asyncio
    async def test_the_member_closes_as_waiting_not_as_finished(self):
        require_lineage_events()
        chunk = _member_paused(_confirmation(), member_run_id="member-run")
        events, error = await collect_async(
            [chunk],
            attributed(),
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            emit_interrupt_outcome=True,
        )

        assert error is None
        outcome = _outcome_on_the_wire(_subagent_terminals(events)[0])
        assert outcome["type"] == "suspended"
        assert sorted(outcome["interruptIds"]) == _accepted_by_the_resume_side(chunk)

    @pytest.mark.asyncio
    async def test_a_visibility_that_names_no_member_attributes_nothing(self):
        """``hidden`` must not let a confirmation prompt reveal which member asked."""
        events, error = await collect_async(
            [_member_paused(_confirmation(), member_run_id="member-run")],
            "hidden",
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            emit_interrupt_outcome=True,
        )

        assert error is None
        interrupt = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]
        assert "subagentRunId" not in interrupt
        # Every way this stream could name the member: an announcement, a
        # terminal of any kind, or a lane stamped on anything at all.
        assert member_mentions(events) == []

    @pytest.mark.asyncio
    async def test_the_default_visibility_attributes_nothing_either(self):
        events, error = await collect_async(
            [_member_paused(_confirmation(), member_run_id="member-run")],
            None,
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            emit_interrupt_outcome=True,
        )

        assert error is None
        interrupt = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]
        assert "subagentRunId" not in interrupt
        assert member_mentions(events) == []


# --- Resuming: the half that has to actually continue the run ----------------


# What each tool's body actually did, which is the only record that says a
# declined call did not run: nothing on the wire tells a call the run refused
# from one it ran and whose result it withheld.
EMAILS_SENT: List[str] = []
POSTS_WRITTEN: List[str] = []


@pytest.fixture(autouse=True)
def _forget_what_the_tools_did():
    """No earlier test's tool call can read as this one's evidence."""
    EMAILS_SENT.clear()
    POSTS_WRITTEN.clear()
    yield


@tool(requires_confirmation=True)
def send_email(to: str) -> str:
    """Send one email."""
    EMAILS_SENT.append(to)
    return f"EMAIL SENT to {to}"


@tool(requires_user_input=True, user_input_fields=["topic"])
def write_post(topic: str = "") -> str:
    """Write a post."""
    POSTS_WRITTEN.append(topic)
    return f"POST ABOUT {topic}"


@tool(requires_user_input=True)
def ask_nothing() -> str:
    """Ask for input, taking no argument an answer could be written into."""
    raise AssertionError("a tool with nothing to answer must never run")


@tool(external_execution=True)
def change_background(color: str) -> str:
    """Change the background. Never runs server side."""
    raise AssertionError("an external execution must not run in the server")


_WIRE_EVENT = TypeAdapter(Event)


def _as_protocol_events(events: List[Dict[str, Any]]) -> List[Any]:
    """The body's events read back through the protocol's own models.

    The shared invariants are written against protocol events and what the route
    hands a client is an encoded body, so the body is decoded back into the
    events it carries rather than checked here in a second, weaker way.
    """
    return [_WIRE_EVENT.validate_python(event) for event in events]


def _one_run_terminal(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The single run terminal on the wire, refusing a body that carries two.

    Taking the last of several hides a second terminal instead of failing on it,
    and which of two a client would have acted on is not something to guess.
    """
    terminals = [event for event in events if event["type"] in ("RUN_FINISHED", "RUN_ERROR")]
    assert len(terminals) == 1, f"expected exactly one run terminal, got {[event['type'] for event in events]}"
    return terminals[0]


def _finished_on_the_wire(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The run's terminal, which has to be a finish rather than a failure."""
    terminal = _one_run_terminal(events)
    assert terminal["type"] == "RUN_FINISHED", f"the run did not finish: {terminal}"
    return terminal


class Wire:
    """One AGUI interface over a real entity, driven by real requests.

    Every resume assertion in this suite is about what the second request does to
    the run the first one paused, so both go through the mounted route against one
    live entity and one live session.

    Every body this harness reads is held to the shared definition of a
    well-formed stream, the same one every other suite in this directory uses, so
    a resume that continues the run through a malformed stream fails here rather
    than passing on the one payload a test happened to look at, and to what its
    events encoded, so a key no model declares fails on the real route rather
    than only where a builder is driven directly.
    """

    def __init__(self, entity, **agui_kwargs):
        from fastapi.testclient import TestClient

        from agno.os import AgentOS
        from agno.os.interfaces.agui import AGUI

        is_team = isinstance(entity, Team)
        interface = AGUI(team=entity, **agui_kwargs) if is_team else AGUI(agent=entity, **agui_kwargs)
        agent_os = AgentOS(
            id="interrupt-os",
            agents=None if is_team else [entity],
            teams=[entity] if is_team else None,
            interfaces=[interface],
            telemetry=False,
        )
        self._entity = entity
        self._client = TestClient(agent_os.get_app())
        self._turn = 0

    def post(self, prompt: str, *, malformed: Optional[str] = None, **extra: Any) -> List[Dict[str, Any]]:
        """One request, with the body it answered with held to the shared definition.

        ``malformed`` names the record for a body this interface really does
        send malformed today, pinning the violation as the direct-driver
        wrapper above does rather than waiving it.
        """
        self._turn += 1
        response = self._client.post(
            "/agui",
            json={
                "thread_id": THREAD_ID,
                "run_id": f"request-{self._turn}",
                "messages": [{"id": "m1", "role": "user", "content": prompt}],
                "tools": [],
                "context": [],
                "forwarded_props": {},
                **extra,
            },
        )
        assert response.status_code == 200, response.text
        events = sse_events(response.text)
        as_protocol_events = _as_protocol_events(events)
        if malformed is None:
            assert_well_formed_stream(as_protocol_events)
        else:
            assert_stream_is_malformed_as_recorded(as_protocol_events, malformed)
        _assert_nothing_undeclared_reached_the_client(as_protocol_events)
        terminal = _one_run_terminal(events)
        assert events[-1] is terminal, (
            f"the response body does not end on its run terminal: {[event['type'] for event in events[-3:]]}"
        )
        return events

    def recorded_tool_messages(self) -> List[Tuple[Optional[str], Any]]:
        """(tool call id, content) per tool message the last run recorded, in order.

        Where a client-run tool's result exists at all: nothing of it reaches the
        wire, and this is the message the run went on to continue from.
        """
        return [
            (message.tool_call_id, message.content)
            for message in self._last_run().messages or []
            if message.role == "tool"
        ]

    def open_interrupt_ids(self) -> List[Optional[str]]:
        """The interrupt id of every requirement the last run left open.

        Read off the stored run rather than off the wire, so a test can drive
        the ids a client was never advertised: a resume for one of those is what
        a client that guessed would send.
        """
        return [
            interrupts.interrupt_id_of(requirement)
            for requirement in self._last_run().requirements or []
            if not requirement.is_resolved()
        ]

    def _last_run(self) -> Any:
        session = self._entity.get_session(session_id=THREAD_ID)
        assert session is not None, f"the entity recorded no session {THREAD_ID} to read"
        assert session.runs, f"session {THREAD_ID} recorded no run to read"
        return session.runs[-1]


def _interrupts_of(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    outcome = _finished_on_the_wire(events).get("outcome")
    assert outcome and outcome["type"] == "interrupt", f"the run did not report an interrupt: {outcome}"
    return outcome["interrupts"]


def _tool_results(events: List[Dict[str, Any]]) -> Dict[str, str]:
    """The result each tool call reported, refusing to fold a call reported twice.

    A mapping keyed by the call id lets a second result overwrite the first,
    which is what a tool running twice looks like on the wire.
    """
    reported = [(event["toolCallId"], event["content"]) for event in events if event["type"] == "TOOL_CALL_RESULT"]
    repeated = sorted(call for call, count in Counter(call for call, _ in reported).items() if count > 1)
    assert not repeated, f"a tool call reported a result more than once: {repeated}"
    return dict(reported)


def _said(events: List[Dict[str, Any]]) -> str:
    return "".join(event["delta"] for event in events if event["type"] == "TEXT_MESSAGE_CONTENT")


def _errors(events: List[Dict[str, Any]]) -> List[str]:
    return [event["message"] for event in events if event["type"] == "RUN_ERROR"]


def _errors_naming(events: List[Dict[str, Any]], *fragments: str) -> List[str]:
    """The run errors carrying every fragment, for a test whose subject is one refusal.

    A test satisfied by any error at all is satisfied by a crash anywhere on the
    path, which is the failure it was written to tell apart from the refusal it
    asked for.
    """
    return [message for message in _errors(events) if all(fragment in message for fragment in fragments)]


def _confirming_agent(tools=None, script=None) -> Agent:
    return Agent(
        id="interrupt-agent",
        name="Interrupt Agent",
        model=ScriptedModel(
            "m",
            script
            or [
                ("tool", "send_email", {"to": "ops@example.com"}, "tc-1"),
                ("content", "Sent."),
            ],
        ),
        db=InMemoryDb(),
        tools=tools or [send_email],
        telemetry=False,
    )


class _ProposingSeveralAtOnce(ScriptedModel):
    """A model whose first turn proposes several tool calls, then talks.

    One run pausing on two requirements at once needs one assistant turn
    proposing two calls, and the shared scripted model states one call per turn.
    """

    def __init__(self, calls: List[Tuple[str, Dict[str, Any], str]], then: str):
        super().__init__("m", [("content", then)])
        self._proposed = list(calls)

    def _next(self) -> Any:
        if not self._proposed:
            return super()._next()
        from agno.models.response import ModelResponse

        proposing, self._proposed = self._proposed, []
        response = ModelResponse(role="assistant")
        response.tool_calls = [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for name, args, call_id in proposing
        ]
        return response


def _agent_pausing_on_one_answerable_and_one_not() -> Agent:
    """An Agent whose one turn proposes a decision and a tool nothing can answer.

    ``ask_nothing`` asks for input and takes no argument, so the pause it
    reports declares no field a value could be sent under: it is open, and no
    payload resolves it. The decision beside it is answerable on its own.
    """
    return Agent(
        id="interrupt-agent",
        name="Interrupt Agent",
        model=_ProposingSeveralAtOnce(
            [("send_email", {"to": "ops@example.com"}, "tc-1"), ("ask_nothing", {}, "tc-2")],
            "Done.",
        ),
        db=InMemoryDb(),
        tools=[send_email, ask_nothing],
        telemetry=False,
    )


# The question a feedback pause over the route asks, in the arguments the
# ask_user call carries it in. Its labels are what the interrupt advertises as
# the entries of the array an answer sends back.
A_QUESTION_WITH_LABELS = [
    {
        "question": "What budget?",
        "header": "Budget",
        "options": [{"label": "low"}, {"label": "high"}],
        "multi_select": False,
    }
]


def _agent_asking_a_question() -> Agent:
    """An Agent whose one turn asks the user to pick one of two labels.

    ``ask_user`` is intercepted rather than run, so what a selection reaches is
    the question it is written onto and the tool message the run continues from,
    which is where the model reads the answer back.
    """
    return Agent(
        id="interrupt-agent",
        name="Interrupt Agent",
        model=ScriptedModel(
            "m",
            [("tool", "ask_user", {"questions": A_QUESTION_WITH_LABELS}, "tc-ask"), ("content", "Noted.")],
        ),
        db=InMemoryDb(),
        tools=[UserFeedbackTools(add_instructions=False)],
        telemetry=False,
    )


A_MIXED_PAUSE_PROMPT = "email ops@example.com and ask me something"


@needs_interrupt_outcome
class TestAMixedPauseOverTheRoute:
    """One answerable requirement beside one nothing can answer, end to end.

    The strand this closes only exists in the round trip, so it is driven
    through the mounted route against a real Agent: the terminal advertised the
    answerable requirement, a client answered exactly that, and the resume was
    refused over the requirement it had never been told about, with nothing on
    the wire ever saying the run could not go on.
    """

    def test_the_run_fails_on_the_wire_and_says_why(self):
        wire = Wire(_agent_pausing_on_one_answerable_and_one_not(), emit_interrupt_outcome=True)

        events = wire.post(A_MIXED_PAUSE_PROMPT)

        terminal = _one_run_terminal(events)
        assert terminal["type"] == "RUN_ERROR"
        assert terminal["code"] == interrupts.PAUSE_NOT_CONTINUABLE_CODE
        assert "cannot be continued" in terminal["message"]
        assert "declares no field" in terminal["message"]

    def test_the_answerable_half_is_not_advertised_and_its_tool_never_runs(self):
        """Answering it could not continue the run, so it is not offered.

        The tool body is the only record that says the call did not run, and the
        run has to reach its terminal without it: a pause the client cannot
        resolve must not be resolved on the client's behalf either.
        """
        wire = Wire(_agent_pausing_on_one_answerable_and_one_not(), emit_interrupt_outcome=True)

        events = wire.post(A_MIXED_PAUSE_PROMPT)

        assert "outcome" not in _one_run_terminal(events)
        assert EMAILS_SENT == []

    @needs_resume_array
    def test_a_client_that_resumes_it_anyway_is_told_the_same_thing(self):
        """Nothing stops a client sending a resume array it was never offered.

        It reaches the guard, which reads the same computation the terminal
        read, so the answer it gets is the terminal's answer and not a bare
        refusal.
        """
        wire = Wire(_agent_pausing_on_one_answerable_and_one_not(), emit_interrupt_outcome=True)
        wire.post(A_MIXED_PAUSE_PROMPT)
        guessed = wire.open_interrupt_ids()[0]

        resumed = wire.post(
            A_MIXED_PAUSE_PROMPT,
            resume=[{"interrupt_id": guessed, "status": "resolved", "payload": {"accepted": True}}],
        )

        assert [message for message in _errors(resumed) if "cannot be continued" in message]
        assert EMAILS_SENT == []


class TestAMixedPauseWithTheOutcomeOff:
    """The same run on an install that has no interrupt-aware lifecycle at all.

    Which is the half of the setting's promise that holds everywhere, so it sits
    outside the gate above: asking for the emission is what needs the release
    piece, and this asks for nothing.
    """

    def test_the_same_pause_prompts_as_it_always_did(self):
        """The setting decides what the terminal claims, and nothing else.

        With it off this interface advertises no ids and holds a resume to
        nothing, so the pause reaches the client as the finished run and the two
        pending calls it always did.
        """
        wire = Wire(_agent_pausing_on_one_answerable_and_one_not())

        events = wire.post(A_MIXED_PAUSE_PROMPT)

        assert "outcome" not in _finished_on_the_wire(events)
        started = [event["toolCallId"] for event in events if event["type"] == "TOOL_CALL_START"]
        assert started == ["tc-1", "tc-2"]


@needs_interrupt_outcome
@needs_resume_array
class TestResumeContinuesTheRun:
    """Every test here reads a pause off an emitted outcome and answers it by id.

    Both gates, because those are two release pieces: the outcome the pause is
    advertised through, and the array the answer arrives in.
    """

    def test_a_feedback_pause_continues_from_the_selections_it_advertised(self):
        """The fourth pause kind over the route the other three already run.

        It was the one answered only by calling a resolver directly, so nothing
        said a client could reach it over the wire at all. Answered from the
        advertised schema alone, which is all such a client reads, and the proof
        it arrived is the selection reaching the tool that asked for it.
        """
        asked = {
            "question": "Which colour?",
            "header": "Colour",
            "options": [{"label": "blue"}, {"label": "red"}],
        }
        wire = Wire(
            _confirming_agent(
                tools=[UserFeedbackTools()],
                script=[("tool", "ask_user", {"questions": [asked]}, "tc-ask"), ("content", "Blue it is.")],
            ),
            emit_interrupt_outcome=True,
        )
        interrupt = _interrupts_of(wire.post("pick a colour"))[0]

        assert interrupt["metadata"]["agno"]["pause_type"] == "user_feedback"

        resumed = wire.post(
            "pick a colour",
            resume=[{"interrupt_id": interrupt["id"], "status": "resolved", "payload": _an_answer_to(interrupt)}],
        )

        assert _errors(resumed) == []
        assert _said(resumed) == "Blue it is."
        assert wire.recorded_tool_messages() == [
            ("tc-ask", 'User feedback received: [{"question": "Which colour?", "selected": ["blue"]}]')
        ]

    def test_a_decision_runs_the_tool_the_pause_proposed(self):
        """The proof a pause was real: the tool body ran, against the original call.

        A restarted run would propose the call again and report a result for a
        new id; this asserts the id the pause reported.
        """
        wire = Wire(_confirming_agent(), emit_interrupt_outcome=True)
        paused = wire.post("email ops@example.com")
        interrupt = _interrupts_of(paused)[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt["id"], "status": "resolved", "payload": {"accepted": True}}],
        )

        assert _tool_results(resumed) == {"tc-1": json.dumps("EMAIL SENT to ops@example.com")}
        assert _said(resumed) == "Sent."

    def test_the_resumed_run_is_finished_not_waiting(self):
        wire = Wire(_confirming_agent(), emit_interrupt_outcome=True)
        interrupt = _interrupts_of(wire.post("email ops@example.com"))[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt["id"], "status": "resolved", "payload": {"accepted": True}}],
        )

        assert "outcome" not in _finished_on_the_wire(resumed)
        # The pause it continued from is what makes a terminal with no outcome
        # mean finished rather than a run that never got that far.
        assert EMAILS_SENT == ["ops@example.com"]

    def test_a_denied_decision_does_not_run_the_tool(self):
        """A denial continues the run, and the call it declined never ran.

        The absence of the tool's output from the stream is not the subject: a
        resume that failed outright carries none of it either. What is asserted
        is that the run went on past the pause, that the body never ran, and
        that the reason the client gave is what the run continued from.
        """
        wire = Wire(_confirming_agent(), emit_interrupt_outcome=True)
        interrupt = _interrupts_of(wire.post("email ops@example.com"))[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[
                {
                    "interrupt_id": interrupt["id"],
                    "status": "resolved",
                    "payload": {"accepted": False, "note": "wrong recipient"},
                }
            ],
        )

        assert _errors(resumed) == []
        assert _said(resumed) == "Sent."
        assert EMAILS_SENT == []
        assert wire.recorded_tool_messages() == [("tc-1", "wrong recipient")]

    def test_a_decision_nobody_can_read_fails_the_run_instead_of_declining(self):
        """A denial the client never gave reads exactly like one it did.

        So the run fails where a client can see it, rather than the call being
        declined and the refusal recorded against whoever asked.
        """
        wire = Wire(_confirming_agent(), emit_interrupt_outcome=True)
        interrupt = _interrupts_of(wire.post("email ops@example.com"))[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt["id"], "status": "resolved", "payload": {"decision": "approve"}}],
        )

        assert _errors_naming(resumed, "confirmation expects"), (
            f"an unreadable decision was taken for an answer: {_errors(resumed)}"
        )
        assert EMAILS_SENT == []

    def test_the_interrupt_specs_own_approval_field_is_read_too(self):
        """A payload written against the spec's example must resolve, not refuse."""
        wire = Wire(_confirming_agent(), emit_interrupt_outcome=True)
        interrupt = _interrupts_of(wire.post("email ops@example.com"))[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[
                {
                    "interrupt_id": interrupt["id"],
                    "status": "resolved",
                    "payload": {interrupts.CONFIRMATION_ACCEPTED_ALIAS: True},
                }
            ],
        )

        assert _tool_results(resumed) == {"tc-1": json.dumps("EMAIL SENT to ops@example.com")}

    def test_structured_input_reaches_the_tool_that_asked_for_it(self):
        wire = Wire(
            _confirming_agent(
                tools=[write_post],
                script=[("tool", "write_post", {}, "tc-post"), ("content", "Written.")],
            ),
            emit_interrupt_outcome=True,
        )
        interrupt = _interrupts_of(wire.post("write a post"))[0]

        resumed = wire.post(
            "write a post",
            resume=[
                {
                    "interrupt_id": interrupt["id"],
                    "status": "resolved",
                    "payload": {interrupts.USER_INPUT_VALUES_KEY: {"topic": "otters"}},
                }
            ],
        )

        assert _tool_results(resumed) == {"tc-post": json.dumps("POST ABOUT otters")}

    def test_a_client_run_tool_hands_its_result_back(self):
        """Text the client returned is what the run continues from, unchanged.

        A client-run tool's result reaches no client back, so the tool message
        the run recorded under the call the pause reported is where it exists.
        """
        wire = Wire(
            _confirming_agent(
                tools=[change_background],
                script=[("tool", "change_background", {"color": "blue"}, "tc-bg"), ("content", "Changed.")],
            ),
            emit_interrupt_outcome=True,
        )
        interrupt = _interrupts_of(wire.post("make it blue"))[0]

        resumed = wire.post(
            "make it blue",
            resume=[{"interrupt_id": interrupt["id"], "status": "resolved", "payload": "the client changed it"}],
        )

        assert _errors(resumed) == []
        assert _said(resumed) == "Changed."
        assert wire.recorded_tool_messages() == [("tc-bg", "the client changed it")]

    def test_a_structured_client_result_travels_as_json(self):
        """A structured result is serialised, so a Python repr is not what it needs.

        Nothing of this result reaches the wire, so the run continuing is not
        what tells a repr from JSON: the tool message the run recorded is, and
        it is what anything reading the thread back parses.
        """
        wire = Wire(
            _confirming_agent(
                tools=[change_background],
                script=[("tool", "change_background", {"color": "blue"}, "tc-bg"), ("content", "Changed.")],
            ),
            emit_interrupt_outcome=True,
        )
        interrupt = _interrupts_of(wire.post("make it blue"))[0]

        resumed = wire.post(
            "make it blue",
            resume=[
                {
                    "interrupt_id": interrupt["id"],
                    "status": "resolved",
                    "payload": {"ok": True, "changed": ["body"]},
                }
            ],
        )

        assert _errors(resumed) == []
        assert _said(resumed) == "Changed."
        assert wire.recorded_tool_messages() == [("tc-bg", json.dumps({"ok": True, "changed": ["body"]}))]

    def test_the_resume_array_wins_over_trailing_tool_messages(self):
        """Both channels can arrive at once, and only one of them names interrupts."""
        wire = Wire(_confirming_agent(), emit_interrupt_outcome=True)
        interrupt = _interrupts_of(wire.post("email ops@example.com"))[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt["id"], "status": "resolved", "payload": {"accepted": True}}],
            messages=[
                {"id": "m1", "role": "user", "content": "email ops@example.com"},
                {
                    "id": "t1",
                    "role": "tool",
                    "tool_call_id": "tc-1",
                    "content": json.dumps({"accepted": False}),
                },
            ],
        )

        assert _tool_results(resumed) == {"tc-1": json.dumps("EMAIL SENT to ops@example.com")}

    def test_a_cancelled_decision_declines_the_call(self):
        """A decision the client withdrew is a refusal, and the run continues.

        Nothing stands in for the answer, so what the run continues from says
        the interrupt was cancelled rather than declined for a reason nobody
        gave, and the tool the pause proposed never runs.
        """
        wire = Wire(_confirming_agent(), emit_interrupt_outcome=True)
        interrupt = _interrupts_of(wire.post("email ops@example.com"))[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt["id"], "status": "cancelled"}],
        )

        assert _errors(resumed) == []
        assert _said(resumed) == "Sent."
        assert EMAILS_SENT == []
        assert wire.recorded_tool_messages() == [("tc-1", CANCELLED_NOTE)]

    def test_a_cancelled_request_for_input_stops_the_run(self):
        """There is no value that stands in for data the tool needs to run at all."""
        wire = Wire(
            _confirming_agent(
                tools=[write_post],
                script=[("tool", "write_post", {}, "tc-post"), ("content", "Written.")],
            ),
            emit_interrupt_outcome=True,
        )
        interrupt = _interrupts_of(wire.post("write a post"))[0]

        resumed = wire.post(
            "write a post",
            resume=[{"interrupt_id": interrupt["id"], "status": "cancelled"}],
        )

        assert _errors_naming(resumed, interrupt["id"], "cannot be resumed without the input"), (
            f"a cancelled input request continued the run anyway: {_errors(resumed)}"
        )
        assert POSTS_WRITTEN == []


@needs_interrupt_outcome
@needs_resume_array
class TestAnEntryThePausedRunDoesNotRecognise:
    """An answer to a question this run never asked must not discard the real ones.

    The protocol has a producer proceed without an entry it does not recognise
    and warn, rather than fail a run over an answer it never asked for. Three
    ways a client gets there: an id that never existed, an id the run already
    resolved, and the same request body arriving twice.
    """

    def _paused_wire(self, script=None) -> Tuple[Wire, str]:
        """Pauses on the first turn; a test that drives more runs than one states the turns they take."""
        wire = Wire(_confirming_agent(script=script), emit_interrupt_outcome=True)
        return wire, _interrupts_of(wire.post("email ops@example.com"))[0]["id"]

    @pytest.mark.parametrize("stale_first", [False, True], ids=["stale_last", "stale_first"])
    def test_the_valid_answer_beside_it_still_continues_the_run(self, stale_first):
        """Order does not decide it: whichever entry is read first, the real answer applies."""
        wire, interrupt_id = self._paused_wire()
        answered = {"interrupt_id": interrupt_id, "status": "resolved", "payload": {"accepted": True}}
        stale = {"interrupt_id": "int-from-an-older-run", "status": "resolved", "payload": {"accepted": True}}

        resumed = wire.post(
            "email ops@example.com",
            resume=[stale, answered] if stale_first else [answered, stale],
        )

        assert _errors(resumed) == []
        assert _tool_results(resumed) == {"tc-1": json.dumps("EMAIL SENT to ops@example.com")}
        assert EMAILS_SENT == ["ops@example.com"]

    def test_the_entry_it_skipped_is_warned_about(self, caplog):
        """Skipping it quietly would leave a client's answer with nowhere it was reported.

        The level is the subject: naming the id while failing the run is what
        this already did, so the record has to be the warning a continued run
        left behind.
        """
        wire, interrupt_id = self._paused_wire()

        with captured_agno_logs(caplog, "WARNING"):
            resumed = wire.post(
                "email ops@example.com",
                resume=[
                    {"interrupt_id": interrupt_id, "status": "resolved", "payload": {"accepted": True}},
                    {"interrupt_id": "int-from-an-older-run", "status": "resolved", "payload": {"accepted": True}},
                ],
            )

        assert _errors(resumed) == []
        named = [record.levelname for record in caplog.records if "int-from-an-older-run" in record.message]
        assert named == ["WARNING"]

    def test_a_wrong_answer_to_a_question_this_run_did_ask_still_fails_the_run(self):
        """The skip is for an entry nobody asked for, not for an unreadable answer.

        An answer to an interrupt this run is waiting on cannot be dropped: the
        pause stays open and the client is owed the reason its payload was
        refused. Nothing is spent by refusing it, which is what makes the refusal
        the right answer rather than a lost turn: the same pause answers a second
        request that sends a payload this side can read.
        """
        wire, interrupt_id = self._paused_wire()

        refused = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt_id, "status": "resolved", "payload": {"decision": "approve"}}],
        )

        assert _errors_naming(refused, "confirmation expects"), (
            f"an unreadable answer to an open interrupt was skipped: {_errors(refused)}"
        )
        assert EMAILS_SENT == []

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt_id, "status": "resolved", "payload": {"accepted": True}}],
        )

        assert _tool_results(resumed) == {"tc-1": json.dumps("EMAIL SENT to ops@example.com")}

    def test_the_same_request_body_sent_twice_does_not_fail_the_second_time(self):
        """A browser retry or a double submit replays one body; it must not error.

        The run it answered is finished, so the entries answer nothing and the
        request runs on without them. What must not happen either way is the
        tool running a second time.

        The third scripted turn is what the replay runs on its own: a replay
        answered out of the resumed run's turn would be a repeat nobody asked
        the model for.
        """
        wire, interrupt_id = self._paused_wire(
            script=[
                ("tool", "send_email", {"to": "ops@example.com"}, "tc-1"),
                ("content", "Sent."),
                ("content", "Nothing left to answer."),
            ]
        )
        answering = [{"interrupt_id": interrupt_id, "status": "resolved", "payload": {"accepted": True}}]

        resumed = wire.post("email ops@example.com", resume=answering)
        replayed = wire.post("email ops@example.com", resume=answering)

        assert _errors(resumed) == []
        assert _said(resumed) == "Sent."
        assert _errors(replayed) == []
        assert _said(replayed) == "Nothing left to answer."
        assert _tool_results(replayed) == {}
        assert EMAILS_SENT == ["ops@example.com"]

    def test_the_pause_it_could_not_place_is_still_answerable_afterwards(self):
        """An array nothing in the run answers must not consume the pause either.

        Proceeding without the entries leaves the interrupt exactly where it was,
        so the client that sends the right id next gets its run continued rather
        than a pause the earlier request spent.

        Two runs follow the pause and the script states a turn for each: the
        request whose entries placed nowhere runs fresh on its own turn, and the
        continued run finishes on the turn after it.
        """
        wire, interrupt_id = self._paused_wire(
            script=[
                ("tool", "send_email", {"to": "ops@example.com"}, "tc-1"),
                ("content", "Nothing to answer here."),
                ("content", "Sent."),
            ]
        )
        unplaceable = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": "int-that-never-existed", "status": "resolved", "payload": {"accepted": True}}],
        )

        assert _errors(unplaceable) == []
        assert _said(unplaceable) == "Nothing to answer here."
        assert _tool_results(unplaceable) == {}

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt_id, "status": "resolved", "payload": {"accepted": True}}],
        )

        assert _errors(resumed) == []
        assert _tool_results(resumed) == {"tc-1": json.dumps("EMAIL SENT to ops@example.com")}
        assert _said(resumed) == "Sent."
        assert EMAILS_SENT == ["ops@example.com"]


@needs_resume_array
class TestTheResumeArrayIsInput:
    def test_an_array_that_answers_no_paused_run_runs_fresh(self):
        """A resume list on a run that continues no interrupted run answers nothing.

        The protocol has those entries treated as unrecognised, and the request
        carries a user message like any other, so what is left is the fresh run
        it describes rather than a run error.
        """
        wire = Wire(_confirming_agent(script=[("content", "Nothing to resume.")]))

        events = wire.post(
            "hello",
            resume=[{"interrupt_id": "int-that-never-existed", "status": "resolved", "payload": {"accepted": True}}],
        )

        assert _errors(events) == []
        assert _said(events) == "Nothing to resume."

    def test_the_resume_array_is_read_whether_or_not_the_outcome_is_emitted(self):
        """The array is input, and the setting is about output.

        A client that resumes this way is not the reason the emission is opt-in,
        and ignoring its answers would strand a run over a setting that only
        decides what the terminal says. With the emission off the pause reports
        no id, so the answer is addressed to the one the run recorded: the proof
        the array was read is the tool body running against the call the pause
        held, which an ignored array leaves pending forever.

        Gated on the array alone, which is the piece it reads. Sitting under the
        gate for the emission is what made it skip on the one install it exists
        to prove: a release that declares the array without the interrupt types.
        """
        wire = Wire(_confirming_agent())
        paused = wire.post("email ops@example.com")
        assert "outcome" not in _finished_on_the_wire(paused)
        interrupt_id = wire.open_interrupt_ids()[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt_id, "status": "resolved", "payload": {"accepted": True}}],
        )

        assert _errors(resumed) == []
        assert _tool_results(resumed) == {"tc-1": json.dumps("EMAIL SENT to ops@example.com")}


def _run_input_type_without_the_resume_array() -> Any:
    """``RunAgentInput`` as a release that never declared the resume array presents it.

    A real model built from the installed one's remaining fields on the protocol's
    own configured base, so it keeps the configuration that decides what happens
    to a key it does not declare. That configuration is the whole subject: the
    protocol's models keep such a key as untyped extra data, so a client's resume
    array still arrives on this release, as raw dictionaries rather than entries.
    """
    return _type_without(RunAgentInput, "resume")


@needs_resume_array
class TestAReleaseWithoutTheResumeArray:
    """The install this interface says it still serves: no array, tool messages only.

    The route is mounted against the simulated release, so the request the client
    sends is parsed by it, which is the one thing that decides whether the answers
    arrive as entries or as extra data. Nothing about the detection is stood in
    for: it reads the model the route actually parsed with.
    """

    def _wire_on_the_older_release(self, monkeypatch) -> Wire:
        from agno.os.interfaces.agui import router as router_module

        monkeypatch.setattr(router_module, "RunAgentInput", _run_input_type_without_the_resume_array())
        return Wire(_confirming_agent())

    def test_a_client_that_sends_both_is_continued_from_its_tool_message(self, monkeypatch):
        """The shape a newer client sends an older server, which has to keep working.

        The array cannot be read here, so the answer the request also carries in
        the channel this release does have is what continues the run. Reading the
        array off the parsed request instead finds raw dictionaries, and the run
        fails on the first one without ever reaching the tool message.
        """
        wire = self._wire_on_the_older_release(monkeypatch)
        wire.post("email ops@example.com")
        guessed = wire.open_interrupt_ids()[0]

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": guessed, "status": "resolved", "payload": {"accepted": True}}],
            messages=[
                {"id": "m1", "role": "user", "content": "email ops@example.com"},
                {"id": "t1", "role": "tool", "tool_call_id": "tc-1", "content": json.dumps({"accepted": True})},
            ],
        )

        assert _errors(resumed) == []
        assert _tool_results(resumed) == {"tc-1": json.dumps("EMAIL SENT to ops@example.com")}
        assert EMAILS_SENT == ["ops@example.com"]

    def test_an_array_nothing_can_read_is_dropped_by_name(self, monkeypatch, caplog):
        """Dropping answers silently is what leaves a client waiting on a run.

        The release has no place for them, so the run goes on as it did before the
        round trip existed, and what was dropped is said once, naming the field,
        rather than reaching a resolver as dictionaries.
        """
        wire = self._wire_on_the_older_release(monkeypatch)
        wire.post("email ops@example.com")
        guessed = wire.open_interrupt_ids()[0]

        with caplog.at_level(logging.WARNING, logger="agno"):
            resumed = wire.post(
                "email ops@example.com",
                resume=[{"interrupt_id": guessed, "status": "resolved", "payload": {"accepted": True}}],
            )

        assert _errors(resumed) == [], "the unreadable array reached a resolver as dictionaries"
        assert [record for record in caplog.records if "resume" in record.message], (
            "a client's answers were dropped without saying so"
        )


@needs_interrupt_outcome
@needs_resume_array
class TestTeamResumeContinuesTheMember:
    def _team(self) -> Team:
        db = InMemoryDb()
        member = Agent(
            name="Mailer",
            id="mailer",
            model=ScriptedModel(
                "m-mailer",
                [("tool", "send_email", {"to": "ops@example.com"}, "tc-mem"), ("content", "Member done.")],
            ),
            db=db,
            tools=[send_email],
            telemetry=False,
        )
        return Team(
            name="Team",
            id="interrupt-team",
            model=ScriptedModel(
                "m-leader",
                [
                    ("tool", "delegate_task_to_member", {"member_id": "mailer", "task": "email ops"}, "tc-lead"),
                    ("content", "Leader done."),
                ],
            ),
            members=[member],
            db=db,
            telemetry=False,
        )

    @needs_member_attribution
    @needs_suspended_outcome
    def test_the_members_pause_is_attributed_and_then_continued(self):
        require_lineage_events()
        wire = Wire(self._team(), emit_interrupt_outcome=True, subagent_visibility=attributed())
        paused = wire.post("email ops@example.com")

        interrupt = _interrupts_of(paused)[0]
        lane = interrupt["subagentRunId"]
        assert lane, "the interrupt did not name the member that asked"

        suspended = [
            event
            for event in paused
            if event["type"] == "SUBAGENT_FINISHED" and event.get("outcome", {}).get("type") == "suspended"
        ]
        assert [event["subagentRunId"] for event in suspended] == [lane]
        assert suspended[0]["outcome"]["interruptIds"] == [interrupt["id"]]

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt["id"], "status": "resolved", "payload": {"accepted": True}}],
        )

        assert _tool_results(resumed)["tc-mem"] == json.dumps("EMAIL SENT to ops@example.com")
        # The same member, continued rather than replaced by a fresh invocation.
        assert {event["subagentRunId"] for event in resumed if event.get("subagentRunId")} == {lane}

    def test_answering_exactly_what_the_pause_advertised_continues_the_run(self):
        """The property end to end, on the shape a real team pause has.

        A team leader's terminal lists its own delegation call and nothing else,
        so the member's pending call reaches the client only through the
        requirement list. Answering every advertised id has to continue the run:
        an id the run cannot place stops the array, and an open requirement
        nobody answered stops it at the partial-resume guard.
        """
        wire = Wire(self._team(), emit_interrupt_outcome=True)
        advertised = _interrupts_of(wire.post("email ops@example.com"))

        # Keyed by the requirement rather than by the call, which is the id the
        # resume side looks an answer up by.
        assert [interrupt["id"] for interrupt in advertised] != [interrupt["toolCallId"] for interrupt in advertised]

        resumed = wire.post(
            "email ops@example.com",
            resume=[
                {"interrupt_id": interrupt["id"], "status": "resolved", "payload": {"accepted": True}}
                for interrupt in advertised
            ],
        )

        assert _errors(resumed) == []
        assert _tool_results(resumed)["tc-mem"] == json.dumps("EMAIL SENT to ops@example.com")

    def test_a_team_resumes_without_member_attribution_too(self):
        """The default visibility names no member, and the run still continues."""
        wire = Wire(self._team(), emit_interrupt_outcome=True)
        interrupt = _interrupts_of(wire.post("email ops@example.com"))[0]
        assert "subagentRunId" not in interrupt

        resumed = wire.post(
            "email ops@example.com",
            resume=[{"interrupt_id": interrupt["id"], "status": "resolved", "payload": {"accepted": True}}],
        )

        assert _tool_results(resumed)["tc-mem"] == json.dumps("EMAIL SENT to ops@example.com")


# --- The channel that predates the resume array, at the wire -----------------


# Every decision payload the trailing-tool-message channel already had a verdict
# for, paired with whether that verdict ran the proposed tool, and with the note
# the run went on to continue from where the payload named one. Each row was read
# off the interface at the commit this work starts from and driven through it, so
# the table is that channel's answers rather than a restatement of the reading
# under test.
#
# This channel took answers before the interface advertised any answer shape, and
# its callers were written against exactly these verdicts. The two channels share
# one reading of a decision payload, so a widening meant for the protocol's own
# array reaches this one for free: a payload that used to decline the call would
# start running the tool, and nobody who wrote against the older channel asked for
# that. The table is what a change to the shared reading has to survive.
DECISIONS_THIS_CHANNEL_ALREADY_ANSWERED = pytest.mark.parametrize(
    "payload,runs_the_tool,continued_from",
    [
        ({interrupts.CONFIRMATION_ACCEPTED_KEY: True}, True, None),
        ({interrupts.CONFIRMATION_ACCEPTED_KEY: False}, False, None),
        ({interrupts.CONFIRMATION_ACCEPTED_ALIAS: True}, False, None),
        ({interrupts.CONFIRMATION_ACCEPTED_ALIAS: False}, False, None),
        (
            {interrupts.CONFIRMATION_ACCEPTED_KEY: None, interrupts.CONFIRMATION_ACCEPTED_ALIAS: True},
            False,
            None,
        ),
        (
            {interrupts.CONFIRMATION_ACCEPTED_KEY: True, interrupts.CONFIRMATION_ACCEPTED_ALIAS: False},
            True,
            None,
        ),
        (
            {interrupts.CONFIRMATION_ACCEPTED_KEY: False, interrupts.CONFIRMATION_ACCEPTED_ALIAS: True},
            False,
            None,
        ),
        (
            {interrupts.CONFIRMATION_ACCEPTED_ALIAS: True, interrupts.CONFIRMATION_NOTE_KEY: "wrong recipient"},
            False,
            "wrong recipient",
        ),
        ({interrupts.CONFIRMATION_ACCEPTED_ALIAS: "yes"}, False, None),
        ({interrupts.CONFIRMATION_ACCEPTED_ALIAS: None}, False, None),
        ({interrupts.CONFIRMATION_ACCEPTED_KEY: "true"}, False, None),
        ({interrupts.CONFIRMATION_NOTE_KEY: "no reason to"}, False, "no reason to"),
        (
            {interrupts.CONFIRMATION_ACCEPTED_KEY: False, interrupts.CONFIRMATION_NOTE_KEY: ["wrong recipient"]},
            False,
            ["wrong recipient"],
        ),
        ({}, False, None),
        (True, False, None),
        ("yes", False, None),
    ],
    ids=[
        "agnos_own_field_accepting",
        "agnos_own_field_denying",
        "the_spec_field_accepting",
        "the_spec_field_denying",
        "the_spec_field_past_a_null",
        "agnos_own_field_over_a_denying_alias",
        "agnos_own_denial_over_an_accepting_alias",
        "the_spec_field_beside_a_note",
        "a_non_boolean_alias",
        "a_null_alias",
        "a_non_boolean_decision",
        "a_note_and_nothing_else",
        "a_denial_whose_note_is_not_text",
        "no_fields_at_all",
        "not_an_object",
        "a_bare_string",
    ],
)


class TestTheTrailingToolMessageChannelAnswersAtTheWire:
    """What a client sending a trailing tool result gets back, decision by decision.

    Driven through the mounted route so the subject is what the encoded stream
    carries: a resumed run reports the proposed call's result only where the
    answer confirmed it, so the presence of that ``TOOL_CALL_RESULT`` is the
    client-visible difference between a tool that ran and one that did not.
    """

    def _resume_with(self, wire: Wire, payload: Any) -> List[Dict[str, Any]]:
        return wire.post(
            "email ops@example.com",
            messages=[
                {"id": "m1", "role": "user", "content": "email ops@example.com"},
                {"id": "t1", "role": "tool", "tool_call_id": "tc-1", "content": json.dumps(payload)},
            ],
        )

    @DECISIONS_THIS_CHANNEL_ALREADY_ANSWERED
    def test_a_decision_gets_the_verdict_this_channel_always_gave_it(self, payload, runs_the_tool, continued_from):
        wire = Wire(_confirming_agent())
        wire.post("email ops@example.com")

        resumed = self._resume_with(wire, payload)

        assert _errors(resumed) == []
        assert _tool_results(resumed) == (
            {"tc-1": json.dumps("EMAIL SENT to ops@example.com")} if runs_the_tool else {}
        )
        assert EMAILS_SENT == (["ops@example.com"] if runs_the_tool else [])

    @DECISIONS_THIS_CHANNEL_ALREADY_ANSWERED
    def test_a_decision_leaves_the_run_continuing_from_what_it_carried(self, payload, runs_the_tool, continued_from):
        """The reason a refusal names is what the model reads next, so it is pinned too.

        Nothing of it reaches the wire: a declined call reports no result, and
        the note is only visible in the message the run continued from. A row
        naming no note leaves the refusal wording to Agno rather than restating
        a string this interface does not own.
        """
        wire = Wire(_confirming_agent())
        wire.post("email ops@example.com")

        self._resume_with(wire, payload)

        if runs_the_tool:
            assert wire.recorded_tool_messages() == [("tc-1", "EMAIL SENT to ops@example.com")]
        elif continued_from is not None:
            assert wire.recorded_tool_messages() == [("tc-1", continued_from)]
        else:
            assert [call for call, _ in wire.recorded_tool_messages()] == ["tc-1"]


A_QUESTION_PROMPT = "ask me about the budget"


@needs_interrupt_outcome
class TestAnswersToAQuestionOverTheRoute:
    """A selection of another kind, on the channel that advertised a shape and on the one that did not.

    Nothing of a feedback answer reaches the wire as a tool result, so the run
    the second request produced is the subject: the message it continued from is
    what the model read the selection back as, and that is where a label of
    another kind lands.

    The question text and its labels are read off the emitted interrupt rather
    than restated, so neither half can be held to a shape no client was shown.
    """

    def _paused_on_the_question(self) -> Tuple[Wire, Dict[str, Any]]:
        wire = Wire(_agent_asking_a_question(), emit_interrupt_outcome=True)
        return wire, _interrupts_of(wire.post(A_QUESTION_PROMPT))[0]

    def _asks_for(self, interrupt: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """The one question the interrupt advertised, and the array it wants back."""
        asked = interrupt["responseSchema"]["properties"][interrupts.USER_FEEDBACK_SELECTIONS_KEY]
        (text,) = asked["properties"]
        return text, asked["properties"][text]

    @needs_resume_array
    def test_a_selection_the_question_offered_reaches_the_model(self):
        wire, interrupt = self._paused_on_the_question()
        text, answered = self._asks_for(interrupt)
        picked = answered["items"]["enum"][:1]

        resumed = wire.post(
            A_QUESTION_PROMPT,
            resume=[
                {
                    "interrupt_id": interrupt["id"],
                    "status": "resolved",
                    "payload": {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {text: picked}},
                }
            ],
        )

        assert _errors(resumed) == []
        assert _said(resumed) == "Noted."
        assert wire.recorded_tool_messages() == [("tc-ask", _the_model_was_told(text, picked))]

    @needs_resume_array
    def test_a_selection_that_is_not_a_label_fails_the_run(self):
        """The entry type is declared, so an entry of another kind is refused here.

        A refusal a client can see, rather than the run continuing and the model
        reading a number back as the option somebody chose.
        """
        wire, interrupt = self._paused_on_the_question()
        text, answered = self._asks_for(interrupt)
        assert answered["items"]["type"] == "string"

        resumed = wire.post(
            A_QUESTION_PROMPT,
            resume=[
                {
                    "interrupt_id": interrupt["id"],
                    "status": "resolved",
                    "payload": {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {text: [7]}},
                }
            ],
        )

        assert _errors(resumed), "a selection that is not a label was taken for an answer"
        assert _said(resumed) == ""
        assert wire.recorded_tool_messages() == []

    def test_the_same_selection_in_a_tool_message_reaches_the_model_as_it_always_did(self):
        """The older channel is not held to the shape the interrupt advertised.

        Same payload, same pause, opposite verdict, because this channel took
        answers before this interface described any answer shape and the callers
        it already had were written against that. Restoring a check here would
        refuse a resume Agno used to continue from.
        """
        wire, interrupt = self._paused_on_the_question()
        text, _ = self._asks_for(interrupt)

        resumed = wire.post(
            A_QUESTION_PROMPT,
            messages=[
                {"id": "m1", "role": "user", "content": A_QUESTION_PROMPT},
                {
                    "id": "t1",
                    "role": "tool",
                    "tool_call_id": "tc-ask",
                    "content": json.dumps({interrupts.USER_FEEDBACK_SELECTIONS_KEY: {text: [7]}}),
                },
            ],
        )

        assert _errors(resumed) == []
        assert _said(resumed) == "Noted."
        assert wire.recorded_tool_messages() == [("tc-ask", _the_model_was_told(text, [7]))]


def _the_model_was_told(question: str, selected: List[Any]) -> str:
    """The tool message a resumed feedback pause continues from, as Agno writes it."""
    return f"User feedback received: {json.dumps([{'question': question, 'selected': selected}])}"


# --- Answers arriving on both channels of one request ------------------------


BOTH_CHANNELS_PROMPT = "email ops@example.com and change the background"


def _agent_pausing_on_a_decision_and_a_client_run_tool() -> Agent:
    """An Agent whose one turn proposes a call to decide on and one the client runs.

    Two pause kinds in one turn is what a frontend that runs tools produces. The
    decision comes back in the resume array under the interrupt id it was
    advertised by, and the tool's result comes back as the trailing tool message
    keyed by its tool call, which is how a client-run tool's result has entered
    the conversation since before the array existed.
    """
    return Agent(
        id="interrupt-agent",
        name="Interrupt Agent",
        model=_ProposingSeveralAtOnce(
            [
                ("send_email", {"to": "ops@example.com"}, "tc-confirm"),
                ("change_background", {"color": "blue"}, "tc-extern"),
            ],
            "Both done.",
        ),
        db=InMemoryDb(),
        tools=[send_email, change_background],
        telemetry=False,
    )


def _a_trailing_tool_message(tool_call_id: str, content: str) -> Dict[str, Any]:
    """One tool result in the shape a client puts it in the request body."""
    return {"id": f"t-{tool_call_id}", "role": "tool", "tool_call_id": tool_call_id, "content": content}


BACKGROUND_CHANGED = json.dumps({"ok": True})


def _paused_on_both_kinds(**agui_kwargs: Any) -> Tuple[Wire, List[Dict[str, Any]]]:
    """A wire whose one turn has paused on a decision and on a client-run tool."""
    wire = Wire(_agent_pausing_on_a_decision_and_a_client_run_tool(), **agui_kwargs)
    paused = wire.post(BOTH_CHANNELS_PROMPT)
    assert len(wire.open_interrupt_ids()) == 2, f"the run did not pause on both: {wire.open_interrupt_ids()}"
    return wire, paused


class TestBothPausesAnsweredOnTheOlderChannelAlone:
    """The control the mixed request below is measured against.

    Both answers in trailing tool messages is what a client sent before the
    resume array existed, and it resolves. A client that moves one of those two
    answers onto the array must not be the one that gets refused.
    """

    def test_two_trailing_tool_messages_answer_both_pauses(self):
        wire, _ = _paused_on_both_kinds()

        resumed = wire.post(
            BOTH_CHANNELS_PROMPT,
            messages=[
                {"id": "m1", "role": "user", "content": BOTH_CHANNELS_PROMPT},
                _a_trailing_tool_message("tc-confirm", json.dumps({"accepted": True})),
                _a_trailing_tool_message("tc-extern", BACKGROUND_CHANGED),
            ],
        )

        assert _errors(resumed) == []
        assert EMAILS_SENT == ["ops@example.com"]


@needs_interrupt_outcome
@needs_resume_array
class TestARequestCarryingBothChannels:
    """One pause answered on both channels at once, over the route.

    The two channels are not two spellings of one answer: the array addresses
    interrupts by id, and a trailing tool message is how a frontend-executed
    tool's result enters the conversation, keyed by tool call. One turn can pause
    on both kinds at once, so a client running frontend tools sends exactly this
    mixture, and dropping either channel leaves the pause it answered open for
    the completeness guard to fail the run over.
    """

    def _paused_on_both(self) -> Tuple[Wire, Dict[str, str]]:
        """The wire and the interrupt id advertised for each pending call."""
        wire, paused = _paused_on_both_kinds(emit_interrupt_outcome=True)
        advertised = {interrupt["toolCallId"]: interrupt["id"] for interrupt in _interrupts_of(paused)}
        assert sorted(advertised) == ["tc-confirm", "tc-extern"], f"the run did not advertise both: {advertised}"
        return wire, advertised

    def test_each_channel_answers_the_pause_it_was_sent_for(self):
        """The decision and the client-run tool's result both land, and the run continues."""
        wire, advertised = self._paused_on_both()

        resumed = wire.post(
            BOTH_CHANNELS_PROMPT,
            resume=[{"interrupt_id": advertised["tc-confirm"], "status": "resolved", "payload": {"accepted": True}}],
            messages=[
                {"id": "m1", "role": "user", "content": BOTH_CHANNELS_PROMPT},
                _a_trailing_tool_message("tc-extern", BACKGROUND_CHANGED),
            ],
        )

        assert _errors(resumed) == []
        assert _said(resumed) == "Both done."
        assert EMAILS_SENT == ["ops@example.com"]
        assert _tool_results(resumed) == {"tc-confirm": json.dumps("EMAIL SENT to ops@example.com")}
        assert wire.recorded_tool_messages() == [
            ("tc-confirm", "EMAIL SENT to ops@example.com"),
            ("tc-extern", BACKGROUND_CHANGED),
        ]

    def test_a_pause_the_two_channels_together_leave_open_still_fails_the_run(self):
        """Merging the channels is not a way around the completeness guard.

        The array answers the decision and nothing answers the client-run tool,
        so the merged result is still a partial resume, and a partial resume
        reaches dispatch as an answer nobody gave.
        """
        wire, advertised = self._paused_on_both()

        resumed = wire.post(
            BOTH_CHANNELS_PROMPT,
            resume=[{"interrupt_id": advertised["tc-confirm"], "status": "resolved", "payload": {"accepted": True}}],
        )

        assert [error for error in _errors(resumed) if "Partial resume" in error], _errors(resumed)
        assert advertised["tc-extern"] in _errors(resumed)[0]
        assert EMAILS_SENT == []


# --- Writing the answers onto the requirements -------------------------------


def _tool_message(tool_call_id: str, content: str, error: Optional[str] = None) -> Any:
    """One trailing tool message, in the shape the protocol model presents."""
    from ag_ui.core.types import ToolMessage

    return ToolMessage(id=f"m-{tool_call_id}", role="tool", content=content, tool_call_id=tool_call_id, error=error)


def _answer_by_resume_entry(requirement: RunRequirement, payload: Any) -> None:
    resolve_requirements_from_resume_entries(
        [requirement], [_Entry(interrupts.interrupt_id_of(requirement), payload=payload)]
    )


def _answer_by_tool_message(requirement: RunRequirement, payload: Any) -> None:
    resolve_requirements_from_tool_messages(
        [requirement], [_tool_message(requirement.tool_execution.tool_call_id, json.dumps(payload))]
    )


# The two ways an answer reaches a paused requirement, for the payloads both of
# them read. Where they part is stated by the tests that name one channel: what
# an unreadable answer means, and which spelling of a decision each one reads.
both_channels = pytest.mark.parametrize(
    "answer",
    [_answer_by_resume_entry, _answer_by_tool_message],
    ids=["resume_entry", "tool_message"],
)


def _a_pause_whose_answered_twin_shares_an_open_id() -> List[RunRequirement]:
    """Two requirements under one id, the one already answered listed second.

    The id is the pending tool call, which is what a requirement carrying none of
    its own is keyed by, and the answered twin is what a lookup built over every
    requirement rather than the open ones keeps.
    """
    still_open = _requirement(_confirmation("tc-shared"))
    already_answered = _requirement(_confirmation("tc-shared"))
    for requirement in (still_open, already_answered):
        requirement.id = None
    already_answered.confirm()
    return [still_open, already_answered]


class TestTheIdTheTerminalAdvertisedIsTheIdResumeAnswers:
    """Both sides of the round trip key answers off the same population.

    The terminal advertises what the run's open requirements need, so an id it
    hands a client has to be one the resume side writes that client's answer
    onto. Built over two different populations they disagree, and the client is
    refused for answering exactly the id it was given.
    """

    def test_an_answered_twin_does_not_shadow_the_open_requirement_it_shares_an_id_with(self):
        requirements = _a_pause_whose_answered_twin_shares_an_open_id()
        advertised = [needed.interrupt_id for needed in interrupts.answers_a_pause_needs(requirements)]
        assert advertised == ["tc-shared"], "the terminal did not advertise the open requirement's id"

        resolve_requirements_from_resume_entries(requirements, [_Entry("tc-shared", payload={"accepted": True})])

        assert requirements[0].tool_execution.confirmed is True

    def test_an_answer_the_run_already_holds_is_still_passed_over_in_silence(self, caplog):
        """A replay is not an entry naming an interrupt the run does not carry.

        A client that re-sent a body the run has already been continued from
        addresses an id this pause really does hold, so it is left alone rather
        than warned about as an entry for some other run.
        """
        already_answered = _requirement(_confirmation("tc-answered"))
        already_answered.confirm()
        still_open = _requirement(_confirmation("tc-open"))

        with captured_agno_logs(caplog, "WARNING"):
            resolve_requirements_from_resume_entries(
                [already_answered, still_open],
                [
                    _Entry(interrupts.interrupt_id_of(already_answered), payload={"accepted": False}),
                    _Entry(interrupts.interrupt_id_of(still_open), payload={"accepted": True}),
                ],
            )

        assert already_answered.tool_execution.confirmed is True, "a replay overwrote the answer the run holds"
        assert still_open.tool_execution.confirmed is True
        assert interrupts.interrupt_id_of(already_answered) not in caplog.text


def _a_pause_whose_two_open_requirements_share_one_tool_call() -> List[RunRequirement]:
    """Three open requirements of one pause, two of them waiting on one call.

    Each carries an id of its own, so the terminal advertises three answers and
    the guard holds a resume to all three. The two under one call are where the
    round trip's two keys meet: an entry names the interrupt it answers, and a
    trailing tool result names the call.
    """
    return [
        _requirement(_confirmation("tc-one", "send_email")),
        _requirement(_external("tc-same", "change_background")),
        _requirement(_confirmation("tc-same", "wire_funds")),
    ]


class TestOneToolResultCannotAnswerTwoInterrupts:
    """A request whose result would land on two open interrupts is refused.

    The older channel matches a tool result to every open requirement waiting on
    its call. It answered that way before this interface advertised an id to
    answer by and its own callers were written against it, so that is not what
    changes here, and neither is the terminal: a pause can hold two requirements
    for one real call, where one result answers both, and a stored run read back
    cannot be told from two calls a model numbered alike. What can tell them
    apart is the request, which says which interrupts the client answered by id.

    So a request that leaves two of them open under one call and reports a result
    for it is refused: otherwise one answer a client sent once resolves two, and
    the completeness guard sees a pause fully answered.
    """

    def test_a_result_two_open_interrupts_wait_on_is_refused_naming_both(self):
        requirements = _a_pause_whose_two_open_requirements_share_one_tool_call()
        answered_by_id, *under_one_call = [interrupts.interrupt_id_of(each) for each in requirements]

        with pytest.raises(ValueError) as refused:
            resolve_requirements_from_resume_entries(
                requirements,
                [_Entry(answered_by_id, payload={interrupts.CONFIRMATION_ACCEPTED_KEY: True})],
                [_tool_message("tc-same", BACKGROUND_CHANGED)],
            )

        assert all(interrupt_id in str(refused.value) for interrupt_id in under_one_call), str(refused.value)
        assert [each.is_resolved() for each in requirements] == [False, False, False], (
            "an answer was written onto a requirement before the request was refused"
        )

    def test_the_result_lands_where_the_array_answered_the_other_interrupt(self):
        """What is refused is the ambiguity, not the two channels meeting.

        A client that answered one of the two by id left one open requirement on
        that call, so the result it sent beside it has one place to go.
        """
        requirements = _a_pause_whose_two_open_requirements_share_one_tool_call()

        resolve_requirements_from_resume_entries(
            requirements,
            [
                _Entry(
                    interrupts.interrupt_id_of(requirements[0]),
                    payload={interrupts.CONFIRMATION_ACCEPTED_KEY: True},
                ),
                _Entry(
                    interrupts.interrupt_id_of(requirements[2]),
                    payload={interrupts.CONFIRMATION_ACCEPTED_KEY: False},
                ),
            ],
            [_tool_message("tc-same", BACKGROUND_CHANGED)],
        )

        assert requirements[1].external_execution_result == BACKGROUND_CHANGED
        assert requirements[2].tool_execution.confirmed is False

    def test_a_request_carrying_no_result_for_that_call_is_not_refused(self):
        """The array alone addresses each of them by its own id, so it is enough."""
        requirements = _a_pause_whose_two_open_requirements_share_one_tool_call()

        resolve_requirements_from_resume_entries(
            requirements,
            [
                _Entry(
                    interrupts.interrupt_id_of(requirements[0]),
                    payload={interrupts.CONFIRMATION_ACCEPTED_KEY: True},
                ),
                _Entry(interrupts.interrupt_id_of(requirements[1]), payload="the client ran it"),
                _Entry(
                    interrupts.interrupt_id_of(requirements[2]),
                    payload={interrupts.CONFIRMATION_ACCEPTED_KEY: True},
                ),
            ],
        )

        assert [each.is_resolved() for each in requirements] == [True, True, True]

    def test_the_older_channel_alone_still_answers_every_requirement_on_the_call(self):
        """Base behaviour, pinned: nothing above changes what that channel does.

        A request carrying no resume array never reaches the guard, and one
        result resolving every requirement waiting on its call is what Agno did
        there before any of this, for every caller written against it.
        """
        requirements = _a_pause_whose_two_open_requirements_share_one_tool_call()

        resolve_requirements_from_tool_messages(requirements, [_tool_message("tc-same", BACKGROUND_CHANGED)])

        assert requirements[1].external_execution_result == BACKGROUND_CHANGED
        assert requirements[2].tool_execution.confirmed is False

    def test_two_requirements_recorded_for_one_real_call_are_answered_by_id_as_they_were(self):
        """The shape the refusal must not reach: one call, recorded twice.

        Both are advertised, because a client that was told about one of them
        would be refused over the one nobody named, and answering each by its own
        id resolves the pause. The refusal above is about a request that leaves
        them to a result keyed by the call, not about the pause.
        """
        one_call = _confirmation("tc-twice")
        requirements = [_requirement(one_call), _requirement(one_call)]
        advertised = [needed.interrupt_id for needed in interrupts.answers_a_pause_needs(requirements)]
        assert len(advertised) == 2, "the pause stopped advertising both answers it needs"

        resolve_requirements_from_resume_entries(
            requirements,
            [_Entry(interrupt_id, payload={interrupts.CONFIRMATION_ACCEPTED_KEY: True}) for interrupt_id in advertised],
        )

        assert [each.is_resolved() for each in requirements] == [True, True]

    @needs_interrupt_outcome
    @needs_resume_array
    def test_the_refusal_reaches_the_client_and_the_run_does_not_go_on(self):
        """Over the route, on a stored pause holding two requirements for one call.

        The pause is a real one; the second requirement on its client-run call is
        written onto the stored run, because a model has to number two of its
        calls alike for a run to record that and nothing else about the request
        would differ. What the second request does to it is the subject, and that
        is the route's own: one result for the call, one decision answered by id,
        and the completeness guard would have read the pause as answered.
        """
        agent = _agent_pausing_on_a_decision_and_a_client_run_tool()
        wire = Wire(agent, emit_interrupt_outcome=True)
        paused = wire.post(BOTH_CHANNELS_PROMPT)
        advertised = {interrupt["toolCallId"]: interrupt["id"] for interrupt in _interrupts_of(paused)}
        recorded = agent.get_session(session_id=THREAD_ID).runs[-1]
        recorded.requirements.append(_requirement(_confirmation("tc-extern", "wire_funds")))
        also_waiting = interrupts.interrupt_id_of(recorded.requirements[-1])

        resumed = wire.post(
            BOTH_CHANNELS_PROMPT,
            resume=[{"interrupt_id": advertised["tc-confirm"], "status": "resolved", "payload": {"accepted": True}}],
            messages=[
                {"id": "m1", "role": "user", "content": BOTH_CHANNELS_PROMPT},
                _a_trailing_tool_message("tc-extern", BACKGROUND_CHANGED),
            ],
        )

        assert _errors_naming(resumed, advertised["tc-extern"], also_waiting), _errors(resumed)
        assert _said(resumed) == "", "the run went on from a pause one answer had resolved twice"
        assert EMAILS_SENT == []


class TestResolvingResumeEntries:
    def test_every_open_requirement_has_to_be_answered(self):
        """A partial resume is silently declined at dispatch, so it stops here.

        The protocol says one resume array addresses every open interrupt of the
        interrupted run, and an unanswered confirmation reaching dispatch is read
        there as a refusal the client never gave.
        """
        answered = _requirement(_confirmation("tc-a"))
        unanswered = _requirement(_confirmation("tc-b"))

        with pytest.raises(ValueError, match="still unresolved"):
            resolve_requirements_from_resume_entries(
                [answered, unanswered],
                [_Entry(interrupts.interrupt_id_of(answered), payload={"accepted": True})],
            )

    def test_the_refusal_names_the_ids_this_channel_is_addressed_by(self):
        """A resume array answers interrupts, so a refusal naming tool calls
        named something the client never sent."""
        answered = _requirement(_confirmation("tc-a"))
        unanswered = _requirement(_confirmation("tc-b"))

        with pytest.raises(ValueError) as refused:
            resolve_requirements_from_resume_entries(
                [answered, unanswered],
                [_Entry(interrupts.interrupt_id_of(answered), payload={"accepted": True})],
            )

        assert interrupts.interrupt_id_of(unanswered) in str(refused.value)
        assert "tc-b" not in str(refused.value)

    def test_a_requirement_with_no_id_at_all_is_still_named_by_something(self):
        """The refusal could name an empty list or a null, which named nothing to answer."""
        nameless = _requirement(_confirmation("tc-nameless"))
        del nameless.id
        nameless.tool_execution.tool_call_id = None

        assert interrupts.interrupt_id_of(nameless) is None
        with pytest.raises(ValueError, match="1 carrying no id to name them by"):
            ensure_requirements_resolved([nameless])

    def test_an_entry_naming_no_requirement_is_skipped_rather_than_matched(self, caplog):
        """Skipped, and never answered off some other pause that happens to be open."""
        requirement = _requirement(_confirmation())

        with captured_agno_logs(caplog, "WARNING"):
            resolve_requirements_from_resume_entries(
                [requirement],
                [
                    _Entry("no-such-interrupt", payload={"accepted": False}),
                    _Entry(interrupts.interrupt_id_of(requirement), payload={"accepted": True}),
                ],
            )

        assert requirement.tool_execution.confirmed is True
        assert "no-such-interrupt" in caplog.text

    def test_a_cancelled_decision_is_declined_with_the_reason(self):
        requirement = _requirement(_confirmation())

        resolve_requirements_from_resume_entries(
            [requirement], [_Entry(interrupts.interrupt_id_of(requirement), status="cancelled")]
        )

        assert requirement.tool_execution.confirmed is False
        assert requirement.confirmation_note == CANCELLED_NOTE

    def test_a_cancelled_client_run_tool_reports_back_as_a_failure(self):
        """The model has to learn the tool did not run, not read the reason as output."""
        requirement = _requirement(_external())

        resolve_requirements_from_resume_entries(
            [requirement], [_Entry(interrupts.interrupt_id_of(requirement), status="cancelled")]
        )

        assert requirement.tool_execution.tool_call_error is True
        assert requirement.external_execution_result == CANCELLED_NOTE

    @pytest.mark.parametrize("pending", [_user_input(), _user_feedback()], ids=["user_input", "user_feedback"])
    def test_a_cancelled_request_for_input_cannot_be_resolved(self, pending):
        requirement = _requirement(pending)

        with pytest.raises(ValueError, match="cannot be resumed without"):
            resolve_requirements_from_resume_entries(
                [requirement], [_Entry(interrupts.interrupt_id_of(requirement), status="cancelled")]
            )

    @pytest.mark.parametrize("pending", [_user_input(), _user_feedback()], ids=["user_input", "user_feedback"])
    def test_a_failed_request_for_input_cannot_be_resolved_either(self, pending):
        """There is no failure to record on a pause that is waiting on data.

        A declined tool call and a client-run tool both have somewhere to put
        the reason. A request for input has none, so a client reporting that it
        could not collect the data leaves the run as unresumable as a
        cancellation does, and the reason it gave is what says so.
        """
        requirement = _requirement(pending)

        with pytest.raises(ValueError, match="the form could not be shown"):
            resolve_requirements_from_resume_entries(
                [requirement],
                [
                    _Entry(
                        interrupts.interrupt_id_of(requirement),
                        metadata={
                            interrupts.RESUME_METADATA_NAMESPACE: {
                                interrupts.RESUME_ERROR_KEY: "the form could not be shown"
                            }
                        },
                    )
                ],
            )

        assert requirement.is_resolved() is False

    def test_a_client_run_tools_structured_result_is_stored_as_json(self):
        """A frontend parses the result back, so a Python repr is not what it needs."""
        requirement = _requirement(_external())

        resolve_requirements_from_resume_entries(
            [requirement],
            [_Entry(interrupts.interrupt_id_of(requirement), payload={"ok": True, "changed": ["body"]})],
        )

        assert json.loads(requirement.external_execution_result) == {"ok": True, "changed": ["body"]}

    def test_a_client_run_tools_text_result_is_stored_as_it_arrived(self):
        requirement = _requirement(_external())

        resolve_requirements_from_resume_entries(
            [requirement], [_Entry(interrupts.interrupt_id_of(requirement), payload="the client changed it")]
        )

        assert requirement.external_execution_result == "the client changed it"

    def test_an_answer_already_written_is_left_alone(self):
        """A replayed entry must not overwrite the answer the run already holds."""
        requirement = _requirement(_confirmation())
        entry = _Entry(interrupts.interrupt_id_of(requirement), payload={"accepted": True})

        resolve_requirements_from_resume_entries([requirement], [entry])
        resolve_requirements_from_resume_entries([requirement], [entry])

        assert requirement.tool_execution.confirmed is True

    def test_a_requirement_with_no_stored_id_is_keyed_by_its_tool_call(self):
        """The id is what an answer comes back under, so there has to be one."""
        requirement = _requirement(_confirmation("tc-keyed"))
        del requirement.id

        assert interrupts.interrupt_id_of(requirement) == "tc-keyed"

        resolve_requirements_from_resume_entries([requirement], [_Entry("tc-keyed", payload={"accepted": True})])

        assert requirement.tool_execution.confirmed is True

    def test_a_failure_report_with_no_reason_stops_the_resume(self):
        """Dropping it stores the payload as the result and says the tool ran."""
        requirement = _requirement(_external())

        with pytest.raises(ValueError, match="non-empty string"):
            resolve_requirements_from_resume_entries(
                [requirement],
                [
                    _Entry(
                        interrupts.interrupt_id_of(requirement),
                        payload={"ok": False},
                        metadata={interrupts.RESUME_METADATA_NAMESPACE: {interrupts.RESUME_ERROR_KEY: True}},
                    )
                ],
            )

        assert requirement.is_resolved() is False

    @pytest.mark.parametrize(
        "envelope",
        [
            {interrupts.RESUME_ERROR_KEY: "TypeError: color is not a string"},
            {interrupts.RESUME_METADATA_NAMESPACE: "TypeError: color is not a string"},
        ],
        ids=["outside_the_namespace", "as_the_namespace_itself"],
    )
    def test_a_failure_reported_in_another_shape_is_read_rather_than_dropped(self, envelope):
        """A report only read inside the advertised namespace was dropped elsewhere.

        Which stores the payload beside it as the tool's result and tells the
        model the tool ran, the one thing the resolver must never do with an
        entry that said it failed.
        """
        requirement = _requirement(_external())

        resolve_requirements_from_resume_entries(
            [requirement],
            [_Entry(interrupts.interrupt_id_of(requirement), payload={"ok": False}, metadata=envelope)],
        )

        assert requirement.tool_execution.tool_call_error is True
        assert requirement.external_execution_result == "TypeError: color is not a string"

    def test_a_report_in_another_shape_naming_no_reason_is_refused_too(self):
        """Present and unreadable is refused wherever it sits, for the same reason."""
        requirement = _requirement(_external())

        with pytest.raises(ValueError, match="non-empty string"):
            resolve_requirements_from_resume_entries(
                [requirement],
                [
                    _Entry(
                        interrupts.interrupt_id_of(requirement),
                        payload={"ok": False},
                        metadata={interrupts.RESUME_METADATA_NAMESPACE: 500},
                    )
                ],
            )

        assert requirement.is_resolved() is False

    def test_an_error_the_entry_leaves_empty_is_no_failure_report(self):
        """The protocol allows a null under any metadata key, so it reports nothing."""
        requirement = _requirement(_external())

        resolve_requirements_from_resume_entries(
            [requirement],
            [
                _Entry(
                    interrupts.interrupt_id_of(requirement),
                    payload="the client changed it",
                    metadata={interrupts.RESUME_METADATA_NAMESPACE: {interrupts.RESUME_ERROR_KEY: None}},
                )
            ],
        )

        assert requirement.external_execution_result == "the client changed it"
        assert requirement.tool_execution.tool_call_error is not True

    def test_an_entry_carrying_no_metadata_at_all_still_resolves(self):
        """The envelope is an optional part of the protocol, so it is read as one."""
        requirement = _requirement(_external())
        entry = _Entry(interrupts.interrupt_id_of(requirement), payload="the client changed it")
        del entry.metadata

        resolve_requirements_from_resume_entries([requirement], [entry])

        assert requirement.external_execution_result == "the client changed it"

    def test_a_cancelled_entry_stays_the_cancellation_it_declares(self):
        """Cancelling is abandoning the question, whatever envelope rides along."""
        requirement = _requirement(_external())

        resolve_requirements_from_resume_entries(
            [requirement],
            [
                _Entry(
                    interrupts.interrupt_id_of(requirement),
                    status="cancelled",
                    metadata={
                        interrupts.RESUME_METADATA_NAMESPACE: {interrupts.RESUME_ERROR_KEY: "the tool never ran"}
                    },
                )
            ],
        )

        assert requirement.tool_execution.tool_call_error is True
        assert requirement.external_execution_result.startswith(CANCELLED_NOTE)

    @pytest.mark.parametrize(
        "pending,payload",
        [
            (_confirmation, {interrupts.CONFIRMATION_ACCEPTED_KEY: True}),
            (_user_input, {interrupts.USER_INPUT_VALUES_KEY: {"topic": "otters"}}),
            (_user_feedback, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {"What budget?": ["low"]}}),
        ],
        ids=["decision", "input", "feedback"],
    )
    def test_an_answer_sent_as_a_string_is_read_as_the_answer_it_carries(self, pending, payload):
        """The same payload the tool-message channel parses out of a string.

        A client that put its JSON in a string answered on one channel and was
        refused on the other, for a difference in how the two read one payload
        rather than in what they mean. Both go through one parser now.
        """
        requirement = _requirement(pending())

        _answer_by_resume_entry(requirement, json.dumps(payload))

        assert requirement.is_resolved() is True

    def test_a_resolved_entry_carrying_no_result_is_refused_like_a_decision_with_none(self):
        """One entry shape, one verdict, whichever pause kind it addresses.

        Resolving a client-run tool from nothing stored a result nobody returned
        and told the model the tool ran, while the same entry against a decision
        was already refused. A client that ran nothing cancels instead, and one
        whose tool returned nothing sends an empty result rather than none.
        """
        ran_a_tool = _requirement(_external())
        decided = _requirement(_confirmation())

        with pytest.raises(ValueError, match="no result"):
            resolve_requirements_from_resume_entries([ran_a_tool], [_Entry(interrupts.interrupt_id_of(ran_a_tool))])
        with pytest.raises(ValueError, match="confirmation expects"):
            resolve_requirements_from_resume_entries([decided], [_Entry(interrupts.interrupt_id_of(decided))])

        assert (ran_a_tool.is_resolved(), decided.is_resolved()) == (False, False)

    def test_a_tool_that_returned_nothing_still_resolves_with_an_empty_result(self):
        """The refusal above is about an entry with no answer, not about an empty one."""
        requirement = _requirement(_external())

        _answer_by_resume_entry(requirement, "")

        assert requirement.is_resolved() is True
        assert requirement.external_execution_result == ""

    def test_a_status_the_protocol_does_not_declare_is_refused(self):
        """The protocol declares two statuses and validates the field as a literal of them.

        So this is about an entry that did not come through that model: the
        interface reads the array loosely typed, because the model is there only
        on a release that declares it. A third value taking the resolved path
        answers the interrupt from a payload that means something else, which for
        a decision is a definite answer read off input nothing understood.
        """
        requirement = _requirement(_confirmation())

        with pytest.raises(ValueError, match="status"):
            resolve_requirements_from_resume_entries(
                [requirement],
                [_Entry(interrupts.interrupt_id_of(requirement), status="deferred", payload={"accepted": True})],
            )

        assert requirement.is_resolved() is False


def _nested_deeper_than_python_walks() -> List[Any]:
    """A value both serializers run out of stack walking, as a graph dump can be."""
    outermost: List[Any] = []
    innermost = outermost
    for _ in range(2000):
        deeper: List[Any] = []
        innermost.append(deeper)
        innermost = deeper
    return outermost


class TestAResultThisServerCannotSerialize:
    """A client-run tool's result that JSON refuses, on the way to the model.

    The result is whatever the client's own tool returned, so serializing it can
    fail and rendering it can fail after that. Both are the tool's answer
    arriving in a shape this interface did not choose, and neither is a reason
    to replace the tool's result with a stringification error, or to hand the
    model a Python rendering nothing recorded.
    """

    def test_a_result_json_refuses_is_recorded_and_handed_over_as_its_python_rendering(self, caplog):
        """The fallback is the documented one; going unrecorded is what hid it.

        A datetime is the ordinary way a client's tool returns something JSON
        has no spelling for, and the model then reads a Python repr as the tool's
        output. That is the best this interface can do with it, and an operator
        reading the answer the model gave has nothing to trace it by unless the
        fallback says it ran.
        """
        requirement = _requirement(_external())

        with captured_agno_logs(caplog, "WARNING"):
            _answer_by_resume_entry(requirement, {"at": datetime(2020, 1, 1)})

        assert requirement.external_execution_result == "{'at': datetime.datetime(2020, 1, 1, 0, 0)}"
        _record_naming(caplog, "could not serialize a client-run tool's result")

    def test_a_result_that_cannot_be_rendered_at_all_does_not_raise_out_of_the_resume(self, caplog):
        """The fallback ran the payload's own code outside any guard.

        A result whose rendering raises then left the resume reporting a
        stringification error in place of the tool-result problem it was
        handling, which fails the whole resume over the one entry that did
        report a result.
        """
        requirement = _requirement(_external())

        with captured_agno_logs(caplog, "WARNING"):
            _answer_by_resume_entry(requirement, RaisesOnSerialization())

        assert requirement.is_resolved() is True
        assert requirement.external_execution_result == interrupts.UNREADABLE_RESULT_NOTE
        _record_naming(caplog, "could not read a client-run tool's result")

    def test_a_result_nested_deeper_than_the_serializers_walk_is_handled_like_any_other(self, caplog):
        """The depth limit is raised as neither of the two errors the fallback caught.

        Both serializers walk the value recursively, so a deeply nested result
        raises ``RecursionError`` out of each of them in turn. It derives from
        neither ``TypeError`` nor ``ValueError``, so it went straight out of the
        function and out of the resume with it.
        """
        requirement = _requirement(_external())

        with captured_agno_logs(caplog, "WARNING"):
            _answer_by_resume_entry(requirement, _nested_deeper_than_python_walks())

        assert requirement.is_resolved() is True
        assert requirement.external_execution_result == interrupts.UNREADABLE_RESULT_NOTE


# --- A decision, on whichever channel it arrives by --------------------------


# Every payload that says nothing about the proposed call that this interface
# can read. One list, read by both channels below, because what the two differ on
# is what they do with it and not which payloads they cannot read.
decisions_nobody_can_read = pytest.mark.parametrize(
    "payload",
    [
        True,
        "yes",
        {"decision": "approve"},
        {interrupts.CONFIRMATION_ACCEPTED_KEY: "true"},
        {},
    ],
    ids=["not_an_object", "a_bare_string", "an_unrelated_field", "a_non_boolean", "no_fields_at_all"],
)


class TestResolvingADecision:
    """Both channels answer the same question, and read a decision the same way.

    They part on two things, both of them the older channel keeping what it
    already had. What an answer this interface cannot read means: on the
    protocol's own channel it fails the run, because ``reject(note=None)`` is a
    refusal nobody gave and nothing on the wire or in the run's record tells it
    from a real denial, while a trailing tool message declines the call, which is
    what Agno did there before any of this. And which spelling of a decision is
    read: the spec's approval field is named by the interrupt the resume array
    answers, and reading it on the older channel would run a proposed tool that
    channel declined for every caller written against it.
    """

    @decisions_nobody_can_read
    def test_a_decision_nobody_can_read_stops_a_resume_entry(self, payload):
        requirement = _requirement(_confirmation())

        with pytest.raises(ValueError, match="confirmation expects"):
            _answer_by_resume_entry(requirement, payload)

        assert requirement.tool_execution.confirmed is None
        assert requirement.is_resolved() is False

    @decisions_nobody_can_read
    def test_the_same_payload_in_a_tool_message_declines_the_call_as_it_always_did(self, payload):
        """The older channel's answer to it, which this round trip does not get to change.

        Every one of these used to decline the proposed call there. Failing the
        run instead refuses a resume Agno accepted, and the client cannot tell
        the difference from the pause being broken.
        """
        requirement = _requirement(_confirmation())

        _answer_by_tool_message(requirement, payload)

        assert requirement.tool_execution.confirmed is False
        assert requirement.confirmation_note is None
        assert requirement.is_resolved() is True

    def test_an_entry_carrying_no_payload_at_all_stops_the_resume(self):
        requirement = _requirement(_confirmation())

        with pytest.raises(ValueError, match="confirmation expects"):
            resolve_requirements_from_resume_entries([requirement], [_Entry(interrupts.interrupt_id_of(requirement))])

        assert requirement.tool_execution.confirmed is None

    @both_channels
    def test_a_decision_is_written_through_to_the_tool(self, answer):
        """Dispatch reads the nested copy, so a decision that stops at the
        requirement is audited as a refusal."""
        requirement = _requirement(_confirmation())

        answer(requirement, {interrupts.CONFIRMATION_ACCEPTED_KEY: True})

        assert requirement.tool_execution.confirmed is True

    @both_channels
    def test_a_denial_declines_the_call(self, answer):
        requirement = _requirement(_confirmation())

        answer(requirement, {interrupts.CONFIRMATION_ACCEPTED_KEY: False})

        assert requirement.tool_execution.confirmed is False
        assert requirement.confirmation_note is None

    @both_channels
    def test_a_denial_carries_its_note(self, answer):
        requirement = _requirement(_confirmation())

        answer(
            requirement,
            {interrupts.CONFIRMATION_ACCEPTED_KEY: False, interrupts.CONFIRMATION_NOTE_KEY: "wrong recipient"},
        )

        assert (requirement.tool_execution.confirmed, requirement.confirmation_note) == (False, "wrong recipient")

    @pytest.mark.parametrize("decision", [True, False], ids=["approved", "denied"])
    def test_the_interrupt_specs_own_approval_field_is_read_on_the_array(self, decision):
        """A payload written against the spec's own approval example resolves the call.

        On the array only. The interrupt that names the field is what the array
        answers, and the trailing-tool-message channel never advertised it: an
        acceptance spelled that way declined the call there, and reading it would
        run a tool that channel used to refuse, which the table at the wire pins.
        """
        requirement = _requirement(_confirmation())

        _answer_by_resume_entry(requirement, {interrupts.CONFIRMATION_ACCEPTED_ALIAS: decision})

        assert requirement.tool_execution.confirmed is decision

    @pytest.mark.parametrize("decision", [True, False], ids=["approved", "denied"])
    def test_the_spec_field_is_read_past_a_null_under_agnos_own(self, decision):
        """Which key is read is decided by the value, not by the key being there.

        A client that writes both keys and leaves the one it had no value for
        null sent exactly one decision. Reading the empty key refused a resume
        that could have been answered, and the run it was told to continue died.
        """
        requirement = _requirement(_confirmation())

        _answer_by_resume_entry(
            requirement,
            {interrupts.CONFIRMATION_ACCEPTED_KEY: None, interrupts.CONFIRMATION_ACCEPTED_ALIAS: decision},
        )

        assert requirement.tool_execution.confirmed is decision

    @both_channels
    def test_agnos_own_field_stays_authoritative(self, answer):
        requirement = _requirement(_confirmation())

        answer(
            requirement,
            {
                interrupts.CONFIRMATION_ACCEPTED_KEY: False,
                interrupts.CONFIRMATION_ACCEPTED_ALIAS: True,
            },
        )

        assert requirement.tool_execution.confirmed is False

    def test_a_value_under_agnos_field_that_cannot_be_read_is_not_answered_off_the_alias(self):
        """One payload, one verdict, whatever else it carries.

        The same unreadable value was refused alone and, with an alias beside it,
        recorded the alias as the decision: the client wrote a decision under the
        key it meant to be read and it was answered off another. A null under
        that key is different, and the test above is what says so.
        """
        alone = _requirement(_confirmation())
        beside_an_alias = _requirement(_confirmation())
        malformed = {interrupts.CONFIRMATION_ACCEPTED_KEY: "true"}

        with pytest.raises(ValueError, match="confirmation expects"):
            _answer_by_resume_entry(alone, malformed)
        with pytest.raises(ValueError, match="confirmation expects"):
            _answer_by_resume_entry(beside_an_alias, {**malformed, interrupts.CONFIRMATION_ACCEPTED_ALIAS: False})

        assert (alone.is_resolved(), beside_an_alias.is_resolved()) == (False, False)


class TestTheNoteBesideADecision:
    """The note a decision carries, described as the decision that keeps one.

    Agno records a note on a denial, where the model reads it as why the call
    was refused. Its approval path takes none: ``confirm`` has nowhere to put
    one, and a note written on the requirement beside an approval does not
    survive the reload a stored run is read back through, which copies a note to
    the tool only where the decision was a denial. The schema offered the field
    to both decisions all the same, and the approve branch read it and dropped
    it without a word, so a client was told to send something nothing here could
    keep.
    """

    @needs_interrupt_outcome
    def test_the_note_reaches_the_client_described_as_what_keeps_it(self):
        """The advertisement says which decision keeps a note, because it cannot
        do it anywhere else: one schema is advertised for both of them.
        """
        described = _the_schema_advertised_for(_confirmation())["properties"][interrupts.CONFIRMATION_NOTE_KEY]

        assert described == {"type": "string", "description": interrupts.CONFIRMATION_NOTE_DESCRIPTION}

    @both_channels
    def test_a_denial_records_the_note_it_carried_and_says_nothing(self, answer, caplog):
        requirement = _requirement(_confirmation())

        with captured_agno_logs(caplog, "WARNING"):
            answer(
                requirement,
                {
                    interrupts.CONFIRMATION_ACCEPTED_KEY: False,
                    interrupts.CONFIRMATION_NOTE_KEY: "wrong recipient",
                },
            )

        assert requirement.tool_execution.confirmation_note == "wrong recipient"
        assert "wrong recipient" not in caplog.text, "a note the run kept was reported as dropped"

    @both_channels
    def test_an_approval_says_out_loud_that_it_dropped_the_note(self, answer, caplog):
        """The one thing left to do with it: nothing the run records afterwards
        says the note was ever sent.
        """
        requirement = _requirement(_confirmation())

        with captured_agno_logs(caplog, "WARNING"):
            answer(
                requirement,
                {
                    interrupts.CONFIRMATION_ACCEPTED_KEY: True,
                    interrupts.CONFIRMATION_NOTE_KEY: "the vendor is verified",
                },
            )

        assert requirement.tool_execution.confirmed is True
        assert requirement.confirmation_note is None
        assert "the vendor is verified" in caplog.text
        assert requirement.tool_execution.tool_name in caplog.text

    @both_channels
    def test_an_approval_carrying_no_note_says_nothing(self, answer, caplog):
        requirement = _requirement(_confirmation())

        with captured_agno_logs(caplog, "WARNING"):
            answer(requirement, {interrupts.CONFIRMATION_ACCEPTED_KEY: True})

        assert requirement.tool_execution.confirmed is True
        assert interrupts.CONFIRMATION_NOTE_KEY not in caplog.text


class TestTheTrailingToolMessageChannelTakesWhatItAlwaysTook:
    """The channel that predates the advertised schema is not held to it.

    Agno took these answers before this interface described any answer shape,
    and every caller of the tool-message resume was written against that. Holding
    them to a schema the client was never shown refuses a resume the run used to
    continue from: the pause is real, the client answered it, and the run dies on
    a constraint invented afterwards.
    """

    def test_a_field_declared_as_an_integer_still_takes_the_string_it_arrives_as(self):
        requirement = _requirement(_user_input([UserInputField(name="count", field_type=int)]))

        _answer_by_tool_message(requirement, {interrupts.USER_INPUT_VALUES_KEY: {"count": "12"}})

        assert [input_field.value for input_field in requirement.user_input_schema] == ["12"]
        assert requirement.is_resolved() is True

    def test_a_note_of_a_shape_no_schema_offered_still_reaches_the_run(self):
        """Both copies, because a note of another kind is written on both.

        This is what the channel did before any of this interface described an
        answer shape, and the resume array is where a note of another kind is
        refused instead. Dropping it here would be a change to the older channel
        rather than a check restored to it, which is the one thing that channel
        is not allowed: the client answered the question, and what it attached
        to the answer is not this channel's to re-judge.
        """
        requirement = _requirement(_confirmation())

        _answer_by_tool_message(
            requirement,
            {interrupts.CONFIRMATION_ACCEPTED_KEY: False, interrupts.CONFIRMATION_NOTE_KEY: {"why": "wrong"}},
        )

        assert requirement.tool_execution.confirmed is False
        assert requirement.confirmation_note == {"why": "wrong"}
        assert requirement.tool_execution.confirmation_note == {"why": "wrong"}

    def test_a_selection_that_is_not_text_still_reaches_the_run(self):
        """The counterpart of the entry-type check the resume array runs.

        Which channel refuses a value of another kind is the whole of the split:
        the array is this interface's own, so it holds an answer to the shape it
        advertised, and this one predates the shape entirely.
        """
        requirement = _requirement(_user_feedback(multi_select=True))

        _answer_by_tool_message(requirement, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {"What budget?": [7]}})

        assert requirement.is_resolved() is True
        assert requirement.user_feedback_schema[0].selected_options == [7]


# --- Reporting that answering failed, on whichever channel -------------------


def _report_failure_by_resume_entry(requirement: RunRequirement, reason: str, payload: Any = None) -> None:
    resolve_requirements_from_resume_entries(
        [requirement],
        [
            _Entry(
                interrupts.interrupt_id_of(requirement),
                payload=payload,
                metadata={interrupts.RESUME_METADATA_NAMESPACE: {interrupts.RESUME_ERROR_KEY: reason}},
            )
        ],
    )


def _report_failure_by_tool_message(requirement: RunRequirement, reason: str, payload: Any = None) -> None:
    resolve_requirements_from_tool_messages(
        [requirement],
        [
            _tool_message(
                requirement.tool_execution.tool_call_id,
                json.dumps(payload) if payload is not None else "",
                error=reason,
            )
        ],
    )


def _advertised_error_report_path(pending: ToolExecution) -> List[str]:
    """Where the emitted interrupt tells a client to report that its tool failed."""
    events = on_run_completed(_paused(pending), StreamState(emit_interrupt_outcome=True))
    described = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]["metadata"]["agno"]
    return described[interrupts.ERROR_REPORT_PATH_KEY]


def _nested(path: List[str], value: Any) -> Dict[str, Any]:
    """One value at the end of a path, keyed by the entry field the path starts at."""
    for key in reversed(path):
        value = {key: value}
    return value


def _entry_carrying(interrupt_id: str, path: List[str], value: Any) -> "_Entry":
    """One resume entry carrying ``value`` at the path an interrupt advertised.

    The path starts at the entry field a client writes it on, so a path rooted
    anywhere else is an interrupt naming a place the resume channel has none of.
    Read against the fields an entry declares and said here: splatted straight
    in, it arrives as a constructor's arity, which reports this helper rather
    than the advertisement it is about.
    """
    carries = set(inspect.signature(_Entry.__init__).parameters) - {"self", "interrupt_id"}

    assert path and path[0] in carries, (
        f"the advertised report path {path} starts at a field no resume entry carries: {sorted(carries)}"
    )

    return _Entry(interrupt_id, **_nested(path, value))


# The two ways a client says the tool raised. Both channels answer the same
# interrupt, so a failure one of them can report the other has to report too.
both_failure_channels = pytest.mark.parametrize(
    "report_failure",
    [_report_failure_by_resume_entry, _report_failure_by_tool_message],
    ids=["resume_entry", "tool_message"],
)


class TestReportingAFailure:
    """A client whose tool raised has to be able to say so on either channel.

    A trailing tool message has always carried an error field. The resume array
    only ever produced one for a cancelled entry, which left a client on the
    protocol's own channel choosing between reporting the failure as a result,
    which tells the model a tool ran that never did, and cancelling, which the
    protocol reserves for abandoning the question rather than answering it.
    """

    @both_failure_channels
    def test_a_client_run_tool_that_failed_reaches_the_model_as_a_failed_call(self, report_failure):
        """The result the model reads is the reason, and the call is marked failed."""
        requirement = _requirement(_external())

        report_failure(requirement, "TypeError: color is not a string", payload={"ok": False})

        assert requirement.tool_execution.tool_call_error is True
        assert requirement.external_execution_result == "TypeError: color is not a string"

    @both_failure_channels
    def test_a_reported_failure_declines_a_proposed_call(self, report_failure):
        """A client reporting a failure answered the question, so it is a refusal."""
        requirement = _requirement(_confirmation())

        report_failure(requirement, "the prompt was dismissed")

        assert requirement.tool_execution.confirmed is False
        assert requirement.confirmation_note == "the prompt was dismissed"

    @both_failure_channels
    def test_a_reported_failure_prefers_the_note_it_carries(self, report_failure):
        requirement = _requirement(_confirmation())

        report_failure(
            requirement,
            "the prompt was dismissed",
            payload={interrupts.CONFIRMATION_NOTE_KEY: "wrong recipient"},
        )

        assert requirement.tool_execution.confirmed is False
        assert requirement.confirmation_note == "wrong recipient"

    @needs_interrupt_outcome
    def test_a_client_that_followed_the_advertised_path_is_read(self):
        """What is advertised has to be what the resolver reads.

        The entry is built by walking the path off the wire, so an interrupt
        that named a report the resume channel does not read would fail here
        rather than reach a client as a convention that does nothing.
        """
        pending = _external()
        path = _advertised_error_report_path(pending)
        requirement = _requirement(pending)

        resolve_requirements_from_resume_entries(
            [requirement],
            [_entry_carrying(interrupts.interrupt_id_of(requirement), path, "TypeError: color is not a string")],
        )

        assert requirement.tool_execution.tool_call_error is True
        assert requirement.external_execution_result == "TypeError: color is not a string"

    def test_a_client_run_tool_that_worked_is_not_read_as_a_failure(self):
        requirement = _requirement(_external())

        _answer_by_resume_entry(requirement, {"ok": True, "changed": ["body"]})

        assert requirement.tool_execution.tool_call_error is not True
        assert json.loads(requirement.external_execution_result) == {"ok": True, "changed": ["body"]}


def _cancel_reporting(requirement: RunRequirement, reason: Any) -> None:
    """Cancel one interrupt, in the envelope a client reports a failed answer in."""
    resolve_requirements_from_resume_entries(
        [requirement],
        [
            _Entry(
                interrupts.interrupt_id_of(requirement),
                status="cancelled",
                metadata={interrupts.RESUME_METADATA_NAMESPACE: {interrupts.RESUME_ERROR_KEY: reason}},
            )
        ],
    )


class TestACancellationThatSaysWhy:
    """A client that gave up can say why, and the entry carrying both is read as both.

    The status says the question was abandoned and the envelope says what went
    wrong, so the reason is recorded exactly where a resolved entry's is: in what
    the run records about the call. Reading the envelope only on a resolved entry
    lost both halves of that, the reason a run could have recorded and the
    refusal of a report nothing could read.
    """

    def test_a_cancelled_client_run_tool_reports_back_with_the_reason(self):
        requirement = _requirement(_external())

        _cancel_reporting(requirement, "the tool never ran")

        assert requirement.tool_execution.tool_call_error is True
        assert requirement.external_execution_result == f"{CANCELLED_NOTE}: the tool never ran"

    def test_a_cancelled_decision_is_declined_with_the_reason_the_client_gave(self):
        requirement = _requirement(_confirmation())

        _cancel_reporting(requirement, "the user closed the tab")

        assert requirement.tool_execution.confirmed is False
        assert requirement.confirmation_note == f"{CANCELLED_NOTE}: the user closed the tab"

    @pytest.mark.parametrize("pending", [_user_input(), _user_feedback()], ids=["user_input", "user_feedback"])
    def test_a_cancelled_request_for_input_stops_the_run_naming_the_reason(self, pending):
        """Nowhere to record it, so the reason is what the refusal carries."""
        requirement = _requirement(pending)

        with pytest.raises(ValueError, match="the form could not be shown"):
            _cancel_reporting(requirement, "the form could not be shown")

    @pytest.mark.parametrize("status", ["resolved", "cancelled"], ids=["resolved", "cancelled"])
    def test_a_report_naming_no_reason_is_refused_whatever_the_status(self, status):
        """One envelope, one refusal: the status is not what makes a report readable."""
        requirement = _requirement(_external())

        with pytest.raises(ValueError, match="non-empty string"):
            resolve_requirements_from_resume_entries(
                [requirement],
                [
                    _Entry(
                        interrupts.interrupt_id_of(requirement),
                        status=status,
                        metadata={interrupts.RESUME_METADATA_NAMESPACE: {interrupts.RESUME_ERROR_KEY: 500}},
                    )
                ],
            )

        assert requirement.is_resolved() is False


# A failure report path with its nesting moved, for the checks whose subject is
# that one path is advertised and read. Deeper and differently named, so a side
# still reading the old structure finds nothing rather than finding it by luck.
_A_MOVED_REPORT_PATH: Tuple[str, ...] = ("metadata", interrupts.RESUME_METADATA_NAMESPACE, "tool_failure", "reason")


def _as_a_client_reads_it(path: List[str]) -> str:
    """One advertised path as a refusal about it names the place it looked."""
    return path[0] + "".join(f"[{key!r}]" for key in path[1:])


class TestOnePathIsAdvertisedAndRead:
    """Where a client says its own tool failed is one spelling, not two.

    The interrupt advertises the path as a nesting and the resume side walked
    that nesting out by hand. The two shared their last two segments and not
    their structure, so moving the nesting on the advertising side left the
    reader looking where no client was ever told to write, and a client that
    followed the advertisement would have had its report read as a result the
    tool returned.
    """

    @needs_interrupt_outcome
    def test_a_report_is_read_wherever_the_advertised_path_moves_to(self, monkeypatch):
        monkeypatch.setattr(interrupts, "ERROR_REPORT_PATH", _A_MOVED_REPORT_PATH)
        pending = _external()
        advertised = _advertised_error_report_path(pending)
        assert advertised == list(_A_MOVED_REPORT_PATH), "the interrupt advertised something else"
        requirement = _requirement(pending)

        resolve_requirements_from_resume_entries(
            [requirement],
            [_entry_carrying(interrupts.interrupt_id_of(requirement), advertised, "TypeError: color is not a string")],
        )

        assert requirement.tool_execution.tool_call_error is True
        assert requirement.external_execution_result == "TypeError: color is not a string"

    @needs_interrupt_outcome
    def test_a_report_nothing_can_read_is_refused_naming_where_it_was_looked_for(self, monkeypatch):
        """The refusal names the path too, so it is a third place to drift from."""
        monkeypatch.setattr(interrupts, "ERROR_REPORT_PATH", _A_MOVED_REPORT_PATH)
        pending = _external()
        advertised = _advertised_error_report_path(pending)
        requirement = _requirement(pending)

        with pytest.raises(ValueError) as refused:
            resolve_requirements_from_resume_entries(
                [requirement], [_entry_carrying(interrupts.interrupt_id_of(requirement), advertised, 500)]
            )

        assert _as_a_client_reads_it(advertised) in str(refused.value)
        assert requirement.is_resolved() is False

    def test_a_reason_written_straight_onto_the_envelope_is_still_read(self):
        """The one reading that is not the advertised path, kept deliberately.

        A client that wrote the reason on the envelope rather than inside the
        namespace reported a failure all the same, and passing it over stores
        the payload beside it as the tool's result and tells the model a tool
        ran that raised.
        """
        requirement = _requirement(_external())

        resolve_requirements_from_resume_entries(
            [requirement],
            [_Entry(interrupts.interrupt_id_of(requirement), metadata={interrupts.RESUME_ERROR_KEY: "it raised"})],
        )

        assert requirement.tool_execution.tool_call_error is True
        assert requirement.external_execution_result == "it raised"


# --- A pause no answer could resolve ----------------------------------------


@needs_interrupt_outcome
class TestAPauseNoAnswerCouldResolve:
    """A pause holding one requirement nothing resolves ends the run, saying why.

    One resolver runs per requirement, picked by pause kind, and it refuses to
    run unless that kind is what the requirement is still waiting on. A
    requirement with anything left open afterwards fails the partial-resume
    guard, which stops the whole resume. So such a requirement is a dead end for
    the run and not only for itself: a resume has to answer every open one, and
    this is one no client can answer.

    The run therefore ends here rather than waiting. Advertising the
    requirements beside it would strand the run silently, which is the failure
    this replaces: the client answers everything the terminal named, the guard
    refuses the resume over the one it did not, and nothing on the wire ever
    said the run could not go on.
    """

    def _terminal_for(self, pending: ToolExecution, caplog) -> Any:
        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(_paused(pending), StreamState(emit_interrupt_outcome=True))
        assert _advertised_interrupts(events) == NO_OUTCOME_AT_ALL
        return _failed_terminal(events)

    def test_a_call_flagged_for_a_decision_and_for_input_ends_the_run(self, caplog):
        failed = self._terminal_for(_two_pause_kinds(), caplog)

        assert "leaves a decision unresolved" in failed.message
        assert failed.code == interrupts.PAUSE_NOT_CONTINUABLE_CODE
        assert "leaves a decision unresolved" in caplog.text

    def test_a_tool_that_asks_for_input_and_declares_no_field_ends_the_run(self, caplog):
        """There is no key to send a value under, so the schema had nothing in it.

        The interrupt went out with no schema at all, which reads as a pause
        that wants no particular answer, and every answer left it open.
        """
        failed = self._terminal_for(_user_input([]), caplog)

        assert "declares no field" in failed.message
        assert "declares no field" in caplog.text

    def test_an_answerable_pause_beside_it_is_not_advertised_either(self, caplog):
        """Answering it could not continue the run, so offering it would strand it.

        The guard demands every open requirement, so a client answering the one
        the terminal named would be refused over the one it could not name. The
        run ends on the wire instead, and the reason names the requirement that
        ended it.
        """
        chunk = _paused(_two_pause_kinds(), _confirmation("tc-answerable"))

        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True))

        assert _advertised_interrupts(events) == NO_OUTCOME_AT_ALL
        nothing_resolves_it, answerable = chunk.requirements
        message = _failed_terminal(events).message
        assert interrupts.interrupt_id_of(nothing_resolves_it) in message
        assert interrupts.interrupt_id_of(answerable) not in message
        # And a client left with no id to answer is refused with the reason the
        # terminal gave, which is what that terminal is there to say before it
        # tries.
        with pytest.raises(ValueError, match="cannot be continued"):
            _answering_everything_advertised(chunk, [])

    def test_a_pause_whose_one_field_cannot_be_named_ends_the_run(self, caplog):
        """The guard has to ask whether a shape was produced, not count empty fields.

        This field can be keyed to by no payload and is filled already, so a
        census of what is still empty finds nothing to report while the schema
        built from it describes nothing at all. The interrupt went out saying
        input was required and naming no shape for it, which is the one state
        the guard exists to prevent.
        """
        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(
                _paused(_filled_a_field_no_answer_could_name()),
                StreamState(emit_interrupt_outcome=True),
            )

        advertised = _advertised_interrupts(events)
        assert advertised == NO_OUTCOME_AT_ALL, f"advertised with no shape to answer in: {advertised}"
        terminal = _encoded(_failed_terminal(events))
        assert terminal["code"] == interrupts.PAUSE_NOT_CONTINUABLE_CODE
        assert "declares no field" in terminal["message"]

    def test_a_pause_whose_question_answers_for_a_field_it_never_fills_ends_the_run(self, caplog):
        """One flag stands for both structured kinds, and only one of them was given.

        Answering the questions marks the whole call answered, so the run goes on
        with the value the tool asked for still missing and the client never told
        there was one.
        """
        chunk = _paused(_asks_a_question_while_a_field_it_needs_stays_empty())

        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True))

        advertised = _advertised_interrupts(events)
        assert advertised == NO_OUTCOME_AT_ALL, f"advertised an answer that leaves the field empty: {advertised}"
        assert "input values still missing" in _encoded(_failed_terminal(events))["message"]
        # And the resume side reads the same computation, so a client that sent
        # an array anyway is told what the terminal said.
        with pytest.raises(ValueError, match="cannot be continued"):
            _answering_everything_advertised(chunk, [])

    def test_the_count_of_unnamed_fields_reads_as_a_count(self, caplog):
        """This sentence reaches the client inside the failed run's message.

        Two of them reported as one unnamed field reads as a statement about a
        pause that is not the one the run died on.
        """
        failed = self._terminal_for(_waits_on_two_fields_no_answer_could_name(), caplog)

        assert "2 unnamed fields or questions" in _encoded(failed)["message"]

    def test_two_requirements_under_one_id_end_the_run(self, caplog):
        """One correlation key for two answers resolves one and strands the other.

        Which the terminal used to hide: it advertised the first of the two and
        dropped the second as a duplicate id, leaving a requirement no client was
        told about.
        """
        chunk = _paused_where_two_requirements_share_one_id()

        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(chunk, StreamState(emit_interrupt_outcome=True))

        assert _advertised_interrupts(events) == NO_OUTCOME_AT_ALL
        assert "keyed by tc-shared too" in _failed_terminal(events).message

    @pytest.mark.asyncio
    async def test_the_terminal_names_no_member_under_a_visibility_that_names_none(self):
        """The run ends here, and ending it must withhold what prompting withholds.

        The terminal reports the chunk the run ended on, which is the leader's
        own and carries a requirement per member the run was waiting on, each
        naming the member, its id and its run. Whose lane the chunk came from
        says nothing about that: this one is the leader's.
        """
        chunk = _member_paused_on_something_nothing_can_answer()

        events, error = await collect_async(
            [chunk],
            "hidden",
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            emit_interrupt_outcome=True,
        )

        assert error is None
        assert "cannot be continued" in _failed_terminal(events).message
        received = _everything_the_client_received(events)
        assert [named for named in _how_a_pause_names_its_member(chunk) if named in received] == []
        # And the other way a stream names a member: an event of one of the
        # member kinds, or a lane stamped on anything at all.
        assert member_mentions(events) == []

    @pytest.mark.asyncio
    async def test_the_withheld_chunk_reaches_the_operator_instead(self, caplog):
        """Nothing else holds it: the terminal says why the run stopped and no more.

        A client is told nothing about the member, so this line is the only copy
        of the chunk the run died on, and an operator diagnosing the failure has
        it and nothing else.
        """
        chunk = _member_paused_on_something_nothing_can_answer()

        with captured_agno_logs(caplog, "WARNING"):
            events, error = await collect_async(
                [chunk],
                "hidden",
                thread_id=THREAD_ID,
                run_id=RUN_ID,
                emit_interrupt_outcome=True,
            )

        assert error is None
        recorded = [line for line in caplog.messages if "withheld the chunk" in line]
        assert len(recorded) == 1
        assert [named for named in _how_a_pause_names_its_member(chunk) if named not in recorded[0]] == []

    @pytest.mark.asyncio
    async def test_the_visibility_that_names_members_still_reports_the_chunk(self):
        """Withholding it where a member is hidden must not withhold it everywhere.

        Nothing is announced on this path, because the run ends before the pause
        prompt's lanes are, so the chunk the terminal reports is the whole of
        what this stream says about the member the run was waiting on.
        """
        chunk = _member_paused_on_something_nothing_can_answer()

        events, error = await collect_async(
            [chunk],
            attributed(),
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            emit_interrupt_outcome=True,
        )

        assert error is None
        reported = _encoded(_failed_terminal(events))["rawEvent"]
        assert reported["event"] == TeamRunEvent.run_paused.value
        received = json.dumps(reported)
        assert [named for named in _how_a_pause_names_its_member(chunk) if named not in received] == []

    @pytest.mark.asyncio
    async def test_a_pause_with_no_member_in_it_still_reports_its_chunk(self):
        """What is withheld is member identity, not every failed run's diagnostics.

        A pause reports the member fields on every requirement it carries,
        emptily when no member is involved, so a visibility that hid the chunk
        on the sight of those fields would take the dump off every failed
        terminal it has ever been on.
        """
        chunk = _paused(_two_pause_kinds())

        events, error = await collect_async(
            [chunk],
            "hidden",
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            emit_interrupt_outcome=True,
        )

        assert error is None
        assert _encoded(_failed_terminal(events))["rawEvent"]["event"] == RunEvent.run_paused.value


def _two_pause_kinds_as_a_real_run_reports_it() -> Function:
    """One tool carrying two pause flags, which a real run splits across two entries.

    ``@tool`` refuses two of the flags at once, and a ``Function`` configured
    directly does not, which is the only way to obtain the tool the two-kind
    pause is reported for.
    """

    def send_two_ways(to: str, body: str = "") -> str:
        """Send one email."""
        raise AssertionError("a paused call must not run")

    function = Function.from_callable(send_two_ways)
    function.name = "send_email"
    function.requires_confirmation = True
    function.requires_user_input = True
    function.user_input_fields = ["body"]
    return function


def _agent_whose_one_call_is_flagged_for_two_kinds() -> Agent:
    return Agent(
        id="interrupt-agent",
        name="Interrupt Agent",
        model=ScriptedModel("m", [("tool", "send_email", {"to": "ops@example.com"}, "tc-1"), ("content", "Sent.")]),
        db=InMemoryDb(),
        tools=[_two_pause_kinds_as_a_real_run_reports_it()],
        telemetry=False,
    )


def _agent_whose_model_numbers_two_calls_alike() -> Agent:
    return Agent(
        id="interrupt-agent",
        name="Interrupt Agent",
        model=_ProposingSeveralAtOnce(
            [
                ("send_email", {"to": "ops@example.com"}, "tc-same"),
                ("send_email", {"to": "sre@example.com"}, "tc-same"),
            ],
            "Done.",
        ),
        db=InMemoryDb(),
        tools=[send_email],
        telemetry=False,
    )


@needs_interrupt_outcome
class TestTwoPendingCallsUnderOneIdOverTheRoute:
    """A pause whose prompt carries one tool call id twice, driven end to end.

    The refusal above reads one ``ToolExecution`` carrying two pause flags. A
    real run does not report one: it records one entry per flag, both under the
    call's own id, and raises a single requirement for whichever kind it paused
    on. That requirement is answerable, so nothing refuses the pause, and the
    prompt opens the shared id once per entry.

    A model numbering two of its calls alike reaches the same stream by a route
    that needs no flag at all.

    Both are streams this directory's own definition rejects, and both are
    pinned to the violation they break rather than passing unseen. Asking for
    the interrupt outcome does not change either: it is the pause the prompt was
    built from that carries the duplicate, and the outcome is written beside it.
    """

    def test_a_tool_flagged_for_two_kinds_opens_its_id_twice(self):
        wire = Wire(_agent_whose_one_call_is_flagged_for_two_kinds(), emit_interrupt_outcome=True)

        events = wire.post("email ops", malformed=A_CALL_PROMPTED_ONCE_PER_PAUSE_KIND)

        assert [event["toolCallId"] for event in events if event["type"] == "TOOL_CALL_START"] == ["tc-1", "tc-1"]
        assert [interrupt["toolCallId"] for interrupt in _interrupts_of(events)] == ["tc-1"]

    def test_a_model_numbering_two_calls_alike_opens_that_id_twice(self):
        wire = Wire(_agent_whose_model_numbers_two_calls_alike(), emit_interrupt_outcome=True)

        events = wire.post("email ops and sre", malformed=A_CALL_PROMPTED_ONCE_PER_PAUSE_KIND)

        assert [event["toolCallId"] for event in events if event["type"] == "TOOL_CALL_START"] == [
            "tc-same",
            "tc-same",
        ]
        assert [interrupt["toolCallId"] for interrupt in _interrupts_of(events)] == ["tc-same", "tc-same"]


class TestNothingResumesAPauseNoAnswerCouldResolve:
    """Why ending the run is a promise kept rather than a pause withheld.

    Ending it above is only right because no answer would have continued the
    run, and that half is the resume channel refusing the payload, on every
    install: nothing here builds an interrupt or reads one off a terminal, so
    the gate on the class above does not belong on these three.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            {interrupts.USER_INPUT_VALUES_KEY: {"body": "the copy"}},
            {interrupts.CONFIRMATION_ACCEPTED_KEY: True},
            {
                interrupts.CONFIRMATION_ACCEPTED_KEY: True,
                interrupts.USER_INPUT_VALUES_KEY: {"body": "the copy"},
            },
        ],
        ids=["values", "decision", "both"],
    )
    def test_nothing_a_client_could_send_resumes_that_call(self, payload):
        requirement = _requirement(_two_pause_kinds())

        with pytest.raises(ValueError):
            _answer_by_resume_entry(requirement, payload)

        assert requirement.is_resolved() is False

    def test_nothing_a_client_could_send_resumes_that_tool(self):
        requirement = _requirement(_user_input([]))

        with pytest.raises(ValueError):
            _answer_by_resume_entry(requirement, {interrupts.USER_INPUT_VALUES_KEY: {"topic": "otters"}})

        assert requirement.is_resolved() is False

    def test_the_guard_reports_the_same_reason_to_a_client_that_resumed_anyway(self):
        """Nothing stops a client sending a resume array for a pause it was not offered.

        It reaches the guard, which reads the same computation the terminal did,
        so it is told what the terminal said rather than only that something is
        unresolved.
        """
        requirement = _requirement(_two_pause_kinds())

        with pytest.raises(ValueError, match="cannot be continued"):
            _answer_by_resume_entry(requirement, {interrupts.USER_INPUT_VALUES_KEY: {"body": "the copy"}})

    def test_that_reason_is_read_before_an_answer_is_written_onto_anything(self):
        """Otherwise the client is told what Agno's own resolver said instead.

        The resolver this pause's kind picks is one Agno refuses to run, and it
        raises from inside that refusal, which says nothing about why the pause
        was a dead end. The computed reason is the thing the terminal promised,
        so it is what the resume reports.
        """
        requirement = _requirement(_answered_its_questions_and_still_waits_on_a_decision())

        with pytest.raises(ValueError, match="cannot be continued") as refused:
            _answer_by_resume_entry(requirement, {interrupts.USER_FEEDBACK_SELECTIONS_KEY: {"What budget?": ["low"]}})

        assert "is not waiting on" in str(refused.value)
        assert requirement.is_resolved() is False

    def test_a_pause_still_waiting_on_its_values_is_refused_by_agnos_own_reckoning(self):
        """The case the narrowed check leaves to Agno, and it is still caught.

        An answer that fills no field is not refused as a payload: nothing about
        it is of the wrong kind. The field stays empty, Agno counts the
        requirement as unanswered, and the resolved-set guard stops the resume.
        """
        requirement = _requirement(_user_input())

        with pytest.raises(ValueError, match="still unresolved"):
            _answer_by_resume_entry(requirement, {interrupts.USER_INPUT_VALUES_KEY: {}})

        assert requirement.is_resolved() is False


# --- The invariant that reads what the stream encoded ------------------------


class TestUndeclaredKeysAreVisibleOnTheWire:
    """The check every stream in this suite is held to, held to itself.

    An invariant nothing has ever seen fail is one that may be reading nothing,
    which is exactly what the per-field guard it replaces turned out to be
    doing. So a key no model declares is constructed here and the check has to
    name it, at the top level and nested inside the outcome a pause carries.
    """

    def _a_run_terminal_carrying(self, **written: Any) -> Any:
        return RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=THREAD_ID, run_id=RUN_ID, **written)

    def test_an_undeclared_key_on_an_event_is_named(self):
        carried = self._a_run_terminal_carrying(nothing_declares_this="x")

        assert "nothing_declares_this" in _encoded(carried)
        assert undeclared_keys_on_the_wire([carried]) == ["RunFinishedEvent.nothing_declares_this"]

    def test_a_declared_event_is_reported_clean(self):
        """Otherwise a check that names everything would pass the test above."""
        assert undeclared_keys_on_the_wire([self._a_run_terminal_carrying()]) == []

    @needs_interrupt_outcome
    def test_an_undeclared_key_nested_in_the_outcome_is_named_too(self):
        """Which is where every instance of this defect has actually been.

        The interrupt an emit site builds is two models below the event, so a
        check reading only the event's own keys would have seen none of them.
        """
        interrupt = interrupts.Interrupt(id="i-1", reason=interrupts.REASON_TOOL_CALL, nothing_declares_this="x")
        carried = self._a_run_terminal_carrying(outcome=interrupts.interrupt_outcome([interrupt]))

        assert undeclared_keys_on_the_wire([carried]) == [
            "RunFinishedEvent.outcome.interrupts[0].nothing_declares_this"
        ]

    def test_a_key_inside_an_open_object_is_not_one_this_check_can_see(self):
        """Stated rather than left to be discovered as a false clean bill.

        An interrupt's metadata is open by key: what this interface writes there
        is declared by no model, so nothing there can be held to a declaration,
        and a null under one of those keys is a defect this check cannot report.
        The test above it is where a missing tool name is caught instead.
        """
        carried = self._a_run_terminal_carrying(metadata={"anything": {"at_all": None}})

        assert undeclared_keys_on_the_wire([carried]) == []


class TestAValueTheEncoderRefuses:
    """A stream holding what no encoder can render, and what this check makes of it.

    A run's content is whatever a model or a tool put there, so an event can
    carry a value the protocol's encoder refuses, and this interface really does
    emit one: a failing chunk is embedded on the terminal verbatim. Giving up on
    such an event would make the check stop reading at exactly the input a
    hostile run produces, and reporting it clean would be worse than either. So
    the value is stood in for, the keys around it are still read, and the path
    it sat at comes back named. The two answers a reader needs are separate:
    ``undeclared_keys_on_the_wire`` says what no model declares,
    ``values_the_encoder_refused`` says what went unread.
    """

    def _a_run_terminal_carrying(self, **written: Any) -> Any:
        return RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=THREAD_ID, run_id=RUN_ID, **written)

    def test_the_client_gets_no_such_event_at_all(self):
        """The premise: what the encoder refuses is what a response body dies on."""
        carried = self._a_run_terminal_carrying(raw_event={"content": RaisesOnSerialization()})

        with pytest.raises(Exception):
            _encoded(carried)

    def test_the_path_it_sat_at_is_named(self):
        carried = self._a_run_terminal_carrying(raw_event={"content": RaisesOnSerialization()})

        assert values_the_encoder_refused([carried]) == ["RunFinishedEvent.rawEvent.content"]

    def test_a_stream_the_encoder_takes_whole_names_none(self):
        """Otherwise a reader could not tell a refusal from an ordinary stream."""
        assert values_the_encoder_refused([self._a_run_terminal_carrying(raw_event={"content": "readable"})]) == []

    def test_the_keys_around_it_are_still_read(self):
        """The point of standing the value in rather than giving up on the event.

        An undeclared key beside a value nobody can render is the defect this
        whole check exists for, and it is the one a check that skipped the event
        would miss.
        """
        carried = self._a_run_terminal_carrying(
            raw_event={"content": RaisesOnSerialization()}, nothing_declares_this="x"
        )

        assert undeclared_keys_on_the_wire([carried]) == ["RunFinishedEvent.nothing_declares_this"]
        assert values_the_encoder_refused([carried]) == ["RunFinishedEvent.rawEvent.content"]

    def test_an_event_no_stand_in_can_rescue_is_named_whole(self):
        """A structure the encoder refuses, not a leaf it cannot render.

        A payload holding itself has no leaf to stand in for, so this event
        yields no keys at all. Reporting it as an event with no undeclared key
        is the silence this check is built to refuse, so it is named instead.
        """
        carried = self._a_run_terminal_carrying(raw_event=circular())

        assert undeclared_keys_on_the_wire([carried]) == []
        refused = values_the_encoder_refused([carried])
        assert len(refused) == 1
        assert refused[0].startswith("RunFinishedEvent: no key of this event could be read")

    def test_a_stream_that_holds_one_is_refused_unless_it_says_so(self):
        """What every driver in this suite does with the answer.

        Naming the path is how a test whose subject is an unrenderable value
        gets past the check; a stream that grows one nobody named fails, which
        is what keeps the check from quietly reading less than it claims.
        """
        carried = self._a_run_terminal_carrying(raw_event={"content": RaisesOnSerialization()})

        with pytest.raises(AssertionError, match="values the protocol's encoder refuses"):
            _assert_nothing_undeclared_reached_the_client([carried])

        _assert_nothing_undeclared_reached_the_client([carried], ["RunFinishedEvent.rawEvent.content"])

    def test_a_path_named_that_the_encoder_takes_fails_too(self):
        """So a pin that stops being true is a diff rather than a silence."""
        with pytest.raises(AssertionError, match="values the protocol's encoder refuses"):
            _assert_nothing_undeclared_reached_the_client(
                [self._a_run_terminal_carrying(raw_event={"content": "readable"})],
                ["RunFinishedEvent.rawEvent.content"],
            )


# --- A run terminal that cannot be built -------------------------------------


class _TerminalBoom(RuntimeError):
    """A failure raised while the run terminal is being built."""


def _the_terminal_explodes(chunk: Any, state: StreamState) -> List[Any]:
    """The interface's terminal builder, replaced by one that raises.

    Everything the terminal reads comes out of the run: the paused run's own
    words, the arguments of every call it prompts for, the session state it ends
    holding. The reads below drive those one at a time; this one stands for the
    rest of that code and for whatever it grows, which is what the guard around
    the terminal is there for.
    """
    raise _TerminalBoom("terminal exploded")


def _the_advertised_shape_explodes(*_: Any, **__: Any) -> Any:
    """The builder the terminal describes an answer's shape with, replaced by a raiser."""
    raise _TerminalBoom("terminal exploded")


def _a_call_still_running() -> ToolExecution:
    return ToolExecution(tool_call_id="tc-lookup", tool_name="look_up", tool_args={"query": "ops"})


def _mid_message_pause_chunks() -> List[Any]:
    """A run mid-sentence and mid-tool-call when it pauses.

    Both spans are open when the terminal is built, which is exactly what a
    client is left holding if the terminal raises and nothing closes them.
    """
    return [
        RunStartedEvent(run_id=RUN_ID),
        ToolCallStartedEvent(run_id=RUN_ID, tool=_a_call_still_running()),
        RunContentEvent(run_id=RUN_ID, content="working on it"),
        _paused(_confirmation()),
    ]


def _mid_message_member_pause_chunks() -> List[Any]:
    """A run mid-sentence when it pauses inside a member nothing has announced.

    The member's lane is first named by the pause itself, so when the terminal
    starts building, nothing on the wire has mentioned that member at all and
    the only thing that can is the terminal being built.
    """
    return [
        RunStartedEvent(run_id=RUN_ID),
        RunContentEvent(run_id=RUN_ID, content="working on it"),
        _member_paused(_confirmation(), member_run_id="member-run"),
    ]


def _unreadable_failure_chunk() -> Any:
    """A failed terminal whose own message cannot be rendered.

    A run's content is whatever a model or a tool put there, and reading it runs
    that value's own code. This is the failed half of the terminal path: the
    message it renders is also what every span the run left open is closed
    under.
    """
    chunk = RunErrorEvent(run_id=RUN_ID)
    chunk.content = RaisesOnSerialization()
    return chunk


class _NameNobodyCanRender:
    """An event name that reports itself and refuses to be rendered.

    The interface normalizes an event through its ``value``, so a chunk carrying
    this is routed like any other failed run while the fallback that stringifies
    the name raises.
    """

    value = "RunError"

    def __str__(self) -> str:
        raise RuntimeError("event name exploded")


class _NoCopy:
    """A session state value with no copy of its own, as a live handle has none."""

    def __deepcopy__(self, memo: Any) -> Any:
        raise RuntimeError("copy exploded")


def _the_dump_explodes(*_: Any, **__: Any) -> Any:
    raise RuntimeError("dump exploded")


class _ChunksAsAnEntity:
    """An entity whose run is a chunk list, so the route's own mapping is driven.

    The route hands whatever ``arun`` returns to the mapper and reads nothing
    else off an Agent or a Team on this path, which is what keeps the test about
    the body a client receives.
    """

    def __init__(self, chunks: List[Any]) -> None:
        self._chunks = chunks

    def arun(self, **_: Any) -> Any:
        chunks = self._chunks

        async def source() -> Any:
            for chunk in chunks:
                yield chunk

        return source()


def _one_request() -> Any:
    """The request the route reads, carrying nothing but a prompt and a session."""
    return RunAgentInput(
        thread_id=THREAD_ID,
        run_id=RUN_ID,
        state={},
        messages=[UserMessage(id="m1", role="user", content="go")],
        tools=[],
        context=[],
        forwarded_props={},
    )


def _record_naming(caplog: Any, wanted: str) -> Any:
    """The one log record that mentions ``wanted``, refusing several or none."""
    recorded = [record for record in caplog.records if wanted in record.message]
    assert len(recorded) == 1, f"{wanted} was recorded {len(recorded)} times: {[r.message for r in caplog.records]}"
    return recorded[0]


both_mappers = pytest.mark.parametrize("collect", [collect_sync, collect_async], ids=["sync", "async"])


class TestATerminalThatCannotBeBuilt:
    """A raise while the run terminal is built, driven through both mappers.

    The terminal is where this interface does its last and most failable work,
    and it used to sit outside the guard that closes what the stream opened. A
    raise from it sent no span end and no terminal at all, so the client was
    left holding a message and a tool call that never resolve, with the router's
    own in-band error as the only account of how the run stopped.
    """

    @pytest.mark.asyncio
    @both_mappers
    async def test_every_span_the_mapper_opened_is_closed(self, collect, monkeypatch, caplog):
        monkeypatch.setattr(stream_module, "process_completion", _the_terminal_explodes)

        with captured_agno_logs(caplog, "ERROR"):
            events, error = await collect(_mid_message_pause_chunks(), thread_id=THREAD_ID, run_id=RUN_ID)

        assert type(error) is _TerminalBoom, f"the failure did not propagate: {error!r}"
        # Every span closing is one of the invariants the collector runs, so
        # what is left to state is that the two this run had open when the
        # terminal was built are the ones closed, and that they close last.
        assert [short_type(event) for event in events[-2:]] == ["TOOL_CALL_END", "TEXT_MESSAGE_END"]
        assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id") == [("tc-lookup",)]

    @pytest.mark.asyncio
    @both_mappers
    async def test_the_mapper_writes_no_terminal_of_its_own(self, collect, monkeypatch, caplog):
        """Nothing may follow a run terminal, so the caller writes the only one."""
        monkeypatch.setattr(stream_module, "process_completion", _the_terminal_explodes)

        with captured_agno_logs(caplog, "ERROR"):
            events, _ = await collect(_mid_message_pause_chunks(), thread_id=THREAD_ID, run_id=RUN_ID)

        assert [short_type(event) for event in events if "RUN_" in short_type(event)] == []

    @pytest.mark.asyncio
    @both_mappers
    async def test_the_failure_is_recorded_as_the_terminals_and_carries_its_traceback(
        self, collect, monkeypatch, caplog
    ):
        """A cleanup that leaves no trace is the other half of this defect.

        The record has to say what raised and where: a source stream that died
        is the run's own failure, and a terminal that cannot be built is this
        interface's bug, so one record naming the other misdirects whoever reads
        it.
        """
        monkeypatch.setattr(stream_module, "process_completion", _the_terminal_explodes)

        with captured_agno_logs(caplog, "ERROR"):
            await collect(_mid_message_pause_chunks(), thread_id=THREAD_ID, run_id=RUN_ID)

        recorded = _record_naming(caplog, "terminal exploded")
        assert "_TerminalBoom" in recorded.message, f"the record does not name what raised: {recorded.message}"
        assert "run terminal" in recorded.message, f"the record does not say where it raised: {recorded.message}"
        assert RUN_ID in recorded.message, f"the record names no run: {recorded.message}"
        assert recorded.exc_info is not None, "the record carries no traceback, so the raise site is lost"

    @pytest.mark.asyncio
    async def test_the_client_is_told_the_run_failed(self, monkeypatch, caplog):
        """What a client receives, read off the route that streams to it.

        The response is committed and streaming by the time the terminal is
        built, so the only thing that can still say the run failed is another
        event on that same body. The whole body is held to the shared definition
        of a well-formed stream: before the guard it carried an open message and
        an open tool call, then the route's own in-band error, and nothing that
        closed either of them.
        """
        monkeypatch.setattr(stream_module, "process_completion", _the_terminal_explodes)

        with captured_agno_logs(caplog, "ERROR"):
            events = await run_entity(_ChunksAsAnEntity(_mid_message_pause_chunks()), _one_request())

        assert [short_type(event) for event in events[-3:]] == ["TOOL_CALL_END", "TEXT_MESSAGE_END", "RUN_ERROR"]
        assert in_emitted_order(events, EventType.RUN_ERROR, "message") == [("terminal exploded",)]

    @pytest.mark.asyncio
    @needs_interrupt_outcome
    @both_mappers
    async def test_the_answer_shape_the_terminal_advertises_is_inside_the_guard_too(self, collect, monkeypatch, caplog):
        """The terminal's most distant read, and the one only the option reaches.

        Advertising a pause means describing the shape of the answer it wants,
        which happens two modules away from where the terminal is built and is
        the same description the resume side holds an incoming answer to. So it
        is on the terminal path with the option on, and a raise from it has to
        close the same spans and be recorded the same way as any other. Read
        rather than assumed: nothing about it says which guard it sits under.
        """
        monkeypatch.setattr(interrupts, "advertised_answer_schema", _the_advertised_shape_explodes)

        with captured_agno_logs(caplog, "ERROR"):
            events, error = await collect(
                _mid_message_pause_chunks(),
                thread_id=THREAD_ID,
                run_id=RUN_ID,
                emit_interrupt_outcome=True,
            )

        assert type(error) is _TerminalBoom, f"the failure did not propagate: {error!r}"
        assert [short_type(event) for event in events[-2:]] == ["TOOL_CALL_END", "TEXT_MESSAGE_END"]
        assert [short_type(event) for event in events if "RUN_" in short_type(event)] == []
        recorded = _record_naming(caplog, "terminal exploded")
        assert "run terminal" in recorded.message, f"the record does not say where it raised: {recorded.message}"

    @pytest.mark.asyncio
    @needs_interrupt_outcome
    @both_mappers
    async def test_a_member_the_client_never_saw_start_owns_no_terminal(self, collect, monkeypatch, caplog):
        """A lane the pause opened in this interface's own record, on a terminal that never went out.

        The pause names its member's lane and opens it before the announcement
        that tells the client about it is emitted, and that announcement only
        leaves with the terminal. A raise in between left the record holding a
        lane the client had never seen, and the cleanup that follows terminated
        it: a member's terminal for a member nothing ever started.
        """
        require_lineage_events()
        chunk = _member_paused(_confirmation(), member_run_id="member-run")
        monkeypatch.setattr(interrupts, "advertised_answer_schema", _the_advertised_shape_explodes)

        with captured_agno_logs(caplog, "ERROR"):
            events, error = await collect(
                _mid_message_member_pause_chunks(),
                attributed(),
                thread_id=THREAD_ID,
                run_id=RUN_ID,
                emit_interrupt_outcome=True,
            )

        assert type(error) is _TerminalBoom, f"the failure did not propagate: {error!r}"
        # The spans the run did open still close, which is what the guard is for.
        assert [short_type(event) for event in events[-1:]] == ["TEXT_MESSAGE_END"]
        received = _everything_the_client_received(events)
        assert [named for named in _how_a_pause_names_its_member(chunk) if named in received] == []
        assert member_mentions(events) == []


class _RefusesToBeRead:
    """A schema value that raises the moment anything asks whether it is there.

    The advertised shape reads a description, a header, a label and the flag
    capping a question for their truth before anything else is done with them,
    so this is what an in-process value can be: a lazily loaded label whose
    source is gone, a proxy to a store that closed. A schema rebuilt from JSON
    holds scalars and never raises, which is why the other half of this subject
    is a value that reads fine and is not words.
    """

    def __bool__(self) -> bool:
        raise RuntimeError("cannot be tested for truth")


class _OptionsNobodyCanWalk(list):
    """A question's choices that refuse to be walked, as a spent iterator does."""

    def __iter__(self) -> Any:
        raise RuntimeError("options exploded")


def _paused_on_a_field_described_by(description: Any) -> RunPausedEvent:
    described = UserInputField(name="topic", field_type=str)
    described.description = description
    return _paused(_user_input([described]))


def _paused_asking(question: UserFeedbackQuestion) -> RunPausedEvent:
    return _paused(
        ToolExecution(
            tool_call_id="tc-feedback",
            tool_name="ask_user",
            tool_args={},
            requires_user_input=True,
            user_feedback_schema=[question],
        )
    )


def _a_question_headed_by(header: Any) -> UserFeedbackQuestion:
    asked = UserFeedbackQuestion(question="What budget?", options=[UserFeedbackOption(label="low")])
    asked.header = header
    return asked


def _a_question_offering(options: Any) -> UserFeedbackQuestion:
    asked = UserFeedbackQuestion(question="What budget?", options=[UserFeedbackOption(label="low")])
    asked.options = options
    return asked


def _a_question_taking_several(multi_select: Any) -> UserFeedbackQuestion:
    asked = UserFeedbackQuestion(question="What budget?", options=[UserFeedbackOption(label="low")])
    asked.multi_select = multi_select
    return asked


def _text_the_schema_states(described: Any) -> List[Any]:
    """Every value an advertised schema offers a client as words to read.

    Walked rather than read at the paths one test knows about, so a value a
    later builder writes under one of these keywords is held to the same thing
    without the walk having to be told it exists.
    """
    found: List[Any] = []
    if isinstance(described, dict):
        for keyword, value in described.items():
            if keyword in ("description", "title"):
                found.append(value)
            elif keyword == "enum" and isinstance(value, list):
                found += value
            else:
                found += _text_the_schema_states(value)
    elif isinstance(described, list):
        for entry in described:
            found += _text_the_schema_states(entry)
    return found


class TestTheTerminalSurvivesWhatARunPutInIt:
    """The reads the terminal really does, driven with values that refuse them.

    Each of these raised from inside the terminal before, and the guard around
    it cannot put back what a raise discards: the closing sweep is built before
    the pause prompt and the state snapshot, so a raise there loses every span
    end with it while the mapper's own record of those spans says they closed.
    That is why these are guarded where they are read, and the guard around the
    terminal is the backstop for the rest.
    """

    def test_a_pause_whose_arguments_cannot_be_serialized_still_prompts_the_call(self, caplog):
        pending = _confirmation()
        pending.tool_args = circular()

        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(_paused(pending), StreamState(thread_id=THREAD_ID, run_id=RUN_ID))

        assert in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id", "tool_call_name") == [
            ("tc-confirm", "send_email")
        ]
        assert in_emitted_order(events, EventType.TOOL_CALL_ARGS, "delta") == [("{}",)]
        _run_finished(events)
        assert "tc-confirm" in _record_naming(caplog, "could not serialize the arguments").message

    def test_a_pause_whose_words_cannot_be_rendered_still_prompts_the_call(self, caplog):
        chunk = _paused(_confirmation())
        chunk.content = RaisesOnSerialization()

        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(chunk, StreamState(thread_id=THREAD_ID, run_id=RUN_ID))

        assert of_type(events, EventType.TEXT_MESSAGE_CONTENT) == [], "the words nobody can read reached the wire"
        assert in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id") == [("tc-confirm",)]
        _run_finished(events)
        _record_naming(caplog, "a paused run's own words")

    @needs_interrupt_outcome
    @pytest.mark.parametrize(
        ("chunk", "advertises", "unreadable_reads"),
        [
            (_paused_on_a_field_described_by(_RefusesToBeRead()), "topic", 1),
            (_paused_asking(_a_question_headed_by(_RefusesToBeRead())), "What budget?", 1),
            (
                _paused_asking(_a_question_offering(_OptionsNobodyCanWalk([UserFeedbackOption(label="low")]))),
                "What budget?",
                1,
            ),
            (_paused_asking(_a_question_taking_several(_RefusesToBeRead())), "What budget?", 1),
            (_paused_on_a_field_described_by({"nested": "object"}), "topic", 0),
        ],
        ids=[
            "field_description",
            "question_header",
            "question_options",
            "question_multi_select",
            "description_that_is_not_words",
        ],
    )
    def test_a_pause_whose_schema_text_cannot_be_read_still_advertises_the_answer_shape(
        self, chunk, advertises, unreadable_reads, caplog
    ):
        """The words the advertised shape is built out of come off the run.

        A description, a question's header, an option's label and the flag that
        says how many selections a question takes are all values a tool put
        there, and each was read for its truth before anything else was done
        with it. Read unguarded, one that raises took the whole terminal with
        it: no interrupt, no terminal, nothing on the wire saying the run was
        waiting. Written verbatim afterwards, one that is not words leaves a
        schema whose own keywords contradict it, which a client that validates
        before answering can construct no payload for.

        Asserted off the encoded events, because the symptom is that a client
        receives nothing: an assertion over the objects the builder returned
        cannot tell a schema that reached the wire from one that did not.
        """
        with captured_agno_logs(caplog, "WARNING"):
            events = on_run_completed(
                chunk, StreamState(thread_id=THREAD_ID, run_id=RUN_ID, emit_interrupt_outcome=True)
            )

        schema = _outcome_on_the_wire(_run_finished(events))["interrupts"][0]["responseSchema"]
        (answered,) = schema["properties"].values()
        assert list(answered["properties"]) == [advertises], (
            f"the pause is waiting on {advertises!r} and advertises {list(answered['properties'])}"
        )
        stated = _text_the_schema_states(schema)
        assert all(isinstance(text, str) for text in stated), (
            f"the advertised schema states {stated!r} where a client reads words"
        )
        unread = [record for record in caplog.records if "could not read" in record.message]
        assert len(unread) == unreadable_reads, f"{len(unread)} unreadable values recorded: {unread}"

    @pytest.mark.asyncio
    @both_mappers
    async def test_a_session_state_that_cannot_be_copied_still_ends_the_run(self, collect, caplog):
        """The snapshot is the last thing the terminal builds, after the sweep.

        The state it copies is the one the terminal chunk carries, which is not
        the document the request opened with: a run whose tools put a value with
        no copy of its own into the session state reaches this line with
        everything before it already copied.

        The snapshot is dropped rather than sent uncopied, since a state with no
        copy of its own is one the protocol's encoder refuses too, and an event
        it refuses stops the response body short of the terminal.
        """
        chunk = _paused(_confirmation())
        chunk.session_state = {"handle": _NoCopy()}

        with captured_agno_logs(caplog, "ERROR"):
            events, error = await collect(
                [RunContentEvent(run_id=RUN_ID, content="working on it"), chunk],
                thread_id=THREAD_ID,
                run_id=RUN_ID,
                run_state={"draft": "hello"},
            )

        assert error is None, f"a state nothing could copy ended the stream: {error!r}"
        assert of_type(events, EventType.STATE_SNAPSHOT) == [], "a state nothing could copy reached the wire"
        assert_stream_contains(events, EventType.RUN_FINISHED)
        recorded = _record_naming(caplog, "could not copy the session state")
        assert recorded.exc_info is not None, "the record carries no traceback, so the raise site is lost"

    @pytest.mark.asyncio
    @both_mappers
    async def test_a_failure_whose_message_cannot_be_read_still_reports_the_failure(self, collect, caplog):
        """The terminal reports the failure, and embeds the chunk that caused it.

        Embedding it verbatim carries the unreadable value onto the terminal's
        own ``rawEvent``, where the protocol's encoder refuses it and a real
        response body would die at this event. That is the standing report this
        interface makes about a failing chunk it cannot read, so it is named
        here rather than left for the encoded-keys check to discover: the keys
        of this event are still read, the subtree under the named path is not.
        """
        chunks = [
            RunStartedEvent(run_id=RUN_ID),
            RunContentEvent(run_id=RUN_ID, content="halfway"),
            _unreadable_failure_chunk(),
        ]

        with captured_agno_logs(caplog, "WARNING"):
            events, error = await collect(
                chunks,
                thread_id=THREAD_ID,
                run_id=RUN_ID,
                encoder_refuses=["RunErrorEvent.rawEvent.content"],
            )

        assert error is None, f"a failure that cannot describe itself ended the stream: {error!r}"
        assert in_emitted_order(events, EventType.RUN_ERROR, "message") == [("Run failed",)]
        assert_stream_contains(events, EventType.TEXT_MESSAGE_END)
        _record_naming(caplog, "a failed run message")

    @pytest.mark.asyncio
    @both_mappers
    async def test_a_failing_chunk_that_cannot_be_dumped_is_recorded_and_reported_by_name(
        self, collect, monkeypatch, caplog
    ):
        """The chunk the terminal embeds verbatim, and the fallback for it.

        The dump ran behind a guard that logged nothing at all, and its fallback
        stringified the event name unguarded, so a chunk that could neither be
        dumped nor named took down the span closing and the terminal together
        from inside the code reporting why the run stopped.
        """
        chunk = RunErrorEvent(run_id=RUN_ID, content="the model died")
        monkeypatch.setattr(chunk, "to_dict", _the_dump_explodes)
        monkeypatch.setattr(chunk, "event", _NameNobodyCanRender())
        chunks = [RunStartedEvent(run_id=RUN_ID), RunContentEvent(run_id=RUN_ID, content="halfway"), chunk]

        with captured_agno_logs(caplog, "WARNING"):
            events, error = await collect(chunks, thread_id=THREAD_ID, run_id=RUN_ID)

        assert error is None, f"the chunk nothing could read ended the stream: {error!r}"
        assert in_emitted_order(events, EventType.RUN_ERROR, "message", "raw_event") == [
            ("the model died", {"event": "RunError"})
        ]
        assert_stream_contains(events, EventType.TEXT_MESSAGE_END)
        _record_naming(caplog, "could not dump the chunk")


# --- A run that stopped before it could report anything ----------------------


class TestWhatStoppedTheRunReachesTheAssertion:
    """The collectors record what ended a run, whatever base it derives from.

    Everything here that is not driven over the route is driven through those
    collectors, and the events and the failure they return are the whole of what
    an assertion reads. A failure they do not record leaves by raising instead:
    the events collected before it are dropped, no invariant runs on any of them,
    and a test asking what the client was left holding never gets to ask.

    A chunk list holds whatever the source stream does, which includes the one
    failure this interface really meets that is not an ``Exception``: the
    cancellation a disconnected client's request is torn down with, mid-run and
    mid-message.
    """

    @pytest.mark.asyncio
    @both_mappers
    async def test_a_cancelled_run_is_recorded_like_any_other_failure(self, collect):
        events, error = await collect(
            [RunContentEvent(run_id=RUN_ID, content="working on it"), asyncio.CancelledError()],
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            exempt=[ABANDONED_MID_STREAM],
        )

        assert type(error) is asyncio.CancelledError, f"the driver did not record what ended the run: {error!r}"
        # And the prefix the client was left holding reached the invariants,
        # which is the whole of what recording it rather than raising buys.
        assert in_emitted_order(events, EventType.TEXT_MESSAGE_CONTENT, "delta") == [("working on it",)]


# --- Refusing an install that cannot serve the outcome -----------------------


def _the_protocols_own_base_model() -> Any:
    """The base every protocol type is configured by, whatever it is called.

    Its configuration is what decides how a release serializes: which keys it
    keeps, which it omits, and what it does with one it never declared. A
    simulated release built on anything else would answer a different question
    than the installed one.
    """
    for ancestor in interrupts.Interrupt.__mro__:
        if issubclass(ancestor, BaseModel) and not ancestor.model_fields:
            return ancestor
    raise AssertionError("the installed Interrupt declares no configured base model to simulate a release from")


def _type_without(model: Any, field: str) -> Any:
    """This protocol type as a release that does not declare ``field`` presents it.

    A real model, built from the installed one's remaining fields on the same
    configured base, rather than a stand-in carrying only a field table. What a
    release omitting a field costs is what its encoder then writes, and only a
    model can be built from and encoded, so a stand-in can prove that a check
    read the table and nothing at all about what left the server.
    """
    assert field in model.model_fields, f"the installed {model.__name__} declares no {field} for a release to omit"
    kept = {
        name: (model_field.annotation, model_field) for name, model_field in model.model_fields.items() if name != field
    }
    return create_model(model.__name__, __base__=_the_protocols_own_base_model(), **kept)


def _interrupt_type_without(field: str) -> Any:
    return _type_without(interrupts.Interrupt, field)


def _census() -> Dict[Any, Tuple[str, ...]]:
    """Every protocol field this interface feature-detects, per class, all tables read.

    The three tables are three separate releases' worth of pieces and are asked
    of the interface rather than copied here, so a row moved between them is
    still one row to everything below.
    """
    merged: Dict[Any, Tuple[str, ...]] = {}
    for table in (
        interrupts.interrupt_round_trip_fields(),
        interrupts.interrupt_attribution_fields(),
        interrupts.subagent_suspension_fields(),
    ):
        for model, fields in table.items():
            merged[model] = tuple(sorted(set(merged.get(model, ())) | set(fields)))
    return merged


def _everything_a_pause_makes_this_interface_build() -> List[Any]:
    """Every protocol object this interface builds for a pause, from its own builders.

    Built rather than listed: what a builder writes is read back off the object
    it returned, so a field added to one is seen here without any list of field
    names being kept in step by hand.
    """
    requirements = [
        _requirement(pending) for pending in (_confirmation(), _external(), _user_input(), _user_feedback())
    ]
    interrupt_list = [
        interrupts.build_interrupt(
            _needs_answering(requirement),
            tool_call_id=requirement.tool_execution.tool_call_id,
            tool_name=requirement.tool_execution.tool_name,
            subagent_run_id=member,
        )
        for requirement in requirements
        for member in (None, "member-run")
    ]
    built = [
        *interrupt_list,
        interrupts.interrupt_outcome([one for one in interrupt_list if one is not None]),
        interrupts.suspended_outcome(["an-interrupt"]),
        interrupts.suspended_outcome([]),
    ]
    return [one for one in built if one is not None]


def _protocol_types_imported_under_a_guard() -> Set[str]:
    """Every protocol type this interface imports behind an ImportError handler.

    Such a type exists only from the release that introduced it onward, so every
    field written on one or read off one is a field an older install has no
    place for, and a table saying which is the whole of what stands between that
    install and a run that fails halfway. Derived from the source, so a fourth
    type added beside the three is held to the same thing on the day it lands.
    """
    source = ast.parse(Path(inspect.getfile(interrupts)).read_text(encoding="utf-8"))
    guarded: Set[str] = set()
    for node in ast.walk(source):
        if not isinstance(node, ast.Try):
            continue
        caught = {
            name.id
            for handler in node.handlers
            for name in ast.walk(handler.type)
            if handler.type is not None and isinstance(name, ast.Name)
        }
        if "ImportError" not in caught:
            continue
        guarded |= {
            alias.asname or alias.name
            for inner in ast.walk(node)
            if isinstance(inner, ast.ImportFrom)
            for alias in inner.names
        }
    return guarded


# The name the incoming half binds one answer to. Its fields are read straight
# off it, and which fields those are is read from the source below rather than
# written down, so the floor and the reads cannot come apart.
_ONE_ANSWER = "entry"


def _plain_attributes_read_on(source: str, name: str) -> Set[str]:
    """Every attribute this source reads straight off ``name``.

    A lookup carrying a default is not one of these and is not meant to be: it
    answers a release that declares no such field instead of raising on it,
    which is what makes that read safe on an install the floor let through.
    """
    return {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == name
    }


def _the_entry_model() -> Any:
    """The model one answer arrives as, or None on a release that declares none.

    Resolved off the module rather than imported, because a release without it
    is one this suite still runs on.
    """
    import ag_ui.core

    return getattr(ag_ui.core, "ResumeEntry", None)


def _the_incoming_half_as_source() -> str:
    """The module that applies a client's answers, read as text."""
    return Path(inspect.getfile(resume_module)).read_text(encoding="utf-8")


_READ_OFF_ONE_ANSWER = _plain_attributes_read_on(_the_incoming_half_as_source(), _ONE_ANSWER)


class TestStartupCheck:
    def test_the_types_the_emission_needs_are_feature_detected(self, monkeypatch):
        """A field nothing detects rides out under a name the wire format omits."""
        monkeypatch.setattr(interrupts, "INTERRUPT_OUTCOME_AVAILABLE", False)

        with pytest.raises(ValueError, match="interrupt-aware run lifecycle"):
            interrupts.validate_interrupt_outcome(True)

    @needs_interrupt_outcome
    def test_a_missing_field_names_itself(self, monkeypatch):
        """The census this message is built from is only reached once the lifecycle is there."""
        monkeypatch.setattr(interrupts, "_missing_interrupt_fields", lambda: ["Interrupt.toolCallId"])

        with pytest.raises(ValueError, match="Interrupt.toolCallId"):
            interrupts.validate_interrupt_outcome(True)

    def test_the_check_is_silent_when_nothing_is_asked_for(self, monkeypatch):
        monkeypatch.setattr(interrupts, "INTERRUPT_OUTCOME_AVAILABLE", False)

        assert interrupts.validate_interrupt_outcome(False) is False

    def test_the_routes_refuse_the_outcome_when_they_are_mounted(self, monkeypatch):
        """An unserveable setting is a startup failure, not an in-band run error."""
        from agno.os.interfaces.agui import AGUI

        monkeypatch.setattr(interrupts, "INTERRUPT_OUTCOME_AVAILABLE", False)

        with pytest.raises(ValueError, match="interrupt-aware run lifecycle"):
            AGUI(agent=Agent(name="A"), emit_interrupt_outcome=True)

    @needs_interrupt_outcome
    def test_the_field_the_answers_arrive_in_is_part_of_the_floor(self, monkeypatch):
        """A release that does not declare it drops a client's answers unread.

        The outcome tells the client to answer by id, and the resume array is
        where those answers arrive, so an install without it cannot continue the
        run it advertised as waiting.
        """
        monkeypatch.setattr("ag_ui.core.RunAgentInput", type("RunAgentInput", (), {"model_fields": {}}))

        with pytest.raises(ValueError, match="RunAgentInput.resume"):
            interrupts.validate_interrupt_outcome(True)

    @needs_interrupt_outcome
    def test_naming_a_member_is_not_part_of_that_floor(self, monkeypatch):
        """It reached the protocol a release later than the rest of the lifecycle.

        A server exposing a single agent never writes it, so refusing the whole
        round trip over it would demand an upgrade for a field the install would
        never be asked for.
        """
        monkeypatch.setattr(interrupts, "Interrupt", _interrupt_type_without(interrupts.MEMBER_ATTRIBUTION_FIELD))

        assert interrupts.validate_interrupt_outcome(True) is True
        assert interrupts.interrupt_attribution_available() is False

    @needs_interrupt_outcome
    def test_an_install_that_cannot_name_a_member_says_so_and_answers_anyway(self, monkeypatch, caplog):
        """The interrupt still goes out, under an id the resume channel accepts.

        Writing the field a release does not declare would put the value on the
        wire under a name the format does not define, so the attribution is
        dropped instead and the pause stays answerable.

        Read off what the interrupt serialized to, on a model that really omits
        the field. The check this replaces patched the availability probe and
        then read the attribute back, which is the one pair of choices that can
        prove nothing: the models keep a key they never declared, so the
        attribute is there whether the field was dropped or written out
        undeclared, and patching the probe leaves the model still declaring it.
        """
        monkeypatch.setattr(interrupts, "Interrupt", _interrupt_type_without(interrupts.MEMBER_ATTRIBUTION_FIELD))
        requirement = _requirement(_confirmation())

        with captured_agno_logs(caplog, "WARNING"):
            interrupt = interrupts.build_interrupt(
                _needs_answering(requirement),
                tool_call_id="tc-confirm",
                tool_name="send_email",
                subagent_run_id="member-run",
            )

        assert interrupt.id == interrupts.interrupt_id_of(requirement)
        serialized = interrupt.model_dump(by_alias=True)
        assert interrupts.MEMBER_ATTRIBUTION_FIELD not in serialized
        assert _camel(interrupts.MEMBER_ATTRIBUTION_FIELD) not in serialized
        assert "unattributed" in caplog.text

    @needs_interrupt_outcome
    def test_a_pause_with_no_member_to_name_writes_that_field_nowhere_either(self, monkeypatch):
        """Which is the whole of what a single agent's install ever asks for.

        Nothing is passed rather than a null: on a release declaring the field a
        null is omitted anyway, and on one that does not it is an undeclared key
        published to every client of every single-agent server.
        """
        monkeypatch.setattr(interrupts, "Interrupt", _interrupt_type_without(interrupts.MEMBER_ATTRIBUTION_FIELD))

        interrupt = interrupts.build_interrupt(
            _needs_answering(_requirement(_confirmation())),
            tool_call_id="tc-confirm",
            tool_name="send_email",
        )

        assert interrupts.MEMBER_ATTRIBUTION_FIELD not in interrupt.model_dump(by_alias=True)

    @needs_interrupt_outcome
    def test_the_tag_the_outcome_is_read_by_is_part_of_the_floor(self, monkeypatch):
        """The outcome reaches a client as a tagged union, and this is the tag.

        It is what tells a client this terminal carries interrupts rather than a
        plain completion, and the builder writes it on every outcome it makes. A
        release that renamed it takes the value as data it never declared, so the
        terminal a paused run ends on is one nothing tells the client to answer.
        """
        monkeypatch.setattr(
            interrupts,
            "RunFinishedInterruptOutcome",
            _type_without(interrupts.RunFinishedInterruptOutcome, "type"),
        )

        with pytest.raises(ValueError, match="RunFinishedInterruptOutcome.type"):
            interrupts.validate_interrupt_outcome(True)

    @needs_interrupt_outcome
    @pytest.mark.parametrize("field", sorted(_READ_OFF_ONE_ANSWER))
    def test_the_fields_one_answer_is_read_off_are_part_of_the_floor(self, monkeypatch, field):
        """An install that shapes an answer otherwise has to be refused, not discovered.

        Each of these is read as a plain attribute while the answer is applied,
        so a release declaring one of them differently is not a client whose
        answer is refused with a reason: it is an AttributeError partway through
        the continue of a run this interface told that client to answer, after
        the startup check reported nothing missing. The array they arrive in
        being declared says nothing about them.
        """
        entry_model = _the_entry_model()
        if entry_model is None:
            pytest.skip("the installed ag_ui.core declares no model for one answer to arrive as")
        monkeypatch.setattr("ag_ui.core.ResumeEntry", _type_without(entry_model, field))

        with pytest.raises(ValueError, match=f"ResumeEntry.{field}"):
            interrupts.validate_interrupt_outcome(True)

    @needs_interrupt_outcome
    def test_an_envelope_a_release_omits_is_not_part_of_that_floor(self, monkeypatch):
        """The failure report is read with a default, so an entry without one answers.

        A release declaring the entry without it is serviceable: every answer it
        carries is read, and the one thing it cannot say is that the client's own
        tool raised. Demanding it would refuse that install over a field most
        answers never carry.
        """
        entry_model = _the_entry_model()
        if entry_model is None or "metadata" not in entry_model.model_fields:
            pytest.skip("the installed ag_ui.core declares no envelope on an answer to omit")
        monkeypatch.setattr("ag_ui.core.ResumeEntry", _type_without(entry_model, "metadata"))

        assert interrupts.validate_interrupt_outcome(True) is True

    @needs_suspended_outcome
    def test_a_release_missing_one_part_of_the_suspended_outcome_builds_none_of_it(self, monkeypatch):
        """The type alone being importable is not the same as being serviceable.

        A release carrying the outcome type without one of the fields it is built
        from would otherwise be handed one whose content rides out undeclared,
        and the member terminal would carry it as a lane that says nothing. Every
        field of it, because each is written on every one of them.
        """
        for field in interrupts.subagent_suspension_fields()[interrupts.SubagentFinishedSuspendedOutcome]:
            with monkeypatch.context() as without:
                without.setattr(
                    interrupts,
                    "SubagentFinishedSuspendedOutcome",
                    _type_without(interrupts.SubagentFinishedSuspendedOutcome, field),
                )

                assert interrupts.subagent_suspension_available() is False, f"{field} is detected by nothing"
                assert interrupts.suspended_outcome(["an-interrupt"]) is None

    @needs_interrupt_outcome
    def test_an_install_without_the_suspended_outcome_says_so(self, monkeypatch, caplog):
        """The member is still attributed; only its lane stops saying it is waiting."""
        require_lineage_events()
        from agno.os.interfaces.agui import AGUI, agui

        monkeypatch.setattr(agui, "subagent_suspension_available", lambda: False)

        with captured_agno_logs(caplog, "WARNING"):
            AGUI(agent=Agent(name="A"), emit_interrupt_outcome=True, subagent_visibility=attributed())

        assert "cannot close a subagent the run paused inside as suspended" in caplog.text


class TestWhatIsWrittenIsWhatIsDetected:
    """The two halves of the rule this interface is built on, held to each other.

    A field is feature-detected so that an install which cannot carry it is
    refused before a run starts. That only works while the census and the code
    say the same thing, and twice now they have not: an outcome tag written by
    both builders that no table listed, and the fields of an incoming answer
    read as plain attributes while only the array around them was checked.
    Neither was catchable by anything here, because both tables were lists kept
    in step by care.

    So each check below derives one side from the other. What the builders write
    is read off the objects they return; what an answer is read off is read from
    the source of the half that reads it; which types are new enough to need a
    table at all is read from the imports that guard them. A field added to any
    of the three without a row fails here rather than on the install that omits
    it.
    """

    @needs_interrupt_outcome
    @needs_suspended_outcome
    def test_no_field_is_written_that_the_census_does_not_declare(self):
        """Read off what the builders return, over every pause kind they build for."""
        census = _census()
        built = _everything_a_pause_makes_this_interface_build()

        assert built, "no object was built at all, so this check holds nothing to anything"
        undetected = {
            type(one).__name__: sorted(set(one.model_fields_set) - set(census.get(type(one), ())))
            for one in built
            if set(one.model_fields_set) - set(census.get(type(one), ()))
        }

        assert undetected == {}, f"these are written where nothing detects them: {undetected}"

    @needs_interrupt_outcome
    def test_every_protocol_type_this_interface_guards_its_import_of_is_censused(self):
        """A type new enough to import defensively is one every field of is new.

        Resolved against the installed protocol first: a type this release does
        not carry is one nothing detects because there is nothing to detect.
        """
        import ag_ui.core

        censused = {model.__name__ for model in _census()}
        guarded = {
            name for name in _protocol_types_imported_under_a_guard() if getattr(ag_ui.core, name, None) is not None
        }

        assert guarded, "this scan found no guarded import at all, so it holds nothing to anything"
        assert guarded <= censused, (
            f"the installed release carries these, and no table says so: {sorted(guarded - censused)}"
        )

    @needs_interrupt_outcome
    def test_the_census_names_every_field_one_answer_is_read_off_and_no_others(self):
        """Both directions, because each is a way this interface has already failed.

        A field read off an answer that no table names is the install that passes
        the startup check and raises mid-continue. A field named that nothing
        reads is a release refused over something this interface never touches.
        """
        entry_model = _the_entry_model()
        if entry_model is None:
            pytest.skip("the installed ag_ui.core declares no model for one answer to arrive as")
        censused = {model.__name__: set(fields) for model, fields in _census().items()}

        assert _READ_OFF_ONE_ANSWER, "this scan found nothing read off an answer, so it holds nothing to anything"
        assert censused.get(entry_model.__name__) == _READ_OFF_ONE_ANSWER, (
            f"read off an answer and detected by nothing: "
            f"{sorted(_READ_OFF_ONE_ANSWER - censused.get(entry_model.__name__, set()))}; "
            f"detected and read nowhere: {sorted(censused.get(entry_model.__name__, set()) - _READ_OFF_ONE_ANSWER)}"
        )

    def test_this_scan_reports_a_field_read_off_an_answer_that_nothing_detects(self):
        """The check above is one whose whole job is to fire, so it is made to.

        Its subject is what the scan reads, so the scan is handed a read of a
        field no table names and has to report it. A scan that cannot report one
        would pass the check above on any source at all.
        """
        read = _plain_attributes_read_on("if entry.expires_at:\n    pass\n", _ONE_ANSWER)

        assert read == {"expires_at"}
        assert _plain_attributes_read_on("value = getattr(entry, 'status', None)\n", _ONE_ANSWER) == set()


# --- The gates, held to the piece each test's own body needs -----------------

# Six times in this suite a gate has named a piece other than the one the test
# under it depends on: the test failed where it should have skipped, skipped
# where it had nothing to skip for, or skipped on the very install it exists to
# prove. Each was found by reading a test and fixed on its own. What follows
# reads the tests instead, off this file's own source, so the next one is a
# failure here rather than the seventh instance of the same mistake.

_OUTCOME = "the interrupt-aware run lifecycle"
_ATTRIBUTION = "naming the member an interrupt was raised inside"
_SUSPENSION = "the suspended subagent outcome"
_RESUME = "the resume array a client's answers arrive in"

# Every gate this suite has: the piece it stands for, and the probe the
# interface itself decides that piece by. A gate written against something other
# than that probe is the original mistake, so each marker's own source is held
# to it below.
_GATES: Dict[str, Tuple[str, str]] = {
    "needs_interrupt_outcome": (_OUTCOME, "INTERRUPT_OUTCOME_AVAILABLE"),
    "needs_member_attribution": (_ATTRIBUTION, "interrupt_attribution_available"),
    "needs_suspended_outcome": (_SUSPENSION, "subagent_suspension_available"),
    "needs_resume_array": (_RESUME, "RESUME_ARRAY_IS_READABLE"),
}


def _camel(field: str) -> str:
    """One protocol field as the wire spells it, which is how a test reads it."""
    head, *rest = field.split("_")
    return head + "".join(piece.capitalize() for piece in rest)


# The suspended outcome's own spellings, held to what the interface actually
# builds by the first test below rather than trusted: a rename there would
# otherwise leave this check quietly matching nothing.
_SUSPENDED_TYPE = "suspended"
_SUSPENDED_INTERRUPT_IDS = "interruptIds"

# An argument that asks a piece for something. Counted only where it is passed
# something other than a falsy literal, so reading the emission setting to
# assert that it defaults to off asks for nothing.
_ASKED_FOR_BY_ARGUMENT: Dict[str, Tuple[str, ...]] = {
    _OUTCOME: ("emit_interrupt_outcome",),
    _RESUME: ("resume",),
}

# A name or a wire key that means nothing on an install without the piece. The
# attribution spellings are derived from the interface's own field name so the
# two cannot drift apart.
_WRITTEN_IN_THE_SOURCE: Dict[str, Tuple[str, ...]] = {
    _OUTCOME: (
        "INTERRUPT_OUTCOME_AVAILABLE",
        "validate_interrupt_outcome",
        "build_interrupt",
        "interrupt_outcome",
        "interrupt_round_trip_fields",
    ),
    _ATTRIBUTION: (
        "interrupt_attribution_available",
        "MEMBER_ATTRIBUTION_FIELD",
        interrupts.MEMBER_ATTRIBUTION_FIELD,
        _camel(interrupts.MEMBER_ATTRIBUTION_FIELD),
    ),
    _SUSPENSION: (
        "subagent_suspension_available",
        "suspended_outcome",
        _SUSPENDED_TYPE,
        _SUSPENDED_INTERRUPT_IDS,
    ),
}

# The class whose subject is this file's own source. Every spelling above
# appears in it, and it depends on no release piece at all, so the walk leaves
# it out and the first test below refuses to run if it has been renamed away.
_READS_THIS_FILE = "TestTheGatesNameThePieceTheBodyNeeds"


def _suite_source() -> ast.Module:
    return ast.parse(Path(__file__).read_text(encoding="utf-8"))


def _is_a_gate(decorator: ast.AST) -> bool:
    return any(isinstance(node, ast.Name) and node.id in _GATES for node in ast.walk(decorator))


def _gates_on(node: ast.AST) -> Set[str]:
    """The pieces one class or function is gated on, whichever gates are stacked."""
    return {
        _GATES[inner.id][0]
        for decorator in getattr(node, "decorator_list", [])
        for inner in ast.walk(decorator)
        if isinstance(inner, ast.Name) and inner.id in _GATES
    }


def _named_by(nodes: Sequence[ast.AST]) -> Set[str]:
    """Identifiers and string literals these nodes carry, absence claims aside.

    A literal used to assert that the wire does not carry it is dropped where it
    is written: a test checking that a field is absent is the opposite of one
    that needs it. Dropped there and nowhere else, because these nodes are a
    whole test together with every helper it reads, and subtracting the spelling
    from the finished set erased it at every other site too: one negative
    assertion then took a gate requirement off a sibling site that genuinely has
    it.
    """
    found: Set[str] = set()
    for node in nodes:
        claimed_absent = {
            inner.left
            for inner in ast.walk(node)
            if isinstance(inner, ast.Compare)
            and isinstance(inner.left, ast.Constant)
            and isinstance(inner.left.value, str)
            and any(isinstance(op, ast.NotIn) for op in inner.ops)
        }
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name):
                found.add(inner.id)
            elif isinstance(inner, ast.Attribute):
                found.add(inner.attr)
            elif isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                if inner not in claimed_absent:
                    found.add(inner.value)
    return found


def _asked_for_by(nodes: Sequence[ast.AST]) -> Set[str]:
    """Keyword argument names these nodes pass something other than a falsy literal."""
    found: Set[str] = set()
    for node in nodes:
        for inner in ast.walk(node):
            if isinstance(inner, ast.keyword) and inner.arg:
                if isinstance(inner.value, ast.Constant) and not inner.value.value:
                    continue
                found.add(inner.arg)
    return found


def _simulated_away_by(nodes: Sequence[ast.AST]) -> Set[str]:
    """The pieces these nodes replace the detection of, which is not a dependency.

    A test whose subject is the refusal patches the probe or the type a piece is
    detected through, and it is the only kind of test with anything left to
    assert on an install that really lacks that piece, so it has to run there.
    """
    away: Set[str] = set()
    for node in nodes:
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            called = inner.func.attr if isinstance(inner.func, ast.Attribute) else None
            if called != "setattr":
                continue
            named = _named_by([inner])
            away |= {piece for piece, spellings in _WRITTEN_IN_THE_SOURCE.items() if set(spellings) & named}
    return away


def _helpers_of_this_suite(tree: ast.Module) -> Dict[str, ast.AST]:
    """Every module-level name of this suite a test body can carry a dependency in.

    An annotated assignment as readily as a bare one: this file writes tables
    both ways, and reading only the bare ones left a dependency carried in an
    annotated table invisible for no reason a reader of either could see.
    """
    helpers: Dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            helpers[node.name] = node
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                helpers[node.target.id] = node.value
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    helpers[target.id] = node.value
    return helpers


def _methods_of(tree: ast.Module) -> Dict[str, Dict[str, ast.AST]]:
    """Every class of this file and what it defines, wherever the class is written."""
    return {
        node.name: {
            child.name: child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }


def _everything_read_by(node: ast.AST, owner: Optional[str], tree: ast.Module) -> List[ast.AST]:
    """The test's own nodes and every helper of this suite it names, transitively.

    Names rather than call sites: a helper handed to ``parametrize`` as a value
    is read by the test just as surely as one it calls, and a call written as an
    attribute is a call the plain-name scan this replaces used to skip.
    """
    helpers = _helpers_of_this_suite(tree)
    methods = _methods_of(tree)
    reading = [
        *getattr(node, "body", []),
        *(decorator for decorator in getattr(node, "decorator_list", []) if not _is_a_gate(decorator)),
    ]
    collected = list(reading)
    seen: Set[str] = set()
    frontier = [(reading, owner)]
    while frontier:
        nodes, in_class = frontier.pop()
        siblings = methods.get(in_class or "", {})
        for name in _named_by(nodes):
            if name in seen:
                continue
            body = siblings.get(name) or helpers.get(name)
            if body is None:
                continue
            seen.add(name)
            collected.append(body)
            frontier.append(([body], in_class if name in siblings else None))
    return collected


def _pieces_needed_by(node: ast.AST, owner: Optional[str], tree: ast.Module) -> Set[str]:
    read = _everything_read_by(node, owner, tree)
    named = _named_by(read)
    asked = _asked_for_by(read)
    needed = {piece for piece, spellings in _WRITTEN_IN_THE_SOURCE.items() if set(spellings) & named}
    needed |= {piece for piece, arguments in _ASKED_FOR_BY_ARGUMENT.items() if set(arguments) & asked}
    return needed - _simulated_away_by(read)


def _every_test_in_this_suite() -> List[Tuple[str, Set[str], Set[str]]]:
    """(name, the pieces its body needs, the pieces it is gated on) per test."""
    tree = _suite_source()
    rows: List[Tuple[str, Set[str], Set[str]]] = []

    def walk(body: Sequence[ast.AST], owner: Optional[str], inherited: Set[str]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                if node.name != _READS_THIS_FILE:
                    walk(node.body, node.name, inherited | _gates_on(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                name = f"{owner}::{node.name}" if owner else node.name
                rows.append((name, _pieces_needed_by(node, owner, tree), inherited | _gates_on(node)))

    walk(tree.body, None, set())
    return rows


def _every_test_this_file_defines() -> Set[str]:
    """Every test defined here, found without the walk's own recursion.

    ``ast.walk`` descends everything, so this cannot miss a test for any of the
    reasons the walk above can: a class it declines to enter, a nesting it does
    not expect, a name it filters on. It is what the walk is compared against,
    in place of a floor that held while most of the suite went unwalked.
    """
    return {
        node.name
        for node in ast.walk(_suite_source())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
    }


def _tests_of_the_class_that_reads_this_file() -> Set[str]:
    """The tests the walk leaves out, which are the ones in this file's own subject."""
    return {
        child.name
        for node in _suite_source().body
        if isinstance(node, ast.ClassDef) and node.name == _READS_THIS_FILE
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test")
    }


# --- Every source of a stream, derived rather than listed --------------------

# A stream reaches this suite from a callable that builds protocol events, and
# every one of those is imported under a private name and wrapped under the name
# the suite calls it by, so that no call site can skip the shared checks. Which
# callables those are used to be a list of three wrapper names, and a fourth
# source was imported and driven under its own name with nothing able to report
# it. So the set is derived from this file's imports and the signatures of what
# they bind.
#
# What the derivation cannot see, stated because every scan in this directory
# has a blind spot: a source whose signature does not say it builds events, one
# this file writes itself rather than imports, one reached through a module
# object instead of an imported name, and events a test constructs by hand. The
# route harness is the first of those, and it calls both checks in its own body.


def _builds_protocol_events(candidate: Any) -> bool:
    """Whether calling this yields or returns AG-UI events, read off its signature.

    A reader of a stream is not a source of one: it is handed the events it
    filters, so a parameter of that type is what tells the two apart.
    """
    if not inspect.isfunction(candidate):
        return False
    try:
        annotations = get_type_hints(candidate)
    except Exception:
        # A signature this check cannot resolve says nothing either way, and the
        # completeness test below is what refuses to let that go unnoticed.
        return False
    if not _mentions_a_protocol_event(annotations.pop("return", None)):
        return False
    return not any(_mentions_a_protocol_event(annotation) for annotation in annotations.values())


def _mentions_a_protocol_event(annotation: Any) -> bool:
    if isinstance(annotation, type) and issubclass(annotation, BaseEvent):
        return True
    return any(_mentions_a_protocol_event(argument) for argument in get_args(annotation))


def _imports_of(tree: ast.Module) -> List[Tuple[str, str]]:
    """(the name imported, the name it is bound to here) for every from-import."""
    return [
        (alias.name, alias.asname or alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]


def _imported_stream_sources() -> Dict[str, Tuple[str, ...]]:
    """{the name a source is wrapped under: the names this file binds it to}.

    Resolved through the module each import names rather than through this
    file's own globals, so a wrapper shadowing the name it wraps cannot hide the
    import behind it.
    """
    found: Dict[str, List[str]] = {}
    for node in ast.walk(_suite_source()):
        if not isinstance(node, ast.ImportFrom):
            continue
        try:
            source_module = importlib.import_module("." * node.level + (node.module or ""), __package__)
        except ImportError:  # pragma: no cover - every import here is one this file already ran
            continue
        for alias in node.names:
            if _builds_protocol_events(getattr(source_module, alias.name, None)):
                found.setdefault(alias.name, []).append(alias.asname or alias.name)
    return {name: tuple(bound) for name, bound in found.items()}


_STREAM_SOURCES = _imported_stream_sources()

_THE_ENCODED_KEYS = ("_assert_nothing_undeclared_reached_the_client",)
_A_WELL_FORMED_STREAM = ("assert_well_formed_stream", "assert_stream_is_malformed_as_recorded")

# What each wrapper owes the stream it hands back, as groups of calls it must
# name at least one of. Every wrapper owes the encoded keys, which is the check
# no caller can run for itself: the paths its encoder is allowed to refuse
# arrive as this wrapper's own argument. The two that hand back the stream alone
# also owe well-formedness; the drivers hand back the error that ended the
# stream beside it, so what a stream cut short should look like is the caller's
# statement to make.
_THE_CHECKS_EACH_WRAPPER_OWES: Dict[str, Tuple[Tuple[str, ...], ...]] = {
    "on_run_completed": (_THE_ENCODED_KEYS, _A_WELL_FORMED_STREAM),
    "run_entity": (_THE_ENCODED_KEYS, _A_WELL_FORMED_STREAM),
    "collect_async": (_THE_ENCODED_KEYS,),
    "collect_sync": (_THE_ENCODED_KEYS,),
}


def _calls_inside(tree: ast.Module, function: str) -> Set[str]:
    """Every name this file's ``function`` calls, the callee's last name only."""
    defined = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
    ]
    assert len(defined) == 1, f"{function} is defined {len(defined)} times at this module's top level"
    called: Set[str] = set()
    for node in ast.walk(defined[0]):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    return called


def _scopes_of_this_file_that_read(tree: ast.Module, name: str) -> Set[str]:
    """Every scope of this file that names ``name``, module level included.

    Scopes rather than function definitions: a module-level parametrize handing
    a driver out as a value drives a stream exactly as a call does, and a scan
    filtered to function definitions could not see one. A decorator counts as
    part of the definition it is written on, which is where such a list is read.

    A scope is named by its whole path, so a method of some class sharing a
    wrapper's name is not mistaken for the wrapper and subtracted.
    """
    found: Set[str] = set()

    def walk(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk(child, child.name if owner == "<module>" else f"{owner}.{child.name}")
                continue
            if isinstance(child, ast.Name) and child.id == name:
                found.add(owner)
            elif isinstance(child, ast.Attribute) and child.attr == name:
                found.add(owner)
            walk(child, owner)

    walk(tree, "<module>")
    return found


class TestTheGatesNameThePieceTheBodyNeeds:
    """This suite's own gates, read off its source.

    The three pieces of the round trip reached the protocol in three separate
    releases, the array the answers arrive in is a fourth, and this suite runs
    on installs that have any subset of them. Which piece a test needs is read
    from what its body asks for and what it reads off the wire, not from a table
    of test names, because such a table is the next thing to drift.
    """

    def test_this_walk_reads_the_suite_it_is_written_about(self):
        """A walk that sees no tests would pass every check below in silence.

        Every test this file defines and none it does not, rather than a floor:
        the floor stood at eighty against a suite of over a hundred and fifty, so
        the walk could have lost half of them and still cleared it.
        """
        walked = {name.rpartition("::")[2] for name, _needed, _gated in _every_test_in_this_suite()}
        defined = _every_test_this_file_defines()
        left_out = _tests_of_the_class_that_reads_this_file()

        assert left_out, f"{_READS_THIS_FILE} defines no test, so the walk leaves nothing out"
        assert walked == defined - left_out, (
            f"this walk reads {len(walked)} of the {len(defined - left_out)} tests it is written about: "
            f"missed {sorted(defined - left_out - walked)}, invented {sorted(walked - defined)}"
        )
        assert {name for name in _GATES} == {
            target.id
            for node in ast.walk(_suite_source())
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id.startswith("needs_")
        }, "a gate this suite defines is not one this check knows the probe for"
        assert any(node.name == _READS_THIS_FILE for node in _suite_source().body if isinstance(node, ast.ClassDef)), (
            f"{_READS_THIS_FILE} is the class the walk leaves out, and it is no longer there"
        )

    def test_the_spellings_this_check_reads_are_the_ones_the_interface_writes(self):
        """Derived where the interface exposes the name, and compared where it does not."""
        assert _camel(interrupts.MEMBER_ATTRIBUTION_FIELD) == "subagentRunId"

        suspended = interrupts.suspended_outcome(["an-interrupt"])
        if suspended is None:
            pytest.skip("the installed ag_ui.core builds no suspended subagent outcome to read")
        assert suspended.type == _SUSPENDED_TYPE
        fields = interrupts.subagent_suspension_fields()[type(suspended)]
        assert _SUSPENDED_INTERRUPT_IDS in {_camel(field) for field in fields}

    def test_every_gate_names_the_probe_the_interface_decides_that_piece_by(self):
        """A gate reading anything else is how a test skips on the wrong install."""
        tree = _suite_source()
        written_as = {
            target.id: ast.unparse(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id in _GATES
        }

        assert sorted(written_as) == sorted(_GATES), f"a gate is not defined at this module's top level: {written_as}"
        for gate, (_piece, probe) in _GATES.items():
            source = written_as[gate]
            assert "skipif" in source, f"{gate} is not a skip gate: {source}"
            assert probe in source, f"{gate} decides by {source}, not by the interface's own {probe}"

    def test_no_test_is_gated_on_a_piece_its_body_does_not_need(self):
        """A gate for a piece a test never touches skips it where it still holds.

        Which is how a class-level gate goes wrong: it is true of most of the
        class and false of the test that only answers a requirement.
        """
        over_gated = {
            name: sorted(gated - needed) for name, needed, gated in _every_test_in_this_suite() if gated - needed
        }

        assert over_gated == {}, f"these tests skip on installs where they would still hold: {over_gated}"

    def test_no_test_that_needs_a_piece_runs_ungated(self):
        """The other direction: a test that fails where it should have skipped."""
        ungated = {
            name: sorted(needed - gated) for name, needed, gated in _every_test_in_this_suite() if needed - gated
        }

        assert ungated == {}, f"these tests need a release piece nothing gates them on: {ungated}"

    def test_every_source_of_a_stream_this_suite_imports_has_a_wrapper(self):
        """The derivation and the wrappers say the same thing, both ways.

        A source it found that nothing wraps is one a test can drive past every
        check, which is how the fourth of them went unheld to the keys it
        encoded. A wrapper for something it no longer finds is the other
        failure, and the one a list of names cannot report at all: the
        derivation has gone blind and every check below it is reading nothing.
        """
        tree = _suite_source()
        defined_here = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        wrapped_here = {name for name, bound in _imports_of(tree) if bound.startswith("_") and name in defined_here}

        assert _STREAM_SOURCES, "this check found no source of a stream at all, so it holds nothing to anything"
        assert set(_STREAM_SOURCES) == wrapped_here, (
            f"sources with no wrapper: {sorted(set(_STREAM_SOURCES) - wrapped_here)}; "
            f"wrappers for something this check no longer reads as a source: "
            f"{sorted(wrapped_here - set(_STREAM_SOURCES))}"
        )

    @pytest.mark.parametrize("wrapped", sorted(_STREAM_SOURCES))
    def test_every_stream_this_suite_drives_reaches_the_shared_checker(self, wrapped):
        """Each wrapper is the only place in this file that reads what it wraps.

        A test reaching past a wrapper gets a stream nothing holds to the shared
        definition of a well-formed one, nor to the keys it encoded, which is
        what let this suite assert a stream was correct while the checker next
        door rejected it. Read over every scope of the file, module level
        included: a parametrize list built there hands the unwrapped one out to
        every test under it, and the scan this replaces looked at function
        definitions only.
        """
        bound = _STREAM_SOURCES[wrapped]
        assert len(bound) == 1 and bound[0].startswith("_"), (
            f"{wrapped} is not imported under exactly one private name for its wrapper to read: {list(bound)}"
        )

        reached_past_it = sorted(_scopes_of_this_file_that_read(_suite_source(), bound[0]) - {wrapped})

        assert reached_past_it == [], f"these drive a stream the checks never see: {reached_past_it}"

    @pytest.mark.parametrize("wrapped", sorted(_STREAM_SOURCES))
    def test_every_wrapper_still_runs_the_checks_it_stands_there_to_run(self, wrapped):
        """Funnelling every stream through a wrapper proves nothing if the wrapper checks nothing.

        The test above holds every caller to the wrapper; this one holds the
        wrapper to its body. Gut all of them and the suite above still passes:
        the sole place each check is made would be gone with no test left
        reading a stream it used to reject.
        """
        owed = _THE_CHECKS_EACH_WRAPPER_OWES.get(wrapped)

        assert owed is not None, f"{wrapped} wraps a stream this file drives and states no check it owes it"

        called = _calls_inside(_suite_source(), wrapped)
        unmade = [sorted(group) for group in owed if not set(group) & called]

        assert unmade == [], f"{wrapped} hands back a stream without making these checks: {unmade}"
