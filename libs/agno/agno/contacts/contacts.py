"""Contacts: let an Agent message other user-built agents and teams to get work done.

A ``Contact`` wraps an existing entity — a local ``Agent`` or ``Team``, or a
``RemoteAgent``/``RemoteTeam`` on another AgentOS — together with instructions on
when to contact it. Attach contacts via ``Agent(contacts=[...])``; the agent then
gets a ``message_contact`` tool built per run so its description enumerates the
real contact list.

A contacted entity runs like a child run inside the parent's session, exactly like
team member delegation: its events stream nested into the parent run (tagged with
``parent_run_id`` and the contact's own name), while the final output becomes the
tool result the parent model sees. Contacts keep their own persistence behavior;
the parent's context stays clean because runs with a ``parent_run_id`` are dropped
from session history.
"""

from copy import copy
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, Optional, Union
from uuid import uuid4

from agno.exceptions import RunCancelledException
from agno.run.agent import RunCancelledEvent as AgentRunCancelledEvent
from agno.run.agent import RunCompletedEvent as AgentRunCompletedEvent
from agno.run.agent import RunContentEvent, RunOutput, RunOutputEvent
from agno.run.agent import RunErrorEvent as AgentRunErrorEvent
from agno.run.base import RunContext, RunStatus
from agno.run.cancel import araise_if_cancelled, aregister_member_run, raise_if_cancelled, register_member_run
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error
from agno.utils.merge_dict import merge_dictionaries

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.agent.remote import RemoteAgent
    from agno.team.remote import RemoteTeam
    from agno.team.team import Team

# Terminal events emitted by a contacted entity; forwarded even when draining after cancel.
_TERMINAL_EVENT_TYPES = (
    AgentRunCancelledEvent,
    AgentRunCompletedEvent,
    AgentRunErrorEvent,
    TeamRunCancelledEvent,
    TeamRunCompletedEvent,
    TeamRunErrorEvent,
)

# Content events the model layer accumulates into the tool result; if any of these
# streamed, the final content is already part of the tool result and must not be
# yielded again.
_CONTENT_EVENT_TYPES = (RunContentEvent, TeamRunContentEvent)

DEFAULT_INSTRUCTIONS = """You have contacts: other agents and teams you can message to get work done.

- Use the message_contact tool when a task belongs to one of your contacts, per the guidance in the contact list.
- Contacts do not see your conversation. Write self-contained messages: include all relevant context and state the exact output you expect back.
- To work with multiple contacts at once, call message_contact multiple times in a single response.
- Handle follow-up work yourself unless it clearly belongs to a contact."""

_MESSAGE_CONTACT_DESCRIPTION = """Message one of your contacts to get a task done and return its result.

The contact runs the task and its answer is returned to you. Message the same contact again for follow-ups; it keeps its own history.

{contacts_overview}"""


