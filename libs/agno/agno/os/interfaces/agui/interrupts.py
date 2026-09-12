"""The AG-UI interrupt round trip for Agno's paused runs.

A paused Agno run is an AG-UI interrupt: the run has ended, and it ends carrying
what the client has to resolve before the work can go on. This module maps one
side to the other, in both directions.

Out: each requirement a pause still needs answered becomes one ``Interrupt``
inside ``RUN_FINISHED.outcome``, so a client is told the run is waiting rather
than reading a pause as a completion.

In: the ``resume`` array of the next request answers those interrupts by id, and
the answers are written onto the stored requirements the continue then runs from.

What the two directions have to agree about is one computation, not two:
``answers_a_pause_needs`` is the single answer to which of a paused run's
requirements must be answered and what each one's correlation id is. The
terminal advertises one interrupt per entry it returns and the resume guard
demands one answer per entry, so neither side can ask for a set the other does
not. Where an entry is one no answer could resolve, the pause cannot be
continued at all, and the terminal says so as a failed run rather than
advertising the rest: a resume has to answer every entry, so a client that
answered only the advertised ones would be refused with nothing on the wire
having said why.

The outcome is opt-in. A client released before the interrupt-aware lifecycle
stops sending its own resume directive the moment it sees a structured outcome,
which would strand the run, so the emission is off unless it is asked for. With
it off this interface emits exactly what it emitted before the outcome existed.
"""

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from agno.models.response import UserFeedbackQuestion, UserInputField
from agno.os.interfaces.agui.utils import readable
from agno.run.requirement import PauseType, RunRequirement
from agno.utils.log import log_warning

try:
    from ag_ui.core import Interrupt, RunFinishedInterruptOutcome

    INTERRUPT_OUTCOME_AVAILABLE = True
except ImportError:  # ag-ui-protocol older than the interrupt-aware run lifecycle
    INTERRUPT_OUTCOME_AVAILABLE = False

try:
    from ag_ui.core import SubagentFinishedSuspendedOutcome

    SUBAGENT_SUSPENDED_OUTCOME_AVAILABLE = True
except ImportError:  # ag-ui-protocol older than the suspended subagent outcome
    SUBAGENT_SUSPENDED_OUTCOME_AVAILABLE = False


def undeclared_fields(model: Any, fields: Iterable[str]) -> List[str]:
    """Which of these fields the installed protocol model does not declare.

    The one question this module asks about a protocol field, and it is asked of
    the schema. Asking the object instead answers a different question: the
    protocol's models accept a key they do not declare, keeping it as untyped
    extra data, so an attribute lookup finds a value this interface wrote under
    a name the wire format has no place for and reports it as present. Every
    gate and every emit site here reads this, so what is detected and what is
    written cannot come apart.
    """
    declared = getattr(model, "model_fields", {})
    return [field for field in fields if field not in declared]


def declares(model: Any, *fields: str) -> bool:
    """Whether the installed protocol model declares every one of these fields."""
    return not undeclared_fields(model, fields)


# The field an interrupt names the member it was raised inside by. It reached the
# protocol with the subagent lineage events, which is later than the run-level
# outcome, so an install can serve every interrupt this module builds for a
# single agent and still have no place to write this one.
MEMBER_ATTRIBUTION_FIELD = "subagent_run_id"


# The protocol's core reason values, which a client switches on to pick a
# dedicated surface. Both are spec-defined names a client matches exactly.
#
# Agno pauses for four kinds of thing, and they answer to two questions. A
# confirmation and an external execution are both a decision about one tool call
# the model has already proposed: approve this, or run it yourself and hand back
# the result. Either way the call is on the wire under the same id and the
# interrupt binds to it. A user-input and a user-feedback pause instead ask for
# structured data the model needs before it can carry on, and that shape travels
# as the interrupt's response schema. The exact kind stays readable in the
# metadata, so a client can tell "approve this" from "run this" when it wants to.
REASON_TOOL_CALL = "tool_call"
REASON_INPUT_REQUIRED = "input_required"

# The code a run terminal carries when the pause it reports can never be
# continued, so a client can tell that case from a run that failed while working
# without reading the message. It is this interface's own name, in the field the
# protocol keeps for one.
PAUSE_NOT_CONTINUABLE_CODE = "pause_not_continuable"

_PAUSE_TYPE_REASONS: Dict[PauseType, str] = {
    "confirmation": REASON_TOOL_CALL,
    "external_execution": REASON_TOOL_CALL,
    "user_input": REASON_INPUT_REQUIRED,
    "user_feedback": REASON_INPUT_REQUIRED,
}

