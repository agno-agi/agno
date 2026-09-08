import copy
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import TypeAdapter

from agno.utils.log import log_warning

# Agno's run loop injects these into session_state so tools and instruction
# templates can read them, and strips them again before the session row is
# persisted. They are Agno's own record keeping rather than application state,
# so every state event drops them by name: a client that sent one of these keys
# itself never gets it back, and holds no value under it at all.
RUNTIME_STATE_KEYS = frozenset({"current_user_id", "current_session_id", "current_run_id"})


class StateDeltaUnavailable(Exception):
    """Raised when state changed but no JSON Patch could be produced for it.

    ``reason`` names which cause fired. The causes need different fixes, so a
    caller that suppresses repeats can still report each one, and they are not
    all answerable the same way: every reason but ``STATE_NOT_SENDABLE`` leaves
    a full snapshot as a way to carry the change, while that one says the state
    cannot go out under any event at all.
    """

    NO_JSONPATCH = "no_jsonpatch"
    PATCH_FAILED = "patch_failed"
    EMPTY_PATCH = "empty_patch"
    PATCH_NOT_REPLAYABLE = "patch_not_replayable"
    PATCH_NOT_FAITHFUL = "patch_not_faithful"
    STATE_NOT_SENDABLE = "state_not_sendable"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _visible_state(state: Any) -> Any:
    """``state`` without Agno's runtime bookkeeping keys, sharing its values.

    Anything that is not a dict holds no bookkeeping keys and is handed back
    whole. Kept apart from the copy below because most of what reads this only
    encodes it and drops it, and copying state a run holds open is the most
    expensive thing on that path.
    """
    if not isinstance(state, dict):
        return state
    return {key: value for key, value in state.items() if key not in RUNTIME_STATE_KEYS}


def client_state(state: Any) -> Any:
    """Copy ``state`` with Agno's runtime bookkeeping keys removed.

    The copy is what makes the result safe to hold while the run mutates state
    on: an event already handed over would otherwise keep changing under the
    client. Anything that is not a dict is copied whole rather than refused,
    because the terminal handler passes the run's own session_state through
    here and a refusal would cost the client its RUN_FINISHED. A value
    ``copy.deepcopy`` cannot copy at all still raises from here, so a caller
    that owes the client an event either way has to be ready for that.
    """
    return copy.deepcopy(_visible_state(state))


# A client never holds the Python objects in session_state, only the JSON the
# AG-UI event encoder makes of them, so both the no-change question and the
# patch describing the change are put to that encoded form. Reading the objects
# disagrees with the wire both ways: {1: "a"} and {True: "a"} are one Python key
# but two different JSON objects, while a list and a tuple are two Python
# objects but one JSON array.
_STATE_SERIALIZER: TypeAdapter = TypeAdapter(Any)

# Names the cause for the once-per-stream warning registry, alongside the
# reasons ``StateDeltaUnavailable`` carries.
_STATE_NOT_ENCODABLE = "state_not_encodable"


def _json_state(state: Any) -> Any:
    """The JSON document the AG-UI event encoder will make of ``state``.

    ``TypeAdapter(Any)`` in JSON mode, by alias, is the same serializer the
    encoder runs over a STATE_SNAPSHOT payload, so this is the document a
    client ends up holding: its keys are the keys a JSON Pointer has to name.
    Dropping ``by_alias`` would point a patch at a pydantic model's field name
    where the client holds the alias.
    """
    return _STATE_SERIALIZER.dump_python(state, mode="json", by_alias=True)


def _encoded_document(document: Any) -> str:
    """``document`` as one comparable string.

    Key order is normalised because the client reads the parsed JSON, so a
    dict rebuilt holding the same entries in a different order is not
    something the client can see. Takes the document rather than the state so
    that a caller needing both pays for the serializer once.
    """
    return json.dumps(document, sort_keys=True)