class Contact:
    """A messageable wrapper around an existing agent or team.

    Wraps exactly one target entity together with instructions on when to contact
    it. Pass contacts to an agent via ``Agent(contacts=[...])``.

    Example:
        >>> news_reporter = Contact(
        ...     agent=RemoteAgent(base_url="http://localhost:7778", agent_id="news-agent"),
        ...     instructions="Contact to get the latest news",
        ... )
        >>> agent = Agent(model=..., contacts=[news_reporter])

    Args:
        agent: The agent to contact. A local ``Agent`` or a ``RemoteAgent``.
            Mutually exclusive with ``team``.
        team: The team to contact. A local ``Team`` or a ``RemoteTeam``.
            Mutually exclusive with ``agent``.
        instructions: When and why to contact this entity. Shown to the model in
            the ``message_contact`` tool description. Falls back to the entity's
            own description when not set.
        name: Optional key override used to address this contact in tool calls.
            Defaults to the entity's id.
    """

    def __init__(
        self,
        agent: Optional[Union["Agent", "RemoteAgent"]] = None,
        team: Optional[Union["Team", "RemoteTeam"]] = None,
        instructions: Optional[str] = None,
        name: Optional[str] = None,
    ):
        if (agent is None) == (team is None):
            raise ValueError("Contact requires exactly one of agent= or team=")

        self.agent = agent
        self.team = team
        self.instructions = instructions
        self.name = name

    @property
    def entity(self) -> Union["Agent", "RemoteAgent", "Team", "RemoteTeam"]:
        """The wrapped entity."""
        return self.agent if self.agent is not None else self.team  # type: ignore[return-value]

    @property
    def is_remote(self) -> bool:
        """Whether the wrapped entity lives on a remote AgentOS."""
        from agno.remote.base import BaseRemote

        return isinstance(self.entity, BaseRemote)

    @property
    def kind(self) -> str:
        """Human-readable kind of the wrapped entity."""
        base = "agent" if self.agent is not None else "team"
        return f"remote {base}" if self.is_remote else base

    @property
    def key(self) -> str:
        """The key the model uses to address this contact."""
        if self.name:
            return self.name
        entity = self.entity
        if entity.id is None:
            # Local entities auto-generate their id at run init; trigger the same here
            set_id = getattr(entity, "set_id", None)
            if set_id is not None:
                set_id()
        key = entity.id or entity.name
        if key is None:
            raise ValueError("Contact target must have an id or name, or pass name= to Contact")
        return key

    @property
    def display_name(self) -> str:
        """Display name for listings; falls back to the key."""
        return self.entity.name or self.key


def _resolve_contacts(agent: "Agent") -> Dict[str, Contact]:
    """Map contact key -> Contact, preserving order; duplicate keys are an error."""
    resolved: Dict[str, Contact] = {}
    for contact in agent.contacts or []:
        key = contact.key
        if key in resolved:
            raise ValueError(f"Duplicate contact key '{key}'; use name= on Contact to disambiguate")
        resolved[key] = contact
    return resolved


def _contacts_overview(contacts: Dict[str, Contact]) -> str:
    """Render the 'Available contacts' block shown in the tool description."""
    lines = []
    for key, contact in contacts.items():
        line = f"- {key} ({contact.kind}): {contact.display_name}"
        guidance = contact.instructions or contact.entity.description
        if guidance:
            line = f"{line} - {guidance}"
        lines.append(line)
    return "Available contacts:\n" + "\n".join(lines)


def _derived_session_id(run_context: RunContext, contact: Contact) -> str:
    """Session id for a contacted entity's child run.

    Agent contacts share the parent's session (like team members). Team contacts
    get a session id derived from the parent's: the sessions table is keyed on
    session_id alone, so a TeamSession reusing the parent's id would overwrite
    the parent's agent session row. The derived id is stable per contact, so
    repeated contacts in the same parent session keep their history.
    """
    if contact.agent is not None:
        return run_context.session_id
    return f"{run_context.session_id}-contact-{contact.key}"


def _cancel_child_run(child_run_id: str) -> None:
    """Cancel a local child run, cascading through its own children.

    Lazy import to avoid a circular dependency with ``agno.team._run``.
    """
    from agno.team._run import cancel_run as _cascading_cancel_run

    _cascading_cancel_run(child_run_id)


async def _acancel_child_run(child_run_id: str) -> None:
    """Async variant of :func:`_cancel_child_run`."""
    from agno.team._run import acancel_run as _acascading_cancel_run

    await _acascading_cancel_run(child_run_id)


def _final_content_string(child_output: Optional[Union[RunOutput, TeamRunOutput]], fallback_content: Any) -> str:
    """Render the contacted entity's final content as the tool result string."""
    if child_output is not None:
        return child_output.get_content_as_string()
    if fallback_content is None:
        return "No response from the contact."
    if isinstance(fallback_content, str):
        return fallback_content
    from pydantic import BaseModel

    if isinstance(fallback_content, BaseModel):
        return fallback_content.model_dump_json(indent=2)
    import json

    return json.dumps(fallback_content, indent=2, ensure_ascii=False)