# The key a confirmation payload carries its decision under. This is the name
# Agno's existing tool-message resume already reads, so one payload shape works
# on both channels. The interrupt spec's own approval example names the field
# ``approved`` instead, and a payload using that name is read too, on the resume
# array the interrupt advertising it is answered by.
CONFIRMATION_ACCEPTED_KEY = "accepted"
CONFIRMATION_ACCEPTED_ALIAS = "approved"
CONFIRMATION_NOTE_KEY = "note"

# What the note beside a decision is for, told to the client that sends it. Agno
# keeps one on a denial, where it reaches the model as the reason the call was
# refused, and its approval path takes none: ``confirm`` has nowhere to put one,
# and a note written on the requirement beside an approval does not survive the
# reload a stored run is read back through. One schema is advertised for both
# decisions, so this is where the advertisement says which of them records it.
CONFIRMATION_NOTE_DESCRIPTION = "Why the call was refused. Recorded on a denial; an approval keeps no note."

# The envelopes the structured pause types answer in, matching the payloads
# Agno's tool-message resume already accepts.
USER_INPUT_VALUES_KEY = "values"
USER_FEEDBACK_SELECTIONS_KEY = "selections"

# How a resume entry says that answering failed. The protocol keeps ``payload``
# for the answer the agent asked for and ``metadata`` for envelope data about
# the response, and reserves the ``ag-ui`` key inside the metadata for its own
# use, so the report travels under this interface's own key. Putting it in the
# payload instead would reach the model as the output of a tool that never ran.
# The resume channel reads them; an interrupt for a client-run tool advertises
# the path they form, because nothing else on the wire says the convention
# exists.
RESUME_METADATA_NAMESPACE = "agno"
RESUME_ERROR_KEY = "error"
ERROR_REPORT_PATH_KEY = "error_report_path"

# The path itself: the entry field the report is written on, then the keys
# inside it. Public, and read off this module rather than bound into the resume
# side at import, because the side that reads an incoming report walks exactly
# this and nothing else. Written out there as its own nesting, the two shared
# their last two keys and not their structure, so moving one moved nothing else.
ERROR_REPORT_PATH: Tuple[str, ...] = ("metadata", RESUME_METADATA_NAMESPACE, RESUME_ERROR_KEY)

# What the model is told when a client-run tool's result can be neither
# serialized nor rendered. Stored as the tool's output, because the resume has
# to write one: an empty result is what a tool that returned nothing says, and
# handing that back for a tool that returned something is the misreport this
# says out loud instead.
UNREADABLE_RESULT_NOTE = "The tool returned a result this server could not read."

_JSON_TYPES: Dict[type, str] = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
    list: "array",
    dict: "object",
}


def interrupt_id_of(requirement: RunRequirement) -> Optional[str]:
    """The id an interrupt for this requirement is correlated by.

    The requirement's own id is it: it is minted when the pause is recorded,
    stored with the paused run, and survives the reload the resume reads the run
    back through, which is what makes it usable as the key an answer comes back
    under. A release that stores no id falls back to the tool call the
    requirement is waiting on, which is unique within the run for the same
    reason the tool call events can be keyed by it.
    """
    stored_id = getattr(requirement, "id", None)
    if isinstance(stored_id, str) and stored_id:
        return stored_id
    tool_execution = requirement.tool_execution
    return tool_execution.tool_call_id if tool_execution else None


def _json_type_of(field_type: Any) -> Optional[str]:
    """The JSON Schema type for one of Agno's declared input field types.

    A type this does not recognise is left unconstrained rather than guessed at:
    a wrong type in the schema makes a client reject an answer the agent would
    have accepted.
    """
    return _JSON_TYPES.get(field_type) if isinstance(field_type, type) else None


def _agreed_on(described: Dict[str, Any], also: Dict[str, Any]) -> Dict[str, Any]:
    """The two descriptions of one payload key, reduced to what they agree on.

    Two declarations under one name are one key in the answer, and Agno writes
    that one value onto every declaration carrying the name, so the key is
    described once. Where the two disagree the constraint is dropped rather than
    resolved to one of them: a constraint one copy would fail is a client
    refusing an answer Agno accepts, which is the same wrong the unrecognised
    type above is left unconstrained for.
    """
    merged: Dict[str, Any] = {}
    for key, value in described.items():
        other = also.get(key)
        if isinstance(value, dict) and isinstance(other, dict):
            nested = _agreed_on(value, other)
            if nested:
                merged[key] = nested
        elif key in also and other == value:
            merged[key] = value
    return merged


def _that_cannot_be_null(described: Dict[str, Any]) -> Dict[str, Any]:
    """One field's description, with the one value it must never carry ruled out.

    A named type rules null out already. A field left with no type, because the
    type it declares is not one this maps or because two declarations of the
    name agree on nothing, is otherwise advertised as a schema a null satisfies,
    and a null is not an answer: the resume writes it onto the field, the field
    counts as unfilled, and the requirement fails the partial-resume guard as a
    run error. So the constraint that is known is stated without naming the type
    that is not.
    """
    if "type" in described:
        return described
    return {**described, "not": {"type": "null"}}


