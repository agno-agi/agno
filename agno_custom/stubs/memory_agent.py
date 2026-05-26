"""V1-compatible stubs for AgentMemory and AgentRun classes (V2 moved memory structure)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class AgentMemory:
    """V1-compatible stub for AgentMemory.

    In V2, memory is managed via MemoryManager and UserMemory in agno.memory module.
    This stub provides V1 interface compatibility.
    """

    agent_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRun:
    """V1-compatible stub for AgentRun.

    In V2, runs are tracked via RunContext and Session objects.
    This stub provides V1 dataclass interface compatibility.
    """

    run_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
