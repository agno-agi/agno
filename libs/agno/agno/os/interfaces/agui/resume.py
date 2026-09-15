from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent import Agent
from agno.os.interfaces.agui import interrupts
from agno.os.interfaces.agui.interrupts import (
    CONFIRMATION_ACCEPTED_ALIAS,
    CONFIRMATION_ACCEPTED_KEY,
    CONFIRMATION_NOTE_KEY,
    USER_FEEDBACK_SELECTIONS_KEY,
    USER_INPUT_VALUES_KEY,
    NeededAnswer,
    advertised_answer_schema,
    answers_a_pause_needs,
    external_execution_result,
    interrupt_id_of,
    pause_not_continuable,
)
from agno.run.base import RunContext, RunStatus
from agno.run.requirement import PauseType, RunRequirement
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team.team import Team
from agno.utils.log import log_warning
from agno.utils.string import parse_response_dict_str

# What each pause kind is waiting for, in the words a client that sent something
# else is refused in. One sentence per kind, shared by the envelope guards and
# by the schema check below, so a payload refused for either reason is refused
# in the same terms a client already matches on.
_WHAT_A_PAUSE_EXPECTS: Dict[PauseType, str] = {
    "confirmation": "confirmation expects {'accepted': true|false} (or the spec's 'approved')",
    "user_input": "user_input expects {'values': {...}}",
    "user_feedback": "user_feedback expects {'selections': {question: [labels]}}",
}