def _addressable(name: Any) -> bool:
    """Whether an answer can name this field or question at all.

    The payload is a JSON object keyed by the name, so a name that is not a
    non-empty string is one no client can send a value under.
    """
    return isinstance(name, str) and bool(name)


def _user_input_schema(fields: List[UserInputField]) -> Optional[Dict[str, Any]]:
    """The schema for the values a user-input pause is waiting on.

    Every field is described, and only the ones still without a value are
    required: the model can pre-fill some of them, and the run continues once
    the rest arrive.

    A name declared twice is advertised once, in both lists, because two keys of
    one name in the payload are one key and two entries in ``required`` are not
    a list a client can satisfy.
    """
    if not fields:
        return None
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for input_field in fields:
        name = input_field.name
        if not _addressable(name):
            continue
        described: Dict[str, Any] = {}
        json_type = _json_type_of(input_field.field_type)
        if json_type is not None:
            described["type"] = json_type
        description = readable(input_field.description, f"the description of the paused input field {name!r}")
        if description is not None:
            described["description"] = description
        if name in properties:
            log_warning(
                f"AG-UI advertises the paused input field {name!r} once: the pause declares it more than "
                "once, and one value in the answer is written onto every declaration of it."
            )
            described = _agreed_on(properties[name], described)
        properties[name] = _that_cannot_be_null(described)
        if input_field.value is None and name not in required:
            required.append(name)
    if not properties:
        return None
    values_schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        values_schema["required"] = required
    return {
        "type": "object",
        "properties": {USER_INPUT_VALUES_KEY: values_schema},
        "required": [USER_INPUT_VALUES_KEY],
    }


def _offered_labels(question: UserFeedbackQuestion, text: str) -> List[str]:
    """The choices this question offers, as the answers an enum holds a client to.

    The choices and each label in them are values a tool declared, so walking
    the one and reading the other both run code this interface did not write.
    The whole walk is guarded and not only the labels, because a sequence that
    refuses to be walked gives up every label at once, and a question advertised
    without its choices is still a question a client can answer in words.
    """
    try:
        offered = [
            readable(option.label, f"an option label of the paused question {text!r}")
            for option in question.options or []
        ]
    except Exception as error:
        log_warning(f"AG-UI could not read the options of the paused question {text!r}: {error}")
        return []
    labels = [label for label in offered if label]
    if len(labels) != len(offered):
        log_warning(
            f"AG-UI advertises the paused question {text!r} without {len(offered) - len(labels)} of its "
            "options: a label with no text to show is not a choice a client could pick out of a list."
        )
    return labels


def _asks_for_several(question: UserFeedbackQuestion, text: str) -> bool:
    """Whether this question takes more than one selection.

    A flag a tool set, so reading it runs that value's own code. One that cannot
    be read leaves the cap off rather than guessing at it: a schema capping an
    answer Agno would have accepted is a client refusing an answer the agent
    wanted, which is the wrong an unrecognised field type is left unconstrained
    for.
    """
    try:
        return bool(question.multi_select)
    except Exception as error:
        log_warning(f"AG-UI could not read whether the paused question {text!r} takes more than one selection: {error}")
        return True


def _user_feedback_schema(questions: List[UserFeedbackQuestion]) -> Optional[Dict[str, Any]]:
    """The schema for the selections a user-feedback pause is waiting on.

    One array per question, keyed by the question text, because that is the key
    Agno matches an answer back to its question by. A single-select question
    caps the array at one entry, so a client cannot offer a choice the agent
    would then have to reject, and every array asks for at least one entry: an
    empty array satisfies a required question while telling the model nothing,
    and the run would go on to use the answer nobody gave.

    A question asked twice under one text is advertised once, for the reason one
    input field declared twice is.
    """
    if not questions:
        return None
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for question in questions:
        text = question.question
        if not _addressable(text):
            continue
        labels = _offered_labels(question, text)
        item: Dict[str, Any] = {"type": "string"}
        if labels:
            item["enum"] = labels
        answered: Dict[str, Any] = {"type": "array", "items": item, "minItems": 1}
        if not _asks_for_several(question, text):
            answered["maxItems"] = 1
        header = readable(question.header, f"the header of the paused question {text!r}")
        if header is not None:
            answered["title"] = header
        if text in properties:
            log_warning(
                f"AG-UI advertises the paused question {text!r} once: the pause asks it more than once, "
                "and one selection in the answer is written onto every copy of it."
            )
            answered = _agreed_on(properties[text], answered)
        properties[text] = answered
        if question.selected_options is None and text not in required:
            required.append(text)
    if not properties:
        return None
    selections_schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        selections_schema["required"] = required
    return {
        "type": "object",
        "properties": {USER_FEEDBACK_SELECTIONS_KEY: selections_schema},
        "required": [USER_FEEDBACK_SELECTIONS_KEY],
    }


