"""V1-compatible stubs for TeamMemory and TeamRun classes (V2 moved memory structure)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class TeamMemory:
    """V1-compatible stub for TeamMemory.

    In V2, team memory is managed via MemoryManager and UserMemory in agno.memory module.
    This stub provides V1 interface compatibility.
    """

    team_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamRun:
    """V1-compatible stub for TeamRun.

    In V2, team runs are tracked via RunContext and Session objects.
    This stub provides V1 dataclass interface compatibility.
    """

    run_id: Optional[str] = None
    session_id: Optional[str] = None
    team_id: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
