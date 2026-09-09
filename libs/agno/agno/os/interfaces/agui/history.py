import uuid
from typing import List, Optional, Tuple, Union

from ag_ui.core import EventType, MessagesSnapshotEvent, RunAgentInput
from ag_ui.core.types import AssistantMessage, ToolMessage, UserMessage
from ag_ui.core.types import Message as AGUIMessage

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agui.input import extract_user_input
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team import Team
from agno.team.remote import RemoteTeam
from agno.utils.log import log_warning

Entity = Union[Agent, RemoteAgent, Team, RemoteTeam]
LocalEntity = Union[Agent, Team]
Session = Union[AgentSession, TeamSession]


def _history_messages(session: Session) -> List[AGUIMessage]:
    messages: List[AGUIMessage] = []
    for message in session.get_chat_history():
        content = message.get_content_string()
        if not content:
            continue
        message_id = str(message.id) if message.id is not None else str(uuid.uuid4())
        if message.role == "user":
            messages.append(UserMessage(id=message_id, content=content))
        elif message.role == "assistant":
            messages.append(AssistantMessage(id=message_id, content=content))
    return messages


def _payload_messages(run_input: RunAgentInput) -> Tuple[List[AGUIMessage], List[AGUIMessage]]:
    head: List[AGUIMessage] = [
        message for message in run_input.messages or [] if message.role in ("system", "developer")
    ]
    user_input = extract_user_input(run_input.messages or [])
    tail: List[AGUIMessage] = []
    if user_input:
        tail.append(UserMessage(id=str(uuid.uuid4()), content=user_input))
    return head, tail


def _snapshot_from_session(session: Session, run_input: RunAgentInput) -> Optional[MessagesSnapshotEvent]:
    history = _history_messages(session)
    if not history:
        return None
    head, tail = _payload_messages(run_input)
    return MessagesSnapshotEvent(type=EventType.MESSAGES_SNAPSHOT, messages=head + history + tail)


def _local_entity(entity: Entity, run_input: RunAgentInput, tool_messages: List[ToolMessage]) -> Optional[LocalEntity]:
    if tool_messages:
        return None
    if any(message.role == "assistant" for message in run_input.messages or []):
        return None
    if not isinstance(entity, (Agent, Team)) or entity.db is None:
        return None
    return entity


def session_history_snapshot(
    entity: Entity,
    run_input: RunAgentInput,
    tool_messages: List[ToolMessage],
    user_id: Optional[str] = None,
) -> Optional[MessagesSnapshotEvent]:
    try:
        local_entity = _local_entity(entity, run_input, tool_messages)
        if local_entity is None:
            return None
        session = local_entity.get_session(session_id=run_input.thread_id, user_id=user_id)
        if not isinstance(session, (AgentSession, TeamSession)):
            return None
        return _snapshot_from_session(session, run_input)
    except Exception as e:
        log_warning(f"Failed to build AG-UI messages snapshot for session {run_input.thread_id}: {e}")
        return None


async def asession_history_snapshot(
    entity: Entity,
    run_input: RunAgentInput,
    tool_messages: List[ToolMessage],
    user_id: Optional[str] = None,
) -> Optional[MessagesSnapshotEvent]:
    try:
        local_entity = _local_entity(entity, run_input, tool_messages)
        if local_entity is None:
            return None
        session = await local_entity.aget_session(session_id=run_input.thread_id, user_id=user_id)
        if not isinstance(session, (AgentSession, TeamSession)):
            return None
        return _snapshot_from_session(session, run_input)
    except Exception as e:
        log_warning(f"Failed to build AG-UI messages snapshot for session {run_input.thread_id}: {e}")
        return None