def _confirmation_schema() -> Dict[str, Any]:
    """The schema for a decision about one proposed tool call.

    A denial is a resolved interrupt carrying a negative decision, which is how
    the protocol expresses one; the ``cancelled`` status is for a client that
    abandoned the question instead of answering it. No edited-arguments field is
    offered, because this interface has no way to apply one and advertising the
    field is what tells a client it may offer that UI.

    The note is described as the denial's, because that is the only decision
    Agno records one on. Offered to both without a word, it was a field a client
    was told to fill and the approve branch then dropped.
    """
    return {
        "type": "object",
        "properties": {
            CONFIRMATION_ACCEPTED_KEY: {"type": "boolean"},
            CONFIRMATION_NOTE_KEY: {"type": "string", "description": CONFIRMATION_NOTE_DESCRIPTION},
        },
        "required": [CONFIRMATION_ACCEPTED_KEY],
    }


def advertised_answer_schema(requirement: RunRequirement) -> Optional[Dict[str, Any]]:
    """The shape of the answer this requirement is waiting for, when it has one.

    An external execution has none: the client runs the tool and hands back
    whatever that tool returns, which this interface cannot describe.

    Public because the resume side holds an incoming answer to this same schema.
    One description of the shape is the point: a second copy is the divergence
    between what a pause advertises and what it accepts.
    """
    pause_type = requirement.pause_type
    if pause_type == "confirmation":
        return _confirmation_schema()
    if pause_type == "user_input":
        return _user_input_schema(requirement.user_input_schema or [])
    if pause_type == "user_feedback":
        return _user_feedback_schema(requirement.user_feedback_schema or [])
    return None


# What a requirement still has open, in the words a warning about it uses.
_OPEN_ANSWERS: Dict[str, str] = {
    "needs_confirmation": "a decision",
    "needs_external_execution": "a result from a tool the client runs",
    "needs_user_input": "input values",
    "needs_user_feedback": "feedback selections",
}

# Per pause kind, the answer the resume channel applies: the requirement's own
# predicate the resolver refuses to run without, and every predicate that
# resolver's answer can clear. The two structured kinds share Agno's
# ``answered`` flag, so either one's answer clears both; a decision and a
# client-run tool clear only their own.
_PAUSE_TYPE_ANSWERS: Dict[PauseType, Tuple[str, Tuple[str, ...]]] = {
    "confirmation": ("needs_confirmation", ("needs_confirmation",)),
    "external_execution": ("needs_external_execution", ("needs_external_execution",)),
    "user_input": ("needs_user_input", ("needs_user_input", "needs_user_feedback")),
    "user_feedback": ("needs_user_feedback", ("needs_user_input", "needs_user_feedback")),
}