def _is_an_integer(value: Any) -> bool:
    """Whether this value is the integer an advertised field asked for.

    An integral float is one. JSON has a single number type, so 42.0 is how a
    client that has no integer of its own sends 42, and the keyword describes the
    value rather than the spelling it arrived in. A bool is not, even though
    Python counts it as an int.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()


# One JSON Schema type, as the check that a value carries it. Written out rather
# than read back off the type map the schemas are built from, because what
# matters here is the other direction: an integer satisfies "number", and a bool
# satisfies neither of the numeric types even though Python counts it as one.
_OF_JSON_TYPE: Dict[str, Callable[[Any], bool]] = {
    "null": lambda value: value is None,
    "boolean": lambda value: isinstance(value, bool),
    "integer": _is_an_integer,
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "string": lambda value: isinstance(value, str),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}

# The keywords an advertised schema carries that state no constraint: they are
# there for a renderer to show.
SCHEMA_ANNOTATIONS: Tuple[str, ...] = ("description", "title")

# The one constraint the schemas state that this check leaves to somebody else.
# Whether an answer fills the pause is Agno's own question: ``is_resolved``
# answers it across every field and question at once, and the resolved-set guard
# is what refuses a resume that left one open, with the reason the terminal gave.
# The top-level key of every schema advertised here is the envelope its resolver
# refuses to run without, so an answer that omits one is refused there and not by
# a second reading of the same keyword.
SCHEMA_COMPLETENESS: Tuple[str, ...] = ("required",)

# The constraints the advertised schemas state and this side describes without
# holding a client to: the labels a question offers, how many of them it takes,
# and the null an untyped field must not carry. Each of those says which values
# of the right kind an answer may carry, which is the client's half of the round
# trip: an agent MAY validate the payload it is sent and a client SHOULD
# validate before submitting, so the schema is what the client holds itself to
# while this side checks only what a value has to be to reach a tool at all.
# Enforcing the rest is also what refused answers this interface used to take,
# so the check stays at the narrowest shape that still keeps a payload of the
# wrong kind out of a tool.
SCHEMA_ADVERTISED_ONLY: Tuple[str, ...] = ("enum", "minItems", "maxItems", "not")


def _type_unmet(constraint: Any, value: Any, at: str) -> Optional[str]:
    carries_it = _OF_JSON_TYPE.get(constraint)
    if carries_it is None:
        log_warning(f"AG-UI cannot check the advertised type {constraint!r}, so {at} is taken unchecked")
        return None
    return None if carries_it(value) else f"{at} has to be {constraint}"


def _properties_unmet(constraint: Any, value: Any, at: str) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    for name, described in constraint.items():
        if name in value:
            unmet = _unmet_constraint(described, value[name], f"{at}[{name!r}]")
            if unmet:
                return unmet
    return None


def _items_unmet(constraint: Any, value: Any, at: str) -> Optional[str]:
    """Every entry of an array, held to the schema that array described entries by.

    Read for the same reason ``properties`` is: a declared type is reached
    wherever the schema states one, and a selections answer states its one level
    deeper than a field's value does. A question's labels are the text of its
    options, stored as text and handed to the model as the options somebody
    chose, so an entry of another kind is a value of the wrong kind reaching a
    tool rather than a client picking badly.

    Which labels a question offers is the other claim, and stays advertised-only:
    this recurses through the same table, so the ``enum`` beside the type is
    passed over here exactly as it is at the top level.
    """
    if not isinstance(value, list):
        return None
    for index, entry in enumerate(value):
        unmet = _unmet_constraint(constraint, entry, f"{at}[{index}]")
        if unmet:
            return unmet
    return None


# Every constraint this side holds an answer to, as the one check that reads it.
# A table rather than a chain of branches, so what is enforced is a list the
# suite can hold the emitted schemas to.
_CONSTRAINT_CHECKS: Dict[str, Callable[[Any, Any, str], Optional[str]]] = {
    "type": _type_unmet,
    "properties": _properties_unmet,
    "items": _items_unmet,
}

# Every keyword this side of the round trip knows what to do with: enforced,
# annotation, or deliberately somebody else's. A schema keyword outside it and
# outside the advertised-only list is one the interface advertises and nothing
# accounts for.
ADVERTISED_KEYWORDS_READ: Tuple[str, ...] = tuple(_CONSTRAINT_CHECKS) + SCHEMA_ANNOTATIONS + SCHEMA_COMPLETENESS

# Where an answer is being read, in the words a refusal names it by.
_THE_ANSWER = "the answer"


def _unmet_constraint(described: Dict[str, Any], value: Any, at: str = _THE_ANSWER) -> Optional[str]:
    """The first constraint of one advertised schema this value does not meet.

    A keyword this does not know is reported and passed over rather than
    refused: a client that sent what it was told to send must not be turned away
    over a constraint nothing here can read, which is the same reason the schemas
    leave an unrecognised field type unconstrained. The suite holds every schema
    the interface advertises to the keywords above, so that case stays
    hypothetical rather than becoming a constraint accounted for nowhere.
    """
    for keyword, constraint in described.items():
        if keyword in SCHEMA_ANNOTATIONS or keyword in SCHEMA_COMPLETENESS or keyword in SCHEMA_ADVERTISED_ONLY:
            continue
        check = _CONSTRAINT_CHECKS.get(keyword)
        if check is None:
            log_warning(f"AG-UI cannot check the advertised constraint {keyword!r} on {at}, so it is not enforced")
            continue
        unmet = check(constraint, value, at)
        if unmet:
            return unmet
    return None


def _without_the_keys_it_left_empty(described: Dict[str, Any], payload: Any) -> Any:
    """One answer with the described keys a client sent nothing under removed.

    JSON has one way to say that there is no value, and a client that sends it
    under a key the pause does not require has sent no value for that key rather
    than a wrong one. Reading it as the key being there is what refuses a resume
    that could have been answered, and for a field the model already filled it is
    worse than a refusal: the null is written on, the field counts as unfilled
    again, and the run the client was told to resume dies on the guard.

    A required key keeps its null, because there a null really is an answer that
    answers nothing: under a key the schema gave a type it is refused as a value
    of the wrong kind, and under one it left untyped it reaches Agno, which
    counts the field unfilled and refuses the resume through the guard.
    """
    properties = described.get("properties")
    if not isinstance(payload, dict) or not isinstance(properties, dict):
        return payload
    required = described.get("required") or []
    kept: Dict[str, Any] = {}
    for key, value in payload.items():
        describes_it = properties.get(key)
        if not isinstance(describes_it, dict):
            kept[key] = value
        elif value is None and key not in required:
            continue
        else:
            kept[key] = _without_the_keys_it_left_empty(describes_it, value)
    return kept


def _the_answer_the_pause_advertised(requirement: RunRequirement, payload: Any) -> Any:
    """One incoming answer, held to the shape the interrupt for it advertised.

    The interface tells a client the exact shape of the answer it wants, so a
    value of another kind is not accepted under a described key: the schema is
    rebuilt here by the same builder the terminal advertised from, which is what
    keeps the advertised shape and the accepted one from being two descriptions
    that drift apart. Rebuilt from the requirement rather than read off the
    emitted interrupt, because the interrupt carries the schema only on a release
    that has the interrupt types, and an answer has to be held to its shape on
    every release.

    Only the protocol's resume array runs this. The trailing-tool-message channel
    took answers before this interface described any shape at all, and holding
    those to a schema refuses resumes Agno accepted, so that channel keeps
    reading a payload the way it always has.

    A pause that advertises no schema has nothing stated to hold an answer to: a
    client-run tool hands back whatever its tool returned.
    """
    schema = advertised_answer_schema(requirement)
    if schema is None:
        return payload
    answer = _without_the_keys_it_left_empty(schema, payload)
    unmet = _unmet_constraint(schema, answer)
    if unmet is None:
        return answer
    expected = _WHAT_A_PAUSE_EXPECTS.get(requirement.pause_type)
    raise ValueError(f"{expected}: {unmet}" if expected else unmet)


def _payload_fields(payload: Any) -> Dict[str, Any]:
    """A resume payload as the field map the requirement resolvers read.

    Anything that is not a map of fields comes through as none of them, which
    each resolver then reports in its own terms rather than raising an attribute
    error from inside one.
    """
    return payload if isinstance(payload, dict) else {}


def _confirmation_fields(payload: Any) -> Dict[str, Any]:
    """A decision payload as the protocol's resume array reads it.

    Agno's key is the one this interface advertises, and the interrupt spec's
    approval example names the field differently, so a payload written against
    either one resolves the call. The alias is read only where Agno's own key
    carries no value at all: a client that sends both, carrying a null under the
    one it had no value for, sent exactly one decision, and reading the empty key
    instead would refuse a resume it could have answered. A value under Agno's
    own key is the decision, readable or not, so a malformed one is refused for
    what it is rather than answered off whatever sits beside it.

    Only the resume array runs this, because the interrupt that array answers is
    what advertised the alias. The trailing-tool-message channel declines a
    decision it cannot read, so reading one more key there is not a refusal
    turning into an answer but a declined tool call turning into one that runs,
    for every caller that channel already had.
    """
    fields = _payload_fields(payload)
    if fields.get(CONFIRMATION_ACCEPTED_KEY) is not None:
        return fields
    alias = fields.get(CONFIRMATION_ACCEPTED_ALIAS)
    if not isinstance(alias, bool):
        return fields
    return {**fields, CONFIRMATION_ACCEPTED_KEY: alias}


def _confirmation_decision(fields: Dict[str, Any]) -> Optional[bool]:
    """The decision this payload about one proposed tool call carries, if it carries one."""
    decision = fields.get(CONFIRMATION_ACCEPTED_KEY)
    return decision if isinstance(decision, bool) else None


def _resolve_confirmation(
    requirement: RunRequirement,
    fields: Dict[str, Any],
    error: Optional[str],
    *,
    unreadable_declines: bool,
) -> None:
    """Write the decision about one proposed tool call onto the requirement.

    A client reporting a failure is itself a denial: it says the question could
    not be answered, and the note records why. Either way the note reaches the
    model as the reason a call was refused.

    An approval keeps none: Agno's own approval entry point takes no note, and
    the interrupt for a decision says so where it advertises the field. One
    arriving anyway is dropped out loud rather than in silence, because the run
    records nothing a reader could learn it from afterwards.

    ``unreadable_declines`` is the one thing the two channels differ on. On the
    protocol's resume array a payload carrying no decision this interface can
    read fails the run, because recording it as a denial would put a refusal
    nobody gave into the run, on the wire and in its audit record, where nothing
    tells it apart from a real one. A trailing tool message declines the call
    instead, which is what that channel did before any of this and what its
    callers were written against.
    """
    note = fields.get(CONFIRMATION_NOTE_KEY)
    decision = _confirmation_decision(fields)
    if error:
        requirement.reject(note=note or error)
    elif decision is True:
        if note is not None:
            tool_execution = requirement.tool_execution
            approved = repr(tool_execution.tool_name) if tool_execution and tool_execution.tool_name else "a call"
            log_warning(
                f"AG-UI approved {approved} and dropped the note the approval carried, which nothing "
                f"downstream can read: {note!r}. Agno records a note on a denial only."
            )
        requirement.confirm()
    elif decision is False or unreadable_declines:
        requirement.reject(note=note)
    else:
        raise ValueError(_WHAT_A_PAUSE_EXPECTS["confirmation"])


def _resolve_user_input(requirement: RunRequirement, fields: Dict[str, Any]) -> None:
    values = fields.get(USER_INPUT_VALUES_KEY)
    if not isinstance(values, dict):
        raise ValueError(_WHAT_A_PAUSE_EXPECTS["user_input"])
    requirement.provide_user_input(values)


def _resolve_user_feedback(requirement: RunRequirement, fields: Dict[str, Any]) -> None:
    selections = fields.get(USER_FEEDBACK_SELECTIONS_KEY)
    if not isinstance(selections, dict) or not all(isinstance(v, list) for v in selections.values()):
        raise ValueError(_WHAT_A_PAUSE_EXPECTS["user_feedback"])
    requirement.provide_user_feedback(selections)


def _resolve_external_execution(requirement: RunRequirement, content: str, error: Optional[str]) -> None:
    if error and requirement.tool_execution:
        requirement.tool_execution.tool_call_error = True
    requirement.set_external_execution_result(error or content)


def resolve_requirements_from_tool_messages(
    requirements: List[RunRequirement],
    tool_messages: List[AGUIToolMessage],
) -> List[RunRequirement]:
    tool_message_by_call_id = {msg.tool_call_id: msg for msg in tool_messages}

    for requirement in requirements:
        if requirement.is_resolved():
            continue

        tool_exec = requirement.tool_execution
        if not tool_exec or not tool_exec.tool_call_id:
            continue

        tool_message = tool_message_by_call_id.get(tool_exec.tool_call_id)
        if tool_message is None:
            continue

        # External execution: raw content, no JSON parsing
        if requirement.pause_type == "external_execution":
            _resolve_external_execution(requirement, tool_message.content, tool_message.error)
            continue

        # Structured pause types: parse JSON payload
        parsed = parse_response_dict_str(tool_message.content)

        # Nothing here is held to an advertised schema, and no key this channel
        # did not already read is read for it. It took answers before the
        # interface described any shape, so the payloads it answered then are the
        # payloads it answers now: a decision it cannot read declines the call
        # rather than failing the run, a value of a kind the pause did not
        # describe is written on as it always was, and the spec's own spelling of
        # a decision stays unread here, because reading it would run a proposed
        # tool this channel refused to run for every caller written against it.
        payload = _payload_fields(parsed)
        if requirement.pause_type == "confirmation":
            _resolve_confirmation(requirement, payload, tool_message.error, unreadable_declines=True)
            continue

        if requirement.pause_type == "user_input":
            _resolve_user_input(requirement, payload)
        elif requirement.pause_type == "user_feedback":
            _resolve_user_feedback(requirement, payload)

    return requirements


def ensure_pause_can_be_continued(needed: List[NeededAnswer]) -> None:
    """Guard: raise if this pause is one no answer could have continued.

    Run before any answer is written, because a requirement whose one resolver
    cannot clear what it has open raises Agno's own internal refusal from inside
    that resolver, which says nothing about why the pause is a dead end. The
    reason is the one the terminal computed and failed the run with, so a client
    that resumed a pause it was never offered is told what the terminal said.

    It is handed the answers the pause needs rather than the requirements,
    because the caller keys the client's entries off that same list. Computing
    it here as well would let the two read different populations, which is the
    disagreement this whole round trip keeps having.
    """
    unanswerable = pause_not_continuable(needed)
    if unanswerable:
        raise ValueError(f"This run cannot be continued: {unanswerable}")


def ensure_no_result_answers_two_interrupts(
    needed: List[NeededAnswer], resume_entries: List[Any], tool_messages: List[AGUIToolMessage]
) -> None:
    """Guard: raise where one trailing tool result would answer two interrupts.

    The two channels address an answer by different keys. An entry names the
    interrupt it answers, so two requirements with ids of their own are two
    answers; a trailing tool result names the tool call, and every open
    requirement waiting on that call takes it. Where a request leaves two of them
    open under one call and reports a result for it, one answer the client sent
    once resolves both, and the completeness guard then reads a pause as answered
    that nobody answered twice.

    Refused here rather than on the older channel, which keyed answers by the
    tool call before this interface advertised an id to answer by and whose
    callers were written against that, and rather than at the terminal, which
    cannot tell the two shapes apart: a pause can hold two requirements for one
    real call, where one result really does answer both, and once the run has
    been stored and read back those are indistinguishable from two calls a model
    numbered alike. What tells them apart is what the client did, which is known
    only here.

    Asked of what the array is about to answer, so a request that answers one of
    the two by id leaves one open requirement on that call and the result it sent
    beside it has one place to go. Asked before anything is written, for the
    reason the pause guard above is: the refusal is about the request as a whole.
    """
    answered_by_id = {entry.interrupt_id for entry in resume_entries}
    reported_calls = {message.tool_call_id for message in tool_messages}
    left_to_the_result: Dict[str, List[str]] = {}
    for answer in needed:
        call_id = answer.tool_call_id
        if call_id is None or call_id not in reported_calls:
            continue
        # A requirement with no id of its own is keyed by this very call, so the
        # pause guard above has already refused the whole pause over it.
        if answer.interrupt_id is None or answer.interrupt_id in answered_by_id:
            continue
        left_to_the_result.setdefault(call_id, []).append(answer.interrupt_id)
    shared = {call_id: ids for call_id, ids in left_to_the_result.items() if len(ids) > 1}
    if not shared:
        return
    raise ValueError(
        "This resume cannot be applied: "
        + "; ".join(
            f"the result for tool call {call_id} answers interrupts {', '.join(ids)}, which are "
            f"{len(ids)} requirements this pause left open on that one call, and a trailing tool result is "
            "keyed by the call rather than by the interrupt it answers"
            for call_id, ids in shared.items()
        )
        + ". Answer them by interrupt id in the resume array."
    )


def ensure_requirements_resolved(requirements: List[RunRequirement]) -> None:
    """Guard: raise if a resume array left one of the run's requirements open.

    What it demands is what ``answers_a_pause_needs`` says the run needs, which
    is the same computation the terminal advertised from, so the set a client is
    told to answer and the set it is held to are one set. The interrupt id is
    what names each of them, because that is the key this channel addresses an
    answer by; naming the tool call named something the client never sent, and a
    requirement carrying no id has no name to give at all.

    The resume-array channel is what runs this, because the protocol has one
    array address every open interrupt of the interrupted run. The tool-message
    channel does not: merging tool messages leaves a requirement the client sent
    no result for untouched, and wiring the guard into it would decide for every
    existing caller that such a request is now an error. A partial resume must
    fail loud here rather than reach dispatch, where an unanswered confirmation
    tool is silently rejected.
    """
    outstanding = answers_a_pause_needs(requirements)
    if not outstanding:
        return
    addressed = [needed.interrupt_id for needed in outstanding if needed.interrupt_id]
    named = ", ".join(addressed) if addressed else f"{len(outstanding)} carrying no id to name them by"
    raise ValueError(f"Partial resume: interrupts {named} still unresolved")


# What a requirement waiting on a decision is told when the client abandoned the
# question instead of answering it. A tool call nobody decided about is one the
# agent must not run, so it is declined, and the note is what the run records as
# the reason.
CANCELLED_NOTE = "The client cancelled this interrupt without answering it"


def _cancellation_note(reported_error: Optional[str]) -> str:
    """What a cancelled interrupt records, carrying the reason it came with.

    A client that gave up can also say why, in the envelope a resolved entry
    reports a failed answer in, and the reason belongs where a resolved entry's
    goes: into what the run records about the call, which is the only place
    anything downstream can read it. It rides with the cancellation rather than
    replacing it, because the entry is still a cancellation, and a note carrying
    only the client's reason would read as a decision somebody made.
    """
    return f"{CANCELLED_NOTE}: {reported_error}" if reported_error else CANCELLED_NOTE


# The two statuses the protocol declares an entry can carry. The protocol's own
# model validates the field as a literal of exactly these, so this is about an
# entry that did not come through it: the resume array is read loosely typed,
# because the model exists only on a release that declares it, and a third value
# taking the resolved path would be answered from a payload that means something
# else.
RESUME_RESOLVED = "resolved"
RESUME_CANCELLED = "cancelled"


def _carried_at(envelope: Any, keys: Sequence[str]) -> Any:
    """What this envelope carries at these keys, stopping where the nesting ends.

    A client that wrote the reason where the advertised path nests further put
    it one level short of the leaf, which is a report all the same, so the walk
    hands back what it found rather than nothing. A key the envelope does not
    carry at all is no report.
    """
    found = envelope
    for key in keys:
        if not isinstance(found, dict):
            return found
        if key not in found:
            return None
        found = found[key]
    return found


def _where_a_failure_is_reported() -> str:
    """The advertised report path, spelled the way a refusal about it names it.

    Built from the path the interrupt advertises rather than written out, for
    the reason the walk below reads that path: a message naming somewhere else
    sends a client to a place nothing reads.
    """
    field, *keys = interrupts.ERROR_REPORT_PATH
    return field + "".join(f"[{key!r}]" for key in keys)


def _reported_error(entry: Any) -> Optional[str]:
    """The failure one resume entry reports, when it reports one.

    Read at the path the interrupt for a client-run tool advertises, walked out
    of that one constant: written out here as a nesting of its own, the two
    shared their last keys and not their structure, and a client following the
    advertisement would have had its report read as the result its tool returned.

    Every lookup is optional: a protocol release without ``metadata`` carries no
    envelope to read, and an entry that answers normally carries no error in the
    one it has. What is present is read wherever a client plausibly put it,
    inside the namespace the interrupt advertised or directly on the envelope,
    and anything present that is not a reason the run can record is refused
    rather than dropped, because dropping it stores the payload beside it as the
    result and tells the model the tool ran.
    """
    envelope_field, *nested = interrupts.ERROR_REPORT_PATH
    envelope = getattr(entry, envelope_field, None)
    if not isinstance(envelope, dict):
        return None
    reported = _carried_at(envelope, nested)
    if reported is None and len(nested) > 1:
        reported = _carried_at(envelope, nested[-1:])
    if reported is None:
        return None
    if not isinstance(reported, str) or not reported.strip():
        raise ValueError(
            f"Resume entry for interrupt {entry.interrupt_id!r} reports a failure under "
            f"{_where_a_failure_is_reported()}, "
            "which has to carry the reason as a non-empty string"
        )
    return reported


def _the_answer_it_carries(payload: Any) -> Any:
    """One resume entry's payload as the resolvers for the structured pauses read it.

    A client that sent the JSON as a string sent the answer the tool-message
    channel parses out of exactly that, so it goes through the same parser and
    the two channels read one payload the same way. A client-run tool's result
    is not parsed, because there a string is the result rather than an envelope
    around one.
    """
    return parse_response_dict_str(payload) if isinstance(payload, str) else payload


def _apply_resume_entry(requirement: RunRequirement, entry: Any) -> None:
    """Write one interrupt's answer onto the requirement waiting for it.

    A cancelled entry is a client that gave up on the question rather than
    answering it, and only the two decision-shaped pauses can express that: a
    declined tool call, and a client-run tool that reports back an error. A pause
    waiting on structured data has no such value to stand in for the data, and
    continuing without it would run the tool on whatever the model guessed, so
    the run stops with the reason instead.

    Either status can carry the failure its metadata reports, so the envelope is
    read once and held to the same shape on both: a report nothing can read is
    refused rather than passed over for what the status says, and a reason a
    cancellation gave joins the note, which is what carries it into the run and
    on to the model.

    An entry that answers can still report that answering failed, through the
    error its metadata carries. That is a resolved interrupt: the client did
    respond, and what it responded is that the tool raised. A client-run tool
    then reaches the model as a failed call rather than as output it never
    produced, and a decision reported the same way is declined with the reason,
    which is what an errored tool message has always done on the other channel.
    The structured pauses have nowhere to put it, so a reported failure stops one
    exactly as a cancellation does.

    An entry that resolves an interrupt has to carry the answer it resolves it
    with. One with no payload at all resolved a client-run tool as an empty
    success, storing a result nobody returned and telling the model the tool ran,
    while the same entry against a decision was refused; a client that ran
    nothing cancels, and one whose tool returned nothing says so with an empty
    payload rather than none.
    """
    if entry.status not in (RESUME_RESOLVED, RESUME_CANCELLED):
        raise ValueError(
            f"Resume entry for interrupt {entry.interrupt_id!r} carries status {entry.status!r}, "
            f"and the protocol declares only {RESUME_RESOLVED!r} and {RESUME_CANCELLED!r}"
        )

    pause_type = requirement.pause_type
    cancelled = entry.status == RESUME_CANCELLED
    reported_error = _reported_error(entry)

    if pause_type == "external_execution":
        if cancelled:
            _resolve_external_execution(requirement, "", _cancellation_note(reported_error))
        elif reported_error is None and entry.payload is None:
            raise ValueError(
                f"Resume entry for interrupt {entry.interrupt_id!r} resolves a tool the client runs and "
                "carries no result to resolve it with. A tool that returned nothing says so with an empty "
                f"payload; one that failed reports it under {_where_a_failure_is_reported()}"
            )
        else:
            _resolve_external_execution(requirement, external_execution_result(entry.payload), reported_error)
        return

    if pause_type == "confirmation":
        if cancelled:
            requirement.reject(note=_cancellation_note(reported_error))
        else:
            decision = _confirmation_fields(_the_answer_it_carries(entry.payload))
            _resolve_confirmation(
                requirement,
                _payload_fields(_the_answer_the_pause_advertised(requirement, decision)),
                reported_error,
                unreadable_declines=False,
            )
        return

    if cancelled or reported_error:
        unanswered = "was cancelled" if cancelled else f"reports the failure {reported_error!r}"
        alongside = f", reporting the failure {reported_error!r}" if cancelled and reported_error else ""
        raise ValueError(
            f"Resume entry for interrupt {entry.interrupt_id!r} {unanswered}{alongside}, and a {pause_type} pause "
            "cannot be resumed without the input it is waiting for"
        )

    answer = _the_answer_the_pause_advertised(requirement, _the_answer_it_carries(entry.payload))
    payload = _payload_fields(answer)
    if pause_type == "user_input":
        _resolve_user_input(requirement, payload)
    elif pause_type == "user_feedback":
        _resolve_user_feedback(requirement, payload)


def _apply_resume_entries(
    requirements: List[RunRequirement],
    needed: List[NeededAnswer],
    resume_entries: List[Any],
) -> None:
    """Write every entry's answer onto the open requirement it names.

    The lookup is keyed off the answers the pause needs, which is the list the
    terminal advertised its interrupts from, so an id a client was handed is the
    id its answer is written under. Keyed off every requirement instead, one
    already carrying the run's answer shadows an open one sharing its id, the
    client's answer lands on the resolved twin, and the open one is reported
    unresolved under the very id the client was told to send.

    An entry naming an interrupt the run does not carry is warned about and
    passed over rather than failing the resume: the protocol has a producer
    proceed without an entry it does not recognise and surface a warning rather
    than fail a run over an answer it never asked for, and failing here threw
    away every real answer sent beside it. It is never matched to some other
    pause, because guessing which one it meant would answer the wrong question.
    An entry for a requirement the run has already answered is a replay, so it
    is left alone in silence rather than reported as naming nothing.

    No guard runs here. A request can carry answers on both channels, and what
    the run still needs is a question about the two of them together, asked once
    by the caller after both have been applied.
    """
    open_by_interrupt_id = {answer.interrupt_id: answer.requirement for answer in needed if answer.interrupt_id}
    already_answered = {interrupt_id_of(requirement) for requirement in requirements if requirement.is_resolved()}

    for entry in resume_entries:
        addressed = open_by_interrupt_id.get(entry.interrupt_id)
        if addressed is not None:
            if not addressed.is_resolved():
                _apply_resume_entry(addressed, entry)
            continue
        if entry.interrupt_id in already_answered:
            continue
        log_warning(
            f"AG-UI resume entry addresses interrupt {entry.interrupt_id!r}, which this paused run does not "
            "carry; it is skipped and the run continues on the entries that answer it"
        )


def resolve_requirements_from_resume_entries(
    requirements: List[RunRequirement],
    resume_entries: List[Any],
    tool_messages: Optional[List[AGUIToolMessage]] = None,
) -> List[RunRequirement]:
    """Resolve a paused run's requirements from the answers the request carries.

    Each entry names an interrupt this run reported, and an answer to one the run
    is waiting on is held to the shape that interrupt advertised. An unreadable
    one still fails the run: the pause it was sent for stays open either way, and
    the client is owed the reason its payload was refused rather than the guard's
    report that something went unanswered.

    ``tool_messages`` are the answers the same request carried on the older
    channel, and they are applied after the array rather than dropped for it. The
    two channels address different things: the array names interrupts by id,
    while a trailing tool message is how a frontend-executed tool's result enters
    the conversation, keyed by tool call. One assistant turn can pause on both
    kinds at once, so a client running frontend tools sends exactly this mixture,
    and a channel dropped here is a pause reported unresolved that the request
    answered. The array wins where both answer one requirement, because applying
    it first leaves that requirement resolved and the tool-message pass skips
    what is already answered.

    Every open requirement must be answered before the run continues, because a
    partial resume reaches dispatch as an unanswered confirmation and is silently
    declined there. That is asked once, of what both channels together resolved.
    A pause holding one requirement no answer resolves is refused before any
    answer is written, so a client that resumed it reads the reason the terminal
    gave rather than whatever the first resolver raised. So is a request whose
    tool result would land on two interrupts at once, which the completeness
    guard cannot see afterwards: both of them come back resolved.
    """
    needed = answers_a_pause_needs(requirements)
    ensure_pause_can_be_continued(needed)
    ensure_no_result_answers_two_interrupts(needed, resume_entries, tool_messages or [])

    _apply_resume_entries(requirements, needed, resume_entries)
    if tool_messages:
        resolve_requirements_from_tool_messages(requirements, tool_messages)

    ensure_requirements_resolved(requirements)
    return requirements


def _find_paused_run(
    session: Union[AgentSession, TeamSession],
    is_team: bool,
    addresses: Callable[[RunRequirement], bool],
):
    """The paused run in this session that the incoming answers are for.

    ``addresses`` is what each channel matches a requirement by: the tool call a
    tool message names, or the interrupt id a resume entry names.
    """
    for run in session.runs or []:
        if is_team and not isinstance(run, TeamRunOutput):
            continue
        if run.status != RunStatus.paused:
            continue
        for req in run.requirements or []:
            if addresses(req):
                # The resume flow writes the user's answers into this run's
                # requirements before continuing it. History run objects are
                # shared between session reads, so the resume works on a copy
                # of its own.
                from copy import deepcopy

                return deepcopy(run)

    return None


async def resume_paused_run(
    entity: Union[Agent, Team],
    session_id: str,
    tool_messages: List[AGUIToolMessage],
    run_context: RunContext,
    run_kwargs: dict,
):
    """Continue the paused run the incoming tool results belong to.

    The tool-message channel: a frontend that executed a tool, or answered a
    prompt, sends the answer back as a trailing tool message keyed by the tool
    call it is for.
    """
    incoming_call_ids = {msg.tool_call_id for msg in tool_messages}
    return await _continue_paused_run(
        entity=entity,
        session_id=session_id,
        run_context=run_context,
        run_kwargs=run_kwargs,
        addresses=lambda req: bool(req.tool_execution and req.tool_execution.tool_call_id in incoming_call_ids),
        resolve=lambda requirements: resolve_requirements_from_tool_messages(requirements, tool_messages),
        nothing_matched="No paused run matching the provided tool results found in session",
    )


async def resume_paused_run_from_entries(
    entity: Union[Agent, Team],
    session_id: str,
    resume_entries: List[Any],
    run_context: RunContext,
    run_kwargs: dict,
    tool_messages: Optional[List[AGUIToolMessage]] = None,
):
    """Continue the paused run the incoming resume entries answer, if one is waiting.

    The protocol's own channel: each entry names an interrupt the run reported
    when it paused, which is the id of the requirement waiting on it.

    ``tool_messages`` are the answers the same request carried on the older
    channel, for the pauses the array does not address. The paused run is matched
    on either key, because a request answering a client-run tool and a decision
    at once holds both, and matching on one alone found no run for a request that
    named it twice.

    Nothing is returned when no paused run in the session carries any of them,
    because then the whole array answers nothing: the protocol reads a resume
    list that continues no interrupted run as entries the producer does not
    recognise, which it proceeds without rather than failing over. A client that
    retried a request, double-submitted one, or replayed a body whose run has
    already been continued gets there, and failing it turned an answer the run
    already holds into a run error. The caller is handed nothing so the request
    can go on as the fresh run it otherwise describes.
    """
    addressed = {entry.interrupt_id for entry in resume_entries}
    answered_calls = {message.tool_call_id for message in tool_messages or []}
    resumed = await _continue_paused_run(
        entity=entity,
        session_id=session_id,
        run_context=run_context,
        run_kwargs=run_kwargs,
        addresses=lambda req: (
            interrupt_id_of(req) in addressed
            or bool(req.tool_execution and req.tool_execution.tool_call_id in answered_calls)
        ),
        resolve=lambda requirements: resolve_requirements_from_resume_entries(
            requirements, resume_entries, tool_messages
        ),
        nothing_matched=None,
    )
    if resumed is None:
        named = ", ".join(sorted(repr(interrupt_id) for interrupt_id in addressed))
        also_dropped = (
            ". The results sent beside them, for tool calls "
            f"{', '.join(sorted(repr(call) for call in answered_calls))}, answer nothing either"
            if answered_calls
            else ""
        )
        log_warning(
            f"AG-UI resume entries address interrupts {named}, which no paused run in session {session_id} "
            f"carries; they answer nothing and the request runs without them{also_dropped}"
        )
    return resumed


async def _continue_paused_run(
    *,
    entity: Union[Agent, Team],
    session_id: str,
    run_context: RunContext,
    run_kwargs: dict,
    addresses: Callable[[RunRequirement], bool],
    resolve: Callable[[List[RunRequirement]], List[RunRequirement]],
    nothing_matched: Optional[str],
):
    """Continue the paused run these answers are for.

    ``nothing_matched`` is the refusal when the session holds no paused run they
    address, or None from a channel whose answers are dropped rather than
    refused, which is handed nothing back instead. A session that was never
    written is the same condition: it holds no paused run either.
    """
    if not isinstance(entity, (Agent, Team)):
        raise ValueError("Frontend tool resume requires a local Agent or Team")
    if not entity.db:
        raise ValueError("Frontend tool resume requires a database")

    session = await entity.aget_session(session_id=session_id)
    if not session:
        if nothing_matched is None:
            return None
        raise ValueError(f"Session {session_id} not found")
    if not isinstance(session, (AgentSession, TeamSession)):
        raise ValueError(f"Session {session_id} is not a valid session type")

    paused_run = _find_paused_run(session, is_team=isinstance(entity, Team), addresses=addresses)
    if not paused_run:
        if nothing_matched is None:
            return None
        raise ValueError(f"{nothing_matched} {session_id}")
    if not paused_run.requirements:
        raise ValueError(f"Run {paused_run.run_id} has no requirements to resume")

    requirements = resolve(paused_run.requirements)

    if paused_run.run_id:
        run_context.run_id = paused_run.run_id

    # Inline-door admission gate (see agno.os.job_queue): a durable ticket
    # owns this run's continuation - AG-UI must not execute it inline while
    # an HTTP durable continue CASes the ticket. The gate's refusal never
    # reaches the client as its 409/503: the route has already begun a 200
    # stream, and run_entity turns any exception from here into an in-band run
    # error carrying the status and detail as its message.
    from agno.os.job_queue import araise_if_ticket_owns_continue, get_active_queue_worker

    await araise_if_ticket_owns_continue(
        get_active_queue_worker(),
        paused_run.run_id,
        component_type="team" if isinstance(entity, Team) else "agent",
        component_id=getattr(entity, "id", None),
    )

    inner = entity.acontinue_run(  # type: ignore
        run_id=paused_run.run_id,
        session_id=session_id,
        requirements=requirements,
        stream=True,
        stream_events=True,
        run_context=run_context,
        **run_kwargs,
    )

    run_id = paused_run.run_id

    async def _stream_then_sync():
        # Status-only stream sync after the continue is consumed (parity with
        # the REST continue doors): a formerly-queued/streamed run's stream
        # view must stop saying PAUSED once the continue settles - otherwise
        # every later /resume replays the stale paused snapshot, and on Redis
        # the pausing replica's TTL refresher keeps those keys alive
        # indefinitely. only_if_tracked leaves never-streamed runs alone; a
        # re-paused continue re-parks the stream as PAUSED. Best-effort: a
        # stream-backend failure must not fail the AG-UI response.
        import contextlib

        from agno.os.utils import acomplete_continue_stream

        try:
            async for chunk in inner:
                yield chunk
        finally:
            with contextlib.suppress(Exception):
                await acomplete_continue_stream(entity, run_id, session_id, only_if_tracked=True)

    return _stream_then_sync()