def get_message_contact_function(agent: "Agent", run_context: RunContext, async_mode: bool = False) -> Function:
    """Build the per-run ``message_contact`` tool for an agent with contacts.

    Built per run (like team delegation tools) so the description enumerates the
    live contact list. The entrypoint is a generator: the contacted entity's
    events are yielded upward — the model layer streams them into the parent run
    and accumulates content events into the tool result.

    Args:
        agent: The parent agent owning the contacts.
        run_context: The parent run's context.
        async_mode: Pick the async generator entrypoint (parallel contacts).

    Returns:
        Function: The ``message_contact`` tool.
    """
    contacts = _resolve_contacts(agent)
    overview = _contacts_overview(contacts)

    def _not_found_message(contact_key: str) -> str:
        return f"Contact '{contact_key}' not found. Choose from the available contacts:\n\n{overview}"

    def _run_kwargs(
        contact: Contact, task: str, session_state_copy: Optional[Dict[str, Any]], child_run_id: str
    ) -> Dict[str, Any]:
        """Kwargs for the contacted entity's run.

        ``run_id`` works for remote entities too: the RemoteAccess endpoints
        forward extra form fields into the server-side run, so the child runs
        under our pre-generated id and can be cancelled with it.
        ``yield_run_output`` is local-only: the server-side SSE streamer drops
        the RunOutput accumulator chunk, so remotely the final content comes
        from the terminal RunCompletedEvent instead.
        """
        kwargs: Dict[str, Any] = dict(
            input=task,
            user_id=run_context.user_id,
            session_id=_derived_session_id(run_context, contact),
            session_state=session_state_copy,
            stream=True,
            stream_events=True,
            run_id=child_run_id,
            dependencies=run_context.dependencies,
            metadata=run_context.metadata,
        )
        if not contact.is_remote:
            kwargs["yield_run_output"] = True
        return kwargs

    def message_contact(contact: str, task: str) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Message a contact to get a task done.

        Args:
            contact (str): The key of the contact to message, from the available contacts list.
            task (str): A complete, self-contained task message for the contact, including all
                relevant context and the exact output you expect back.
        """
        target = contacts.get(contact)
        if target is None:
            yield _not_found_message(contact)
            return

        if target.is_remote:
            yield (
                f"Contact '{contact}' is a remote contact and can only be messaged in an async run. "
                "Run the agent with arun to message remote contacts."
            )
            return

        log_debug(f"Messaging contact '{contact}' ({target.kind})")
        session_state_copy = copy(run_context.session_state)
        child_run_id = str(uuid4())
        register_member_run(run_context.run_id, child_run_id)

        child_output: Optional[Union[RunOutput, TeamRunOutput]] = None
        fallback_content = None
        streamed_content = False
        draining_after_cancel = False
        try:
            event_stream = target.entity.run(**_run_kwargs(target, task, session_state_copy, child_run_id))  # type: ignore[union-attr]
            for event in event_stream:
                # Do NOT break out of the loop, the iterator needs to exit properly
                if isinstance(event, (RunOutput, TeamRunOutput)):
                    child_output = event
                    continue  # Don't yield the final output, only yield events

                if isinstance(event, _TERMINAL_EVENT_TYPES):
                    event.parent_run_id = event.parent_run_id or run_context.run_id
                    if isinstance(event, (AgentRunCompletedEvent, TeamRunCompletedEvent)):
                        fallback_content = event.content
                    yield event
                    if event.is_cancelled:
                        draining_after_cancel = True
                    continue

                if draining_after_cancel:
                    continue

                event.parent_run_id = event.parent_run_id or run_context.run_id
                if isinstance(event, _CONTENT_EVENT_TYPES) and event.content:
                    streamed_content = True
                yield event

                try:
                    raise_if_cancelled(run_context.run_id)
                except RunCancelledException:
                    _cancel_child_run(child_run_id)
                    draining_after_cancel = True
                    continue
            if draining_after_cancel:
                raise RunCancelledException("")
        except RunCancelledException:
            raise
        except Exception as e:
            log_error(f"Contact '{contact}' failed: {e}")
            yield f"Contact task failed: {e}"
            return

        if run_context.session_state is not None and session_state_copy is not None:
            merge_dictionaries(run_context.session_state, session_state_copy)

        if child_output is not None and child_output.status == RunStatus.error:
            yield f"Contact task failed: {child_output.content}"
        elif child_output is not None and getattr(child_output, "is_paused", False):
            yield f"Contact '{contact}' requires human input before continuing."
        elif not streamed_content:
            yield _final_content_string(child_output, fallback_content)

    async def amessage_contact(
        contact: str, task: str
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, str]]:
        """Message a contact to get a task done.

        Args:
            contact (str): The key of the contact to message, from the available contacts list.
            task (str): A complete, self-contained task message for the contact, including all
                relevant context and the exact output you expect back.
        """
        target = contacts.get(contact)
        if target is None:
            yield _not_found_message(contact)
            return

        log_debug(f"Messaging contact '{contact}' ({target.kind})")
        session_state_copy = copy(run_context.session_state)
        child_run_id = str(uuid4())
        await aregister_member_run(run_context.run_id, child_run_id)

        child_output: Optional[Union[RunOutput, TeamRunOutput]] = None
        fallback_content = None
        streamed_content = False
        draining_after_cancel = False
        try:
            event_stream = target.entity.arun(**_run_kwargs(target, task, session_state_copy, child_run_id))  # type: ignore[union-attr]
            async for event in event_stream:
                # Do NOT break out of the loop, the AsyncIterator needs to exit properly
                if isinstance(event, (RunOutput, TeamRunOutput)):
                    child_output = event
                    continue  # Don't yield the final output, only yield events

                if isinstance(event, _TERMINAL_EVENT_TYPES):
                    event.parent_run_id = event.parent_run_id or run_context.run_id
                    if isinstance(event, (AgentRunCompletedEvent, TeamRunCompletedEvent)):
                        fallback_content = event.content
                    yield event
                    if event.is_cancelled:
                        draining_after_cancel = True
                    continue

                if draining_after_cancel:
                    continue

                event.parent_run_id = event.parent_run_id or run_context.run_id
                if isinstance(event, _CONTENT_EVENT_TYPES) and event.content:
                    streamed_content = True
                yield event

                try:
                    await araise_if_cancelled(run_context.run_id)
                except RunCancelledException:
                    if target.is_remote:
                        await target.entity.acancel_run(child_run_id)  # type: ignore[union-attr]
                    else:
                        await _acancel_child_run(child_run_id)
                    draining_after_cancel = True
                    continue
            if draining_after_cancel:
                raise RunCancelledException("")
        except RunCancelledException:
            raise
        except Exception as e:
            log_error(f"Contact '{contact}' failed: {e}")
            yield f"Contact task failed: {e}"
            return

        if not target.is_remote and run_context.session_state is not None and session_state_copy is not None:
            merge_dictionaries(run_context.session_state, session_state_copy)

        if child_output is not None and child_output.status == RunStatus.error:
            yield f"Contact task failed: {child_output.content}"
        elif child_output is not None and getattr(child_output, "is_paused", False):
            yield f"Contact '{contact}' requires human input before continuing."
        elif not streamed_content:
            yield _final_content_string(child_output, fallback_content)

    return Function(
        name="message_contact",
        entrypoint=amessage_contact if async_mode else message_contact,
        description=_MESSAGE_CONTACT_DESCRIPTION.format(contacts_overview=overview),
        instructions=DEFAULT_INSTRUCTIONS,
        add_instructions=True,
    )