def _unanswerable_reason(requirement: RunRequirement, advertised: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why no answer could resolve this requirement, when none could.

    ``pause_type`` picks exactly one resolver per requirement on both resume
    channels, that resolver refuses to run unless the pause kind it belongs to
    is what the requirement is still waiting on, and a requirement with anything
    left open afterwards fails the partial-resume guard, which stops the whole
    resume rather than continuing the run. So a requirement whose one resolver
    cannot clear everything it has open is one no payload resolves, and an
    interrupt advertising it hands the client an id whose every answer strands
    the run.

    Clearing a predicate is not the same as filling what it stood for. Agno
    marks a whole call answered once its questions are, and that one flag stands
    for both structured kinds, so a feedback answer clears the input predicate
    with the fields the tool needs still empty.

    What a client would be shown is not censused here but taken as given:
    ``advertised`` is what the builder produced for this requirement, and a
    requirement it describes no shape for is one whose client is told to send
    structured data and told nothing about what, which is the state this guard
    exists to prevent. A census of the requirement's own fields answers a
    different question, and building a second copy of the shape here would run
    every guarded read of the run's own values twice for one terminal.
    """
    pause_type = requirement.pause_type
    applied, clears = _PAUSE_TYPE_ANSWERS[pause_type]
    still_open = [predicate for predicate in _OPEN_ANSWERS if getattr(requirement, predicate, False)]
    if applied not in still_open:
        return f"the resume channel answers it as a {pause_type} pause, which it is not waiting on"
    unclearable = [_OPEN_ANSWERS[predicate] for predicate in still_open if predicate not in clears]
    if unclearable:
        return (
            f"the resume channel answers it as a {pause_type} pause, "
            f"which leaves {' and '.join(unclearable)} unresolved"
        )
    if pause_type == "user_feedback" and any(
        input_field.value is None for input_field in requirement.user_input_schema or []
    ):
        return (
            f"the resume channel answers it as a {pause_type} pause, which marks the whole call answered "
            f"with {_OPEN_ANSWERS['needs_user_input']} still missing"
        )
    if pause_type == "user_input" and advertised is None:
        return "it asks for input and declares no field to put an answer in"
    if pause_type == "user_feedback" and advertised is None:
        return "it asks for feedback and declares no question to answer"
    # The one thing a produced schema cannot report: a field still empty that no
    # payload could be keyed to is left out of it, so it is counted here.
    unaddressable = [
        input_field.name
        for input_field in (requirement.user_input_schema or [])
        if input_field.value is None and not _addressable(input_field.name)
    ] + [
        question.question
        for question in (requirement.user_feedback_schema or [])
        if question.selected_options is None and not _addressable(question.question)
    ]
    if unaddressable:
        counted = (
            "1 unnamed field or question"
            if len(unaddressable) == 1
            else f"{len(unaddressable)} unnamed fields or questions"
        )
        return f"it waits on {counted}, which no answer can be keyed to"
    return None


@dataclass(frozen=True)
class NeededAnswer:
    """One answer a paused run must have before it can continue.

    ``interrupt_id`` is the key the answer comes back under, and it is the only
    key either side of the round trip uses. ``unanswerable`` says why no answer
    could resolve this requirement, and is None for the requirements a client
    can actually answer.

    ``answer_schema`` is the shape the interrupt advertises, built once here
    because both the guard that decides whether to advertise the requirement at
    all and the interrupt that carries the shape ask for it. The words in it come
    off the run's own values through guards that record what they could not read,
    so a second build is a second record of every one of those.
    """

    requirement: RunRequirement
    interrupt_id: Optional[str]
    unanswerable: Optional[str]
    answer_schema: Optional[Dict[str, Any]]

    @property
    def tool_name(self) -> Optional[str]:
        """The tool this answer is about, as far as the pause records one."""
        tool_execution = self.requirement.tool_execution
        return tool_execution.tool_name if tool_execution else None

    @property
    def tool_call_id(self) -> Optional[str]:
        """The pending call this answer is about, as far as the pause records one.

        The key the older channel addresses an answer by, where the interrupt id
        is the key the resume array addresses it by. Read off the same entry as
        the id, so a caller weighing one channel's answers against the other's
        reads one population and not two.
        """
        tool_execution = self.requirement.tool_execution
        return tool_execution.tool_call_id if tool_execution else None


def _no_answer_resolves(
    requirement: RunRequirement,
    interrupt_id: Optional[str],
    shared_ids: Set[str],
    advertised: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Why nothing a client sends could resolve this requirement, when nothing could.

    An id is what an answer is keyed to on both channels, so a requirement with
    none is one no entry can address. An id two of the pause's open requirements
    share is worse than none: an answer under it lands on whichever the
    correlation map kept, leaving the other open, which is the partial resume the
    guard stops. Both are refused here rather than at the one side that noticed,
    so the terminal and the guard read the same verdict.
    """
    if not interrupt_id:
        return "it carries no id an answer could be keyed to"
    if interrupt_id in shared_ids:
        return (
            f"another open requirement of this pause is keyed by {interrupt_id} too, "
            "and one answer under that id can resolve only one of them"
        )
    return _unanswerable_reason(requirement, advertised)


def answers_a_pause_needs(requirements: Iterable[RunRequirement]) -> List["NeededAnswer"]:
    """Every answer this paused run must have before it can continue, in order.

    The single answer to what a resume has to carry. The terminal builds one
    interrupt per entry and the resume guard demands one answer per entry, so
    the advertised set and the demanded set are the same set by construction
    rather than by two sides happening to agree.

    A resolved requirement is not one of them: the run already holds its answer,
    and an interrupt for it is an id the resume channel would refuse. That is
    the same filter ``active_requirements`` applies, so the terminal reading a
    paused event's active list and the guard reading the stored run's whole list
    come to the same entries.
    """
    open_requirements = [requirement for requirement in requirements if not requirement.is_resolved()]
    interrupt_ids = [interrupt_id_of(requirement) for requirement in open_requirements]
    advertised = [advertised_answer_schema(requirement) for requirement in open_requirements]
    shared_ids = {
        interrupt_id for interrupt_id, times in Counter(key for key in interrupt_ids if key).items() if times > 1
    }
    return [
        NeededAnswer(
            requirement=requirement,
            interrupt_id=interrupt_id,
            unanswerable=_no_answer_resolves(requirement, interrupt_id, shared_ids, answer_schema),
            answer_schema=answer_schema,
        )
        for requirement, interrupt_id, answer_schema in zip(open_requirements, interrupt_ids, advertised)
    ]


def pause_not_continuable(needed: List["NeededAnswer"]) -> Optional[str]:
    """Why this pause can never be continued, when it cannot be.

    A resume must answer every open requirement or the guard stops it, so one
    requirement no answer resolves makes the whole pause a dead end, whatever
    else it is waiting on. Both directions report it in these words: the
    terminal fails the run with them instead of advertising the answerable
    remainder, and the resume refuses the array with them, before it writes an
    answer onto anything, for a client that resumed the pause anyway.
    """
    stranded = [answer for answer in needed if answer.unanswerable]
    if not stranded:
        return None
    return "; ".join(
        f"the pause on tool {answer.tool_name!r}"
        + (f" under interrupt {answer.interrupt_id}" if answer.interrupt_id else "")
        + f" cannot be answered, because {answer.unanswerable}"
        for answer in stranded
    )


def _attribution_that_reaches_the_client(interrupt_id: str, subagent_run_id: Optional[str]) -> Optional[str]:
    """The member this interrupt can say it was raised inside, if it can say so.

    Detected here rather than at startup because the run-level outcome is served
    without it: the release that has the outcome and not this field serves the
    whole single-agent round trip, and only a pause inside a member asks for
    something it cannot write. Naming it anyway would put the value on the wire
    under a name the wire format does not define, so the attribution is dropped
    and the interrupt goes out answerable but unattributed.
    """
    if subagent_run_id is None or interrupt_attribution_available():
        return subagent_run_id
    log_warning(
        f"AG-UI cannot name the subagent that interrupt {interrupt_id} was raised inside: the installed "
        f"ag_ui.core omits Interrupt.{MEMBER_ATTRIBUTION_FIELD}, so it goes out unattributed. "
        "Please upgrade with `pip install -U ag-ui-protocol`."
    )
    return None


def build_interrupt(
    needed: Optional["NeededAnswer"],
    *,
    tool_call_id: Optional[str],
    tool_name: Optional[str],
    subagent_run_id: Optional[str] = None,
) -> Optional["Interrupt"]:
    """One answer a paused run needs, as the interrupt a client resolves it through.

    The id is the one ``answers_a_pause_needs`` gave it, which is the key the
    resume channel looks an answer up by. Nothing is decided here: an answer no
    client could send never reaches this, because the caller reads the same
    computation and fails the run instead. A pause that reports no requirement
    at all has no answer to be built from, so it passes none and is keyed by its
    tool call, which is unique within the run and is all such a release gives to
    key by.

    The tool call is what the client renders and answers against, and it is
    optional: a requirement whose pending call carries no id is still open and
    still answerable under the requirement's id, so it is advertised without
    one rather than withheld from a client that would then never be told the
    run is waiting on it.

    No message is set. The paused run's own words are already on the wire as the
    assistant message the pending tool call is parented to, so a message here
    would repeat the prompt rather than add one. What a renderer cannot read off
    the tool call events travels in the metadata instead: which of Agno's four
    pause kinds this is, and the name of the tool waiting on it.

    A client-run tool is told where to report that the tool raised, because the
    answer it hands back is a tool result and a failed one has to reach the model
    as a failed call rather than as output. That report is envelope data about
    the response and not the answer itself, so it is named in the metadata; the
    pause still advertises no response schema, since what the client hands back
    is whatever its tool returned.

    Only what there is something to say is written. A pause recording no tool
    name has none to give, a member this install has no field to name would be
    named nowhere, and a pause reporting no requirement has nothing that says
    which kind it is: all are left out rather than published as an explicit null
    or as a kind picked for looking plausible. Naming one anyway is a claim a
    client acts on, and every one of the four is wrong three times out of four:
    an approval published as an external execution is a tool the client is told
    to run itself, and the path for saying a client-run tool raised is a path no
    other kind accepts an answer on.

    The reason such a pause carries is ``tool_call``, which is the one thing the
    terminal did report: a proposed call the client was shown, keyed by that
    call's id and answered against it. ``input_required`` would claim the run is
    waiting on data the model needs, and nothing here says that.
    """
    if not INTERRUPT_OUTCOME_AVAILABLE:
        return None
    requirement = needed.requirement if needed is not None else None
    interrupt_id = needed.interrupt_id if needed is not None else tool_call_id
    if not interrupt_id:
        return None
    pause_type = requirement.pause_type if requirement is not None else None
    about_the_pause: Dict[str, Any] = {}
    if pause_type is not None:
        about_the_pause["pause_type"] = pause_type
    if tool_name is not None:
        about_the_pause["tool_name"] = tool_name
    if pause_type == "external_execution":
        about_the_pause[ERROR_REPORT_PATH_KEY] = list(ERROR_REPORT_PATH)
    written: Dict[str, Any] = {
        "id": interrupt_id,
        "reason": REASON_TOOL_CALL if pause_type is None else _PAUSE_TYPE_REASONS.get(pause_type, REASON_TOOL_CALL),
        "tool_call_id": tool_call_id,
        "response_schema": needed.answer_schema if needed is not None else None,
        "metadata": {RESUME_METADATA_NAMESPACE: about_the_pause},
    }
    attribution = _attribution_that_reaches_the_client(interrupt_id, subagent_run_id)
    if attribution is not None:
        written[MEMBER_ATTRIBUTION_FIELD] = attribution
    return Interrupt(**written)


def interrupt_outcome(interrupts: List["Interrupt"]) -> Optional["RunFinishedInterruptOutcome"]:
    """The run outcome for a pause, or nothing when there is no interrupt to carry.

    The protocol rejects an interrupt outcome with an empty list, so a pause this
    interface could build no interrupt for keeps the plain terminal it has always
    sent. The caller records that case.
    """
    if not INTERRUPT_OUTCOME_AVAILABLE or not interrupts:
        return None
    return RunFinishedInterruptOutcome(type="interrupt", interrupts=interrupts)


def suspended_outcome(interrupt_ids: List[str]) -> Optional["SubagentFinishedSuspendedOutcome"]:
    """A subagent's terminal outcome when the run paused inside it.

    ``interrupt_ids`` names the interrupts this subagent owns directly, and is
    empty for one suspended only because a subagent below it interrupted.

    Gated on the same declaration check the caller reads, rather than on the
    import alone: a release carrying the type without the field it is built
    from, or without the member terminal's place to carry the outcome, would
    otherwise be handed an outcome whose every part rides out undeclared.
    """
    if not subagent_suspension_available():
        return None
    return SubagentFinishedSuspendedOutcome(type="suspended", interrupt_ids=interrupt_ids or None)


def _resume_entry_model() -> Any:
    """The model one entry of the resume array arrives as, or a stand-in for it.

    A release too old to declare the entry model declares none of the fields an
    answer is read off, so the stand-in carries the name the protocol gives it
    and no fields at all, and the census names every one of them as missing
    rather than failing on the import.
    """
    try:
        from ag_ui.core import ResumeEntry
    except ImportError:  # ag-ui-protocol older than the resume array's entry model
        return type("ResumeEntry", (), {})
    return ResumeEntry


def interrupt_round_trip_fields() -> Dict[Any, Tuple[str, ...]]:
    """Every protocol field the run-level round trip writes or reads, per class.

    Built here rather than at import, because on a release without the interrupt
    types there is no class to key them by. The floor below reads this table, so
    what is detected and what is written cannot drift.

    Outgoing, that is every field the builders set, the discriminator the
    outcome is read by included: it is written on every outcome this module
    builds, and a release that renamed it would carry the old name as data it
    never declared rather than as the tag a client switches on.

    Incoming, it is the resume array and the entries inside it. The array is the
    channel the answers arrive in, so a release that does not declare it drops a
    client's answers as an unknown field. The fields of an entry are read as
    plain attributes while the answer is applied, so a release declaring them
    differently raises mid-run on a run this interface told the client to
    answer. An entry's ``metadata`` is not here: it is read through a lookup
    that answers a release without one with a default, and an entry carrying no
    failure report answers normally.

    Naming the member an interrupt was raised inside is not here either. That
    field reached the protocol a release later than the rest of the lifecycle,
    and a server exposing a single agent never writes it, so demanding it would
    refuse the whole round trip over a field the install would never be asked
    for. It is detected on its own below instead.
    """
    if not INTERRUPT_OUTCOME_AVAILABLE:
        return {}

    from ag_ui.core import RunAgentInput, RunFinishedEvent

    return {
        Interrupt: ("id", "reason", "tool_call_id", "response_schema", "metadata"),
        RunFinishedInterruptOutcome: ("type", "interrupts"),
        RunFinishedEvent: ("outcome",),
        RunAgentInput: ("resume",),
        _resume_entry_model(): ("interrupt_id", "status", "payload"),
    }


def _missing_interrupt_fields() -> List[str]:
    """The fields every interrupt round trip needs that the installed protocol omits.

    The protocol models accept attributes they do not declare, so an omitted
    field would otherwise leave the run: the value goes out under the name
    written here instead of the one the wire format defines, and a client reads
    an interrupt with no tool call and no schema rather than a refusal. On the
    incoming half an omitted field is worse than a wrong key: the answers are
    dropped unread, or read off an entry that carries them under another name,
    and the run this interface told the client to answer fails mid-continue
    instead of being refused before it started.
    """
    return sorted(
        f"{model.__name__}.{field}"
        for model, fields in interrupt_round_trip_fields().items()
        for field in undeclared_fields(model, fields)
    )


def interrupt_attribution_fields() -> Dict[Any, Tuple[str, ...]]:
    """The member-attribution field this module writes, per class it writes it on.

    Built here rather than at import, because on a release without the interrupt
    types there is no class to key it by. The availability check below reads this
    table, so what is detected and what is written cannot drift.
    """
    if not INTERRUPT_OUTCOME_AVAILABLE:
        return {}
    return {Interrupt: (MEMBER_ATTRIBUTION_FIELD,)}


def interrupt_attribution_available() -> bool:
    """Whether this install can name the member an interrupt was raised inside.

    Checked separately from the run-level outcome, and beside the suspended
    outcome below, because the protocol added all three at different times. An
    install with the outcome and not this field serves every pause a single
    agent reports; only a pause inside a member asks it for a field it has no
    name for.
    """
    fields = interrupt_attribution_fields()
    if not fields:
        return False
    return all(declares(model, *names) for model, names in fields.items())


def validate_interrupt_outcome(emit_interrupt_outcome: bool) -> bool:
    """Refuse the interrupt outcome on an install that cannot serve it.

    Everything the emission needs is feature-detected here rather than at the
    events themselves, which are built with a client already reading the stream.
    What is checked is the run-level round trip, which is what asking for the
    outcome asks for; the two things a Team's member adds to it arrived in later
    releases and are detected where they are written.
    """
    if not emit_interrupt_outcome:
        return False
    if not INTERRUPT_OUTCOME_AVAILABLE:
        raise ValueError(
            "emit_interrupt_outcome=True needs the AG-UI interrupt-aware run lifecycle. "
            "Please upgrade with `pip install -U ag-ui-protocol`."
        )
    undeclared = _missing_interrupt_fields()
    if undeclared:
        raise ValueError(
            "emit_interrupt_outcome=True needs every field the interrupt round trip writes on the AG-UI "
            "interrupt types, and the resume array the answers arrive in with the fields each answer is read off, "
            f"which the installed ag_ui.core omits: {', '.join(undeclared)}. "
            "Please upgrade with `pip install -U ag-ui-protocol`."
        )
    return True


def subagent_suspension_fields() -> Dict[Any, Tuple[str, ...]]:
    """The suspended-outcome fields this module writes, per class it writes them on.

    Built here rather than at import, because on a protocol release without the
    suspended outcome there are no classes to key it by. The availability check
    below reads this table, so what is detected and what is written cannot drift.
    """
    if not SUBAGENT_SUSPENDED_OUTCOME_AVAILABLE:
        return {}
    from ag_ui.core import SubagentFinishedEvent

    return {
        SubagentFinishedEvent: ("outcome",),
        SubagentFinishedSuspendedOutcome: ("type", "interrupt_ids"),
    }


def subagent_suspension_available() -> bool:
    """Whether this install can close a subagent the run paused inside as suspended.

    Checked separately from the interrupt outcome because the protocol added it
    later: an install can carry the run-level outcome and still omit this, and
    the interrupt is then attributed to the member without its lane saying it is
    waiting.
    """
    fields = subagent_suspension_fields()
    if not fields:
        return False
    return all(declares(model, *names) for model, names in fields.items())


def external_execution_result(payload: Any) -> str:
    """A client-run tool's return value as the result text Agno stores for it.

    A string is the result already. Anything else is the JSON the tool returned,
    so it is sent on as JSON rather than as a Python repr, which is what the
    tool-message channel carries and what a frontend can parse back.

    A value JSON has no spelling for falls back to its Python rendering, and the
    fallback says so: the model then reads a repr as a tool's output, and an
    operator reading the answer it gave has nothing else to trace that by.

    Both steps run the payload's own code, so both are guarded and anything they
    raise is caught: the payload arrives over the wire, the caller is resolving
    a problem with a tool result already, and a raise from here would replace
    that problem with a stringification error and fail the whole resume with it.
    Neither error the serializers raise on a value nested deeper than they walk
    is a ``TypeError`` or a ``ValueError``.
    """
    if isinstance(payload, str):
        return payload
    if payload is None:
        return ""
    try:
        return json.dumps(payload)
    except Exception as error:
        log_warning(
            f"AG-UI could not serialize a client-run tool's result as JSON, so the model is handed its "
            f"Python rendering instead: {error}"
        )
    try:
        return str(payload)
    except Exception as error:
        log_warning(f"AG-UI could not read a client-run tool's result at all: {error}")
        return UNREADABLE_RESULT_NOTE
