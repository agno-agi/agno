from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TeamRun:
    """V1 compatibility stub for team run"""
    response: Optional[Any] = None
    message: Optional[Any] = None
    messages: Optional[List[Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def model_validate(self, data: Dict[str, Any]) -> "TeamRun":
        """Validate and create TeamRun from dict"""
        return TeamRun(**data)


@dataclass
class TeamMemory:
    """V1 compatibility stub for team memory"""
    runs: List[TeamRun] = field(default_factory=list)
    messages: List[Any] = field(default_factory=list)
    create_user_memories: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def add_run(self, run: TeamRun) -> None:
        """Add a TeamRun to memory"""
        self.runs.append(run)

    def add_message(self, message: Any) -> None:
        """Add a message to memory"""
        self.messages.append(message)

    def get_runs(self) -> List[TeamRun]:
        """Get all runs"""
        return self.runs

    def get_messages(self) -> List[Any]:
        """Get all messages"""
        return self.messages