@dataclass
class StreamState:
    """Per-stream state for AG-UI event translation.

    Tracks message lifecycle, tool calls, reasoning sessions, and state deltas.
    All handlers receive this object and mutate it as events flow through.

    Text Message Lifecycle:
        CLOSED (initial)      OPEN                   CLOSED
        text_message_id=""    text_message_id=X      text_message_id=X (persists!)
        text_message_open=F   text_message_open=T    text_message_open=F

    The text_message_id persists after close so tool calls can parent to it.
    """

    # Text message tracking
    text_message_id: str = ""
    text_message_open: bool = False

    # Tool call tracking
    active_tool_call_ids: Set[str] = field(default_factory=set)
    ended_tool_call_ids: Set[str] = field(default_factory=set)
    pending_tool_calls_parent_id: str = ""

    # Reasoning tracking
    reasoning_message_id: Optional[str] = None
    reasoning_step_count: int = 0

    # State delta tracking
    _last_snapshot: Any = field(default=None, repr=False)
    _last_snapshot_encoding: Optional[Tuple[Any, str]] = field(default=None, repr=False)
    _warned_delta_fallbacks: Set[str] = field(default_factory=set, repr=False)

    # Run context
    thread_id: str = ""
    run_id: str = ""
    run_state: Optional[Dict[str, Any]] = None

    def open_text_message(self) -> str:
        self.text_message_id = str(uuid.uuid4())
        self.text_message_open = True
        return self.text_message_id

    def close_text_message(self) -> None:
        # ID persists for tool call parenting — only flag changes
        self.text_message_open = False

    def start_tool_call(self, tool_call_id: str) -> None:
        self.active_tool_call_ids.add(tool_call_id)

    def end_tool_call(self, tool_call_id: str) -> None:
        self.active_tool_call_ids.discard(tool_call_id)
        self.ended_tool_call_ids.add(tool_call_id)

    def get_parent_message_id_for_tool_call(self) -> str:
        # pending_tool_calls_parent_id used for sequential tools after message close
        if self.pending_tool_calls_parent_id:
            return self.pending_tool_calls_parent_id
        # text_message_id persists after close
        return self.text_message_id

    def set_pending_tool_calls_parent_id(self, parent_id: str) -> None:
        self.pending_tool_calls_parent_id = parent_id

    def clear_pending_tool_calls_parent_id(self) -> None:
        self.pending_tool_calls_parent_id = ""

    def start_reasoning(self) -> str:
        self.reasoning_message_id = str(uuid.uuid4())
        self.reasoning_step_count = 0
        return self.reasoning_message_id

    def ensure_reasoning_started(self) -> Tuple[str, bool]:
        if self.reasoning_message_id is not None:
            return self.reasoning_message_id, False
        return self.start_reasoning(), True

    def next_reasoning_step(self) -> int:
        self.reasoning_step_count += 1
        return self.reasoning_step_count

    def end_reasoning(self) -> None:
        self.reasoning_message_id = None
        self.reasoning_step_count = 0

    def run_label(self) -> str:
        """Names the conversation and the run, for a warning to be traced by.

        A server carries many conversations at once, so a warning that says
        only that some run degraded cannot be tied back to the one it happened
        in, nor to the state the client of that conversation is left holding.
        """
        return f"(thread_id={self.thread_id}, run_id={self.run_id})"

    def should_warn_delta_fallback(self, reason: str) -> bool:
        """Whether this fallback ``reason`` has yet to be reported on this stream.

        Records the reason, so one cause is reported once however many state
        changes it affects, while a second, different cause is still reported.
        """
        if reason in self._warned_delta_fallbacks:
            return False
        self._warned_delta_fallbacks.add(reason)
        return True

    def set_state_snapshot(self, state: Any) -> None:
        self._last_snapshot = client_state(state)
        self._last_snapshot_encoding = None

    def _snapshot_encoding(self) -> Tuple[Any, str]:
        """The baseline's JSON document and its comparable text, encoded once.

        The baseline only moves when a new snapshot is recorded, so every
        emission that follows one reads this rather than putting the same
        state through the serializer again.
        """
        if self._last_snapshot_encoding is None:
            document = _json_state(self._last_snapshot)
            self._last_snapshot_encoding = (document, _encoded_document(document))
        return self._last_snapshot_encoding

    def _warn_state_has_no_json_form(self, error: Exception) -> None:
        """Report state the no-change question cannot be put to.

        Such state counts as changed, never as unchanged: a client can discard
        an update it already held, but it cannot recover one that was never
        sent. Reported once per stream, so it can be told apart from an
        ordinary change.
        """
        if self.should_warn_delta_fallback(_STATE_NOT_ENCODABLE):
            log_warning(
                f"AG-UI state has no JSON form to compare against the last snapshot ({error}). "
                f"Treating it as changed. {self.run_label()}"
            )

    def compute_state_delta(self, current_state: Any) -> Optional[List[Dict[str, Any]]]:
        """JSON Patch ops taking the last snapshot to ``current_state``.

        Returns ``None`` when no snapshot has been recorded yet, and when
        nothing the client can see has changed. Raises
        ``StateDeltaUnavailable``, for whichever cause fired, only when state
        did change and no patch could be built for it, so the caller can decide
        what the change is still worth sending as, rather than dropping it
        unremarked.
        """
        if self._last_snapshot is None:
            return None

        # Not copied: nothing here outlives the call, and the run holds the
        # only reference that has to survive it, in the baseline copy.
        current = _visible_state(current_state)

        try:
            # Encoded at the boundary the client reads state at, once, so the
            # no-change question below, the diff and the replay check all read
            # the document the client would hold: every pointer then names a
            # key of that document rather than a Python key that was never on
            # the wire.
            current_document = _json_state(current)
            current_encoded = _encoded_document(current_document)
        except Exception as e:
            # State with no JSON form is not a patch that could not be built:
            # it is state no event can carry, a full snapshot included, so this
            # is raised ahead of every other cause, and reported ahead of the
            # no-change question it cannot answer either. Whatever else is
            # wrong, nothing about this state is sendable, and the fix is in
            # the application code that put the value in session_state.
            self._warn_state_has_no_json_form(e)
            raise StateDeltaUnavailable(
                StateDeltaUnavailable.STATE_NOT_SENDABLE,
                f"AG-UI state has no JSON form, so no state event carrying it can be sent ({e}).",
            ) from e

        snapshot_document: Any = None
        snapshot_has_no_json_form: Optional[Exception] = None
        try:
            snapshot_document, snapshot_encoded = self._snapshot_encoding()
        except Exception as e:
            # A baseline with no JSON form leaves nothing to diff against, so
            # the change counts as one no patch could be built for. The cause
            # is held rather than raised here so that a missing jsonpatch,
            # which an operator can act on, is still the cause reported first.
            snapshot_has_no_json_form = e
            self._warn_state_has_no_json_form(e)
        else:
            # Asked before any cause of failure can fire, because a run that
            # never changed state owes the client nothing either way. Asking
            # inside one failure branch alone would make that branch answer
            # every later call of the run with a full snapshot the client
            # already holds.
            if current_encoded == snapshot_encoded:
                return None

        try:
            import jsonpatch
        except Exception as e:
            raise StateDeltaUnavailable(
                StateDeltaUnavailable.NO_JSONPATCH,
                f"AG-UI STATE_DELTA events need the jsonpatch package, which is not importable ({e}). "
                "Install it with `pip install jsonpatch`, or install Agno's agui extra.",
            ) from e

        if snapshot_has_no_json_form is not None:
            raise StateDeltaUnavailable(
                StateDeltaUnavailable.PATCH_FAILED,
                f"AG-UI state delta could not be computed: {snapshot_has_no_json_form}.",
            ) from snapshot_has_no_json_form

        try:
            ops = jsonpatch.make_patch(snapshot_document, current_document).patch
        except Exception as e:
            raise StateDeltaUnavailable(
                StateDeltaUnavailable.PATCH_FAILED, f"AG-UI state delta could not be computed: {e}."
            ) from e

        if not ops:
            # ``jsonpatch`` reads a list element by element with ``==``,
            # which calls 0 and False the same element, so [0] becoming
            # [false] is a change to the client and no change to it. Nothing
            # failed, so this carries its own reason: a caller that reports one
            # cause per run still reports a real failure that follows it.
            raise StateDeltaUnavailable(
                StateDeltaUnavailable.EMPTY_PATCH,
                "AG-UI state encodes to different JSON than the last snapshot did, "
                "but the difference is one JSON Patch has no operation to describe.",
            )

        # Ops are worth sending only once they are known to reproduce the
        # document the client is owed. The same element-by-element ``==`` that
        # can leave the patch empty can also leave it describing one half of a
        # change, and a half-patch is not empty: it goes out, the baseline
        # advances past the half it omitted, and the client holds state the run
        # has permanently moved on from.
        try:
            replayed = jsonpatch.apply_patch(snapshot_document, ops)
            reproduces_the_change = _encoded_document(replayed) == current_encoded
        except Exception as e:
            # A replay that cannot run at all and a replay that runs and lands
            # somewhere else are two failures with two fixes, so they carry two
            # reasons: sharing one would let whichever fired first silence the
            # other for the rest of the stream.
            raise StateDeltaUnavailable(
                StateDeltaUnavailable.PATCH_NOT_REPLAYABLE,
                f"AG-UI state delta could not be replayed onto the last snapshot to check it ({e}).",
            ) from e

        if not reproduces_the_change:
            raise StateDeltaUnavailable(
                StateDeltaUnavailable.PATCH_NOT_FAITHFUL,
                "AG-UI state delta does not reproduce the state it was computed for, "
                "so a client applying it would be left holding state the run has moved on from.",
            )

        return ops
