from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.models.message import Message
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.run.messages import RunMessages
    from agno.run.team import TeamRunOutput
    from agno.session import AgentSession, TeamSession
    from agno.tools.function import Function


@dataclass
class PreparedAgentModelRequest:
    """Prepared Agent model request data without invoking the model."""

    run_response: "RunOutput"
    run_context: "RunContext"
    session: "AgentSession"
    run_messages: "RunMessages"
    tools: List[Union["Function", Dict[str, Any]]]
    tool_instructions: List[str]
    response_format: Optional[Union[Dict[str, Any], Type[BaseModel]]] = None

    @property
    def messages(self) -> List["Message"]:
        return self.run_messages.messages

    @property
    def system_message(self) -> Optional["Message"]:
        return self.run_messages.system_message

    @property
    def user_message(self) -> Optional["Message"]:
        return self.run_messages.user_message


@dataclass
class PreparedTeamModelRequest:
    """Prepared Team model request data without invoking the model."""

    run_response: "TeamRunOutput"
    run_context: "RunContext"
    session: "TeamSession"
    run_messages: "RunMessages"
    tools: List[Union["Function", Dict[str, Any]]]
    tool_instructions: List[str]
    response_format: Optional[Union[Dict[str, Any], Type[BaseModel]]] = None

    @property
    def messages(self) -> List["Message"]:
        return self.run_messages.messages

    @property
    def system_message(self) -> Optional["Message"]:
        return self.run_messages.system_message

    @property
    def user_message(self) -> Optional["Message"]:
        return self.run_messages.user_message
