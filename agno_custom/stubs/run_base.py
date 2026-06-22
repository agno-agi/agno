"""V1-compatible stubs for run management classes (V2 restructured run handling)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BaseRunResponseEvent:
    """V1-compatible base class for run response events.

    In V2, streaming events use a different model structure via agno.run.base.RunContext
    and event handling is done differently.
    This stub provides V1 interface compatibility.
    """

    event_type: str = ""
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResponseExtraData:
    """V1-compatible dataclass for run metadata.

    Collects extra metadata and metrics for run responses.
    In V2, this is handled through RunMetrics and RunContext.
    """

    run_id: Optional[str] = None
    session_id: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
