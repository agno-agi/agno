import copy
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from agno.utils.log import log_warning

# The three client-facing presentations of a delegation to a subagent. Values
# name what the CLIENT SEES, not an internal switch:
#   "inline"     - the subagent's output streams as the parent's own work,
#                  byte-identical to the pre-lineage behavior. The safe default:
#                  a client already in production cannot be protected after the
#                  fact from event types its transport rejects.
#   "attributed" - the full subagent surface: SUBAGENT_* lifecycle events, and a
#                  subagent_run_id on the message, tool call and reasoning events
#                  a subagent produced. State events stay unstamped, because a
#                  team's session state is one shared document.
#   "hidden"     - invisible delegation: no SUBAGENT_* lifecycle event and no
#                  per-event subagent stamp reaches the wire, and nothing a
#                  subagent streamed is sent as its own work. What the client
#                  sees is the parent's: the delegation tool call, whose
#                  arguments name the member and carry the task text just as the
#                  default sends them, that call's result, and the parent's own
#                  reply. Two things a subagent produced also arrive: a change
#                  its tool made to the session state, which is one shared
#                  document, and a pending tool call it paused on, which the run
#                  cannot continue without. Neither is attributed to it. What a
#                  subagent's failure withholds is that same identity: the
#                  lineage events and the per-event stamps stay off the wire and
#                  nothing on it names the subagent that failed, while the
#                  reason the run stopped still reaches the client, because a
#                  subagent's terminal can be the run's only account of how it
#                  ended and is then read as the run's own.
SUBAGENT_VISIBILITY_INLINE = "inline"
SUBAGENT_VISIBILITY_ATTRIBUTED = "attributed"
SUBAGENT_VISIBILITY_HIDDEN = "hidden"
SUBAGENT_VISIBILITY_VALUES = (
    SUBAGENT_VISIBILITY_INLINE,
    SUBAGENT_VISIBILITY_ATTRIBUTED,
    SUBAGENT_VISIBILITY_HIDDEN,
)

# Lane key for the top-level entity's own streaming state. Subagent lanes are
# keyed by the subagent's run id.
ROOT_LANE: Optional[str] = None


# The tools a Team delegates through, named exactly as the framework registers
# them: two for member delegation, and two more when the team works a task list.
# The decision keys on the name because argument shape does not identify a
# delegation: Agno's own ``update_user_memory`` also takes a ``task``, and the
# tasks-mode tools take none.
DELEGATION_TOOL_NAMES = frozenset(
    {
        "delegate_task_to_member",
        "delegate_task_to_members",
        "execute_task",
        "execute_tasks_parallel",
    }
)


@dataclass
class OpenToolCall:
    """One tool call still open in a lane.

    The tool name is a required part of the record: it is what identifies a
    delegation, and without it a reader is left inferring intent from the
    arguments, which mistakes any tool taking a ``task`` for a delegation.
    """

    name: str
    args: Dict[str, Any]
    parent_message_id: str

    @property
    def is_delegation(self) -> bool:
        return self.name in DELEGATION_TOOL_NAMES


@dataclass
class Lane:
    """Streaming state for one attribution lane.

    A lane is the top-level entity or a single subagent invocation. Message,
    reasoning and tool-parent state is per-lane so a subagent's text never
    lands in the parent's bubble and two subagents streaming at once keep
    independent spans.

    Text Message Lifecycle:
        CLOSED (initial)      OPEN                   CLOSED
        text_message_id=""    text_message_id=X      text_message_id=X (persists!)
        text_message_open=F   text_message_open=T    text_message_open=F

    The text_message_id persists after close so tool calls can parent to it.
    """

    text_message_id: str = ""
    text_message_open: bool = False
    pending_tool_calls_parent_id: str = ""
    reasoning_message_id: Optional[str] = None
    reasoning_step_count: int = 0


@dataclass
class Subagent:
    """A subagent invocation announced on the wire."""

    name: str
    parent_lane: Optional[str] = None


