"""Declaring a trigger: when this happens, start a run of that target with this input."""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Tuple, Union

# Called with the event before the run. False skips the event; a string replaces the input.
PrepareFunction = Callable[[Any], Union[None, bool, str, Awaitable[Union[None, bool, str]]]]
# Called with the event and how its run ended.
OnCompleteFunction = Callable[[Any, "TriggerRun"], Union[None, Awaitable[None]]]


@dataclass(frozen=True)
class Schedule:
    """A trigger's event when it is a time: a cron expression, read in a timezone."""

    cron: str
    timezone: str = "UTC"


@dataclass(frozen=True)
class Events:
    """Event kinds from one source, with that source's filter. A source builds it: ``github.on("issues.opened")``."""

    source_id: str
    kinds: Tuple[str, ...]
    filters: Dict[str, Any] = field(default_factory=dict)
    # The source object, so AgentOS can check it is one of its interfaces.
    source: Any = field(default=None, repr=False, compare=False)


@dataclass
class TriggerRun:
    """How the run a trigger started ended. Passed to ``on_complete``."""

    # success, failed, paused or cancelled
    status: str
    trigger_name: str
    event_id: str
    attempt: int = 1
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    # The run's content.
    output: Optional[Any] = None
    error: Optional[str] = None


class Trigger:
    """Start a run of an agent, team or workflow when an event arrives or a schedule is due.

    The run's message is ``input`` followed by the event, marked as information from outside.
    A trigger declared in code has no owner and fires as the system.
    """

    def __init__(
        self,
        name: str,
        on: Union[Events, Schedule],
        input: str,
        agent: Optional[Any] = None,
        team: Optional[Any] = None,
        workflow: Optional[Any] = None,
        continue_on: Optional[Union[str, Sequence[str]]] = None,
        prepare: Optional[PrepareFunction] = None,
        on_complete: Optional[OnCompleteFunction] = None,
        description: Optional[str] = None,
        timeout_seconds: int = 3600,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
    ):
        """
        Args:
            name: Unique among the triggers of one AgentOS. A trigger keeps its history under this name.
            on: What starts the run: events from a source, e.g. ``github.on("issues.opened")``, or a ``Schedule``.
            input: The instruction for the run. The event is added after it.
            agent: The agent to run, as an object or an id. Give exactly one of agent, team and workflow.
            team: The team to run, as an object or an id.
            workflow: The workflow to run, as an object or an id.
            continue_on: Event kinds that only continue a conversation this trigger already started, e.g.
                "issue_comment.created": a reply on an issue the trigger handled becomes a new turn in the
                same session, and a comment on any other issue starts nothing.
            prepare: Called with the event before the run; may be async. Returning False skips the event;
                returning a string replaces the input for this event.
            on_complete: Called with the event and a ``TriggerRun`` when the run ends; may be async.
                Raising does not change the run's status.
            description: What the trigger is for.
            timeout_seconds: How long to wait for a run before recording it as failed.
            max_retries: How many times to run again after a failed run.
            retry_delay_seconds: How long to wait between attempts.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("A trigger needs a name")
        if not isinstance(on, (Events, Schedule)):
            raise ValueError(
                f"Trigger '{name}': on= takes events from a source, e.g. github.on(\"issues.opened\"), or a Schedule"
            )
        if not isinstance(input, str) or not input.strip():
            raise ValueError(f"Trigger '{name}' needs an input: the instruction for the run")
        targets = [(kind, value) for kind, value in (("agent", agent), ("team", team), ("workflow", workflow)) if value]
        if len(targets) != 1:
            raise ValueError(f"Trigger '{name}' needs exactly one of agent=, team= and workflow=")
        if isinstance(continue_on, str):
            continue_on = [continue_on]
        if isinstance(on, Schedule) and (continue_on or prepare is not None or on_complete is not None):
            raise ValueError(
                f"Trigger '{name}': continue_on, prepare and on_complete work on events; a schedule has none"
            )
        if isinstance(on, Events) and not on.kinds:
            raise ValueError(f"Trigger '{name}' names no event kind")
        if timeout_seconds <= 0 or max_retries < 0 or retry_delay_seconds < 0:
            raise ValueError(f"Trigger '{name}': timeout_seconds must be positive, and retries cannot be negative")

        self.name = name.strip()
        self.on = on
        self.input = input
        self.target_type, self.target = targets[0]
        self.continue_on = list(continue_on or [])
        self.prepare = prepare
        self.on_complete = on_complete
        self.description = description
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    @property
    def is_schedule(self) -> bool:
        return isinstance(self.on, Schedule)

    @property
    def target_id(self) -> str:
        """The id of the agent, team or workflow this trigger runs."""
        if isinstance(self.target, str):
            return self.target
        target_id = getattr(self.target, "id", None)
        if not target_id:
            raise ValueError(f"Trigger '{self.name}': its {self.target_type} has no id; give it one, or name it by id")
        return str(target_id)

    def __repr__(self) -> str:
        return f"Trigger(name={self.name!r}, on={self.on!r}, {self.target_type}={getattr(self.target, 'id', self.target)!r})"
