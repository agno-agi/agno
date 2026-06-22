from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentRun:
    """V1 compatibility stub for agent run"""
    response: Optional[Any] = None
    message: Optional[Any] = None
    messages: Optional[List[Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def model_validate(self, data: Dict[str, Any]) -> "AgentRun":
        """Validate and create AgentRun from dict"""
        return AgentRun(**data)


@dataclass
class AgentMemory:
    """V1 compatibility stub for agent memory"""
    runs: List[AgentRun] = field(default_factory=list)
    messages: List[Any] = field(default_factory=list)
    create_user_memories: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def add_run(self, run: AgentRun) -> None:
        """Add an AgentRun to memory"""
        self.runs.append(run)

    def add_message(self, message: Any) -> None:
        """Add a message to memory"""
        self.messages.append(message)

    def get_runs(self) -> List[AgentRun]:
        """Get all runs"""
        return self.runs

    def get_messages(self) -> List[Any]:
        """Get all messages"""
        return self.messages