@dataclass
class StreamState:
    """Per-stream state for AG-UI event translation.

    Tracks message lifecycle, tool calls, reasoning sessions, state deltas and
    subagent lineage. All handlers receive this object and mutate it as events
    flow through.

    Lane-scoped state lives in ``lanes``; the message, reasoning and tool-parent
    properties below read whichever lane the chunk being mapped belongs to, and
    the methods beside them are what writes it. Under ``inline`` visibility every
    chunk resolves to ROOT_LANE, so there is exactly one lane and the emitted
    stream is unchanged.
    """

    # Tool call tracking. Tool call ids are unique across the run, so these stay
    # flat; ``tool_call_lanes`` remembers which lane each one belongs to so a
    # tool call closed at run end is still attributed to its own subagent.
    active_tool_call_ids: Set[str] = field(default_factory=set)
    ended_tool_call_ids: Set[str] = field(default_factory=set)
    tool_call_lanes: Dict[str, Optional[str]] = field(default_factory=dict)

    # State delta tracking
    _last_snapshot: Optional[Dict[str, Any]] = field(default=None, repr=False)

    # Run context
    thread_id: str = ""
    run_id: str = ""
    run_state: Optional[Dict[str, Any]] = None

    # Lineage
    subagent_visibility: str = SUBAGENT_VISIBILITY_INLINE
    lanes: Dict[Optional[str], Lane] = field(default_factory=dict)
    current_lane: Optional[str] = ROOT_LANE
    # Run id of the top-level entity, learned from the first chunk that reports
    # no parent, so a subagent whose parent IS the top-level run reports no parent
    # subagent. It is deliberately not seeded from ``run_id``: a resumed run
    # executes under the stored paused run's id, not the request's, and seeding
    # would read every chunk of it as a subagent's.
    root_run_id: Optional[str] = None
    open_subagents: Dict[str, Subagent] = field(default_factory=dict)
    # Every subagent ever announced, kept after its terminal so a lane drained at
    # run end still knows where it sits in the delegation tree.
    announced_subagents: Dict[str, Subagent] = field(default_factory=dict)
    # SUBAGENT_FINISHED / SUBAGENT_ERROR are terminal for the id they name, so a
    # closed subagent may neither be re-announced nor own a second terminal.
    closed_subagents: Set[str] = field(default_factory=set)
    # Open tool calls per lane, each holding its name, its arguments and the
    # message it was parented to. A delegation is one of these calls, so this is
    # what links a subagent back to the exact call that spawned it.
    open_tool_calls: Dict[Optional[str], Dict[str, OpenToolCall]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validated here as well as at the interface boundary, so a value that
        # reached this object by any other route cannot become a silent fourth
        # mode that behaves like none of the three.
        if self.subagent_visibility not in SUBAGENT_VISIBILITY_VALUES:
            raise ValueError(
                f"subagent_visibility must be one of {SUBAGENT_VISIBILITY_VALUES}, got {self.subagent_visibility!r}"
            )

    @property
    def hides_subagents(self) -> bool:
        return self.subagent_visibility == SUBAGENT_VISIBILITY_HIDDEN

    def lane(self, key: Optional[str]) -> Lane:
        """The state of one named lane, created on first use.

        The key is always explicit: ROOT_LANE is ``None``, so a "current lane"
        default here would make a root-lane lookup indistinguishable from one.
        """
        existing = self.lanes.get(key)
        if existing is None:
            existing = Lane()
            self.lanes[key] = existing
        return existing

    def active_lane(self) -> Lane:
        """The state of the lane the chunk being mapped belongs to."""
        return self.lane(self.current_lane)

    # --- Lane-scoped message state -------------------------------------------

    @property
    def text_message_id(self) -> str:
        return self.active_lane().text_message_id

    @property
    def text_message_open(self) -> bool:
        return self.active_lane().text_message_open

    @property
    def reasoning_message_id(self) -> Optional[str]:
        return self.active_lane().reasoning_message_id

    def open_text_message(self) -> str:
        lane = self.active_lane()
        lane.text_message_id = str(uuid.uuid4())
        lane.text_message_open = True
        return lane.text_message_id

    def close_text_message(self) -> None:
        # ID persists for tool call parenting — only flag changes
        self.active_lane().text_message_open = False

    def start_tool_call(self, tool_call_id: str) -> None:
        self.active_tool_call_ids.add(tool_call_id)
        self.tool_call_lanes[tool_call_id] = self.current_lane

    def end_tool_call(self, tool_call_id: str) -> None:
        self.active_tool_call_ids.discard(tool_call_id)
        self.ended_tool_call_ids.add(tool_call_id)
        self.open_tool_calls.get(self.lane_of_tool_call(tool_call_id), {}).pop(tool_call_id, None)

    def lane_of_tool_call(self, tool_call_id: str) -> Optional[str]:
        return self.tool_call_lanes.get(tool_call_id, ROOT_LANE)

    def tool_call_started(self, tool_call_id: str) -> bool:
        """Whether a start has gone out for a call the run itself opened.

        Every call opened from the run's own tool-call event is recorded in
        ``tool_call_lanes`` and stays there once it ends, so this holds whatever
        state such a call is in now, and a call the client already has a start
        for is never given a second one. The starts a pause prompt writes are
        not recorded here: one terminal produces one prompt, which dedupes
        against the calls it is building rather than against this.
        """
        return tool_call_id in self.tool_call_lanes

    def active_tool_calls_in_order(self) -> List[str]:
        """Tool calls still open, in the order the run opened them.

        The close order reaches the client, so it is read from
        ``tool_call_lanes``, which records every call as it starts, rather than
        from the unordered active set. A call that somehow never reached that
        record still has to be closed, so any such id follows, sorted.
        """
        ordered = [tool_call_id for tool_call_id in self.tool_call_lanes if tool_call_id in self.active_tool_call_ids]
        ordered.extend(sorted(self.active_tool_call_ids.difference(ordered)))
        return ordered

    def get_parent_message_id_for_tool_call(self) -> str:
        lane = self.active_lane()
        # pending_tool_calls_parent_id used for sequential tools after message close
        if lane.pending_tool_calls_parent_id:
            return lane.pending_tool_calls_parent_id
        # text_message_id persists after close
        return lane.text_message_id

    def set_pending_tool_calls_parent_id(self, parent_id: str) -> None:
        self.active_lane().pending_tool_calls_parent_id = parent_id

    def clear_pending_tool_calls_parent_id(self) -> None:
        self.active_lane().pending_tool_calls_parent_id = ""

    def start_reasoning(self) -> str:
        lane = self.active_lane()
        lane.reasoning_message_id = str(uuid.uuid4())
        lane.reasoning_step_count = 0
        return lane.reasoning_message_id

    def ensure_reasoning_started(self) -> Tuple[str, bool]:
        lane = self.active_lane()
        if lane.reasoning_message_id is not None:
            return lane.reasoning_message_id, False
        return self.start_reasoning(), True

    def next_reasoning_step(self) -> int:
        lane = self.active_lane()
        lane.reasoning_step_count += 1
        return lane.reasoning_step_count

    def end_reasoning(self) -> None:
        lane = self.active_lane()
        lane.reasoning_message_id = None
        lane.reasoning_step_count = 0

    # --- Lineage -------------------------------------------------------------

    def lane_for(self, run_id: Optional[str], parent_run_id: Optional[str]) -> Optional[str]:
        """The lane a chunk belongs to, without changing any state.

        Agno stamps every chunk with its own ``run_id`` and, for a subagent, the
        ``parent_run_id`` of the run that delegated to it. A chunk that reports
        no parent is the top-level entity's own work. Under ``inline`` visibility
        every chunk is the top-level entity's work as far as the wire is
        concerned, which is what keeps that stream unchanged.
        """
        if self.subagent_visibility == SUBAGENT_VISIBILITY_INLINE:
            return ROOT_LANE
        if parent_run_id is None or run_id is None or run_id == self.root_run_id:
            return ROOT_LANE
        return run_id

    def resolve_lane(self, run_id: Optional[str], parent_run_id: Optional[str]) -> Optional[str]:
        """Make the chunk's lane current, learning the top-level run id on the way."""
        if parent_run_id is None and run_id is not None and self.root_run_id is None:
            self.root_run_id = run_id
        self.current_lane = self.lane_for(run_id, parent_run_id)
        return self.current_lane

    def delegating_lane_for(
        self, parent_run_id: Optional[str], member_id: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """The lane that delegated to a subagent, and the call it delegated through.

        The call is only ever looked for in the lane reported beside it, so what
        a subagent is announced with comes from the run that really delegated to
        it and from nowhere else. When the delegating lane cannot be named, no
        call is reported either: the delegating run's own open calls are not
        this run's, and searching the top-level entity's instead would hand a
        grandchild the leader's call, the leader's parent message, and the
        leader's task text as its own description.

        A lane goes unnamed for two reasons, and neither leaves a link behind.
        One is a lane this stream has not announced: a parent link is resolved
        by the client against a lane it was told about, so a grandchild whose
        first event outruns its parent's is placed directly under the run rather
        than pointed at a lane the client cannot follow. The other is a lane
        whose terminal has already gone out, which delegates nothing more:
        naming it would hand the client a child that resolves inside a lane it
        has already closed.
        """
        # A chunk reporting no parent at all, and one whose parent is the run
        # this stream learned as the root, are both the top-level entity's work.
        if parent_run_id is None or parent_run_id == self.root_run_id:
            return ROOT_LANE, self.find_delegation_call(ROOT_LANE, member_id)
        if parent_run_id in self.closed_subagents or parent_run_id not in self.announced_subagents:
            return None, None
        return parent_run_id, self.find_delegation_call(parent_run_id, member_id)

    def record_open_tool_call(
        self, tool_call_id: str, tool_name: Optional[str], tool_args: Any, parent_message_id: str
    ) -> None:
        # Name and arguments reach here straight off the model, so anything at all
        # can arrive. Only a mapping of arguments is kept, which is all a
        # delegation lookup reads.
        self.open_tool_calls.setdefault(self.current_lane, {})[tool_call_id] = OpenToolCall(
            name=str(tool_name) if tool_name else "",
            args=dict(tool_args) if isinstance(tool_args, Mapping) else {},
            parent_message_id=parent_message_id,
        )

    def find_delegation_call(self, parent_lane: Optional[str], member_id: Optional[str]) -> Optional[str]:
        """Tool call id of the delegation that spawned a subagent, when identifiable.

        Only a call still open in the delegating lane, whose tool name is one the
        framework delegates through, and whose ``member_id`` argument names this
        member. Naming the member is what makes such a call evidence: an open
        delegation to somebody else would otherwise hand this lane another
        member's parent call, task text and parent message. Two open delegations
        naming the same member point at no single call, so nothing is reported
        rather than one of them picked. The broadcast tools name no member at
        all, so a member one of those spawned gets no link rather than the
        leader's own call.
        """
        if not member_id:
            return None
        named = [
            tool_call_id
            for tool_call_id, entry in (self.open_tool_calls.get(parent_lane) or {}).items()
            if entry.is_delegation and entry.args.get("member_id") == member_id
        ]
        return named[0] if len(named) == 1 else None

    def find_member_delegation(self, member_id: Optional[str]) -> Optional[Tuple[Optional[str], str]]:
        """The lane that delegated to a member and the call it delegated through.

        A member run pauses inside the call that spawned it, so that call is
        still open and the lane holding it is the member's parent, however deep
        the run that reported the pause sits. Only a delegation naming this
        member counts, and only while exactly one is open: two delegations
        naming the same member, in one lane or in two, point at no single
        parent, so nothing is reported rather than guessed.

        A lane whose own terminal has already gone out is not searched. Whatever
        it still holds open, that lane can no longer be named as a parent: its
        terminal would then precede a child's, which is a lane the client has
        already closed.
        """
        if not member_id:
            return None
        matches = [
            (lane, tool_call_id)
            for lane, calls in self.open_tool_calls.items()
            if lane not in self.closed_subagents
            for tool_call_id, entry in calls.items()
            if entry.is_delegation and entry.args.get("member_id") == member_id
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def _delegation_entry(self, parent_lane: Optional[str], tool_call_id: Optional[str]) -> Optional[OpenToolCall]:
        if tool_call_id is None:
            return None
        return (self.open_tool_calls.get(parent_lane) or {}).get(tool_call_id)

    def delegation_task(self, parent_lane: Optional[str], tool_call_id: Optional[str]) -> Optional[str]:
        """The task text the delegation call carried, which describes the subagent's work.

        Only a delegation's own arguments are read, so a ``task`` belonging to
        some other tool can never become a subagent's description. The tasks-mode
        delegations carry a task id instead of task text, so a subagent spawned by
        one has no description rather than an invented one.
        """
        entry = self._delegation_entry(parent_lane, tool_call_id)
        task = entry.args.get("task") if entry is not None and entry.is_delegation else None
        return task if isinstance(task, str) and task else None

    def delegation_parent_message_id(self, parent_lane: Optional[str], tool_call_id: Optional[str]) -> Optional[str]:
        entry = self._delegation_entry(parent_lane, tool_call_id)
        if entry is None or not entry.is_delegation:
            return None
        return entry.parent_message_id or None

    def open_subagent(self, subagent_run_id: str, name: str, parent_lane: Optional[str]) -> None:
        subagent = Subagent(name=name, parent_lane=parent_lane)
        self.open_subagents[subagent_run_id] = subagent
        self.announced_subagents[subagent_run_id] = subagent

    def close_subagent(self, subagent_run_id: str) -> None:
        self.open_subagents.pop(subagent_run_id, None)
        self.closed_subagents.add(subagent_run_id)

    def ancestor_lanes(self, lane_key: Optional[str]) -> List[str]:
        """The announced subagent lanes above a lane, nearest first.

        The walk stops on a lane it has already passed, so a parent chain that
        somehow closes on itself ends the walk instead of looping.
        """
        ancestors: List[str] = []
        seen = {lane_key}
        entry = self.announced_subagents.get(lane_key) if lane_key is not None else None
        parent = entry.parent_lane if entry else None
        while parent is not None and parent not in seen:
            ancestors.append(parent)
            seen.add(parent)
            entry = self.announced_subagents.get(parent)
            parent = entry.parent_lane if entry else None
        return ancestors

    def lane_depth(self, lane_key: Optional[str]) -> int:
        """How many announced subagent lanes sit above a lane.

        A direct child of the top-level entity has none above it, so it reports 0,
        the same as the root lane. The value exists to order children before
        parents, not to measure how deep a delegation went.
        """
        return len(self.ancestor_lanes(lane_key))

    def subagents_deepest_first(self) -> List[str]:
        """Open subagents ordered so a child's terminal precedes its parent's."""
        return sorted(self.open_subagents, key=self.lane_depth, reverse=True)

    def lanes_deepest_first(self) -> List[Optional[str]]:
        """Every lane the stream created, children before parents, then the root.

        The root lane is always last whether or not it holds anything, so a
        caller sweeping these closes nothing there rather than skipping it.

        Every lane the mapper opens a tool call through already has a record here,
        so the sweep over open tool calls adds nothing in practice; it is kept so
        that the guarantee no tool call reaches the run terminal unended does not
        rest on its lane happening to hold a span of its own. Ordering is taken
        from insertion order rather than from the tool call sets, so lanes of equal
        depth keep the order the stream created them in.
        """
        keys: List[Optional[str]] = list(self.lanes)
        seen = set(keys)
        for tool_call_id, lane_key in self.tool_call_lanes.items():
            if tool_call_id in self.active_tool_call_ids and lane_key not in seen:
                seen.add(lane_key)
                keys.append(lane_key)
        subagent_lanes = [key for key in keys if key is not ROOT_LANE]
        return [*sorted(subagent_lanes, key=self.lane_depth, reverse=True), ROOT_LANE]

    # --- State deltas --------------------------------------------------------

    def set_state_snapshot(self, state: Dict[str, Any]) -> None:
        self._last_snapshot = copy.deepcopy(state)

    def compute_state_delta(self, current_state: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        if self._last_snapshot is None:
            return None
        try:
            import jsonpatch

            patch = jsonpatch.make_patch(self._last_snapshot, current_state)
            ops = patch.patch
            if not ops:
                return None
            return ops
        except Exception as e:
            log_warning(f"Failed to compute state delta: {e}")
            return None
