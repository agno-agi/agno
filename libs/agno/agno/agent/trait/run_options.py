from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

if TYPE_CHECKING:
    from pydantic import BaseModel

    from agno.filters import FilterExpr


class ReplayMode(str, Enum):
    OFF = "off"
    ERRORS_ONLY = "errors_only"
    SAMPLED = "sampled"
    FULL = "full"


@dataclass(frozen=True)
class ResolvedRunOptions:
    stream: bool
    stream_events: bool
    yield_run_output: bool
    add_history_to_context: bool
    add_dependencies_to_context: bool
    add_session_state_to_context: bool
    dependencies: Optional[Dict[str, Any]]
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]]
    metadata: Optional[Dict[str, Any]]
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]]
    replay_mode: ReplayMode
    replay_sample_rate: float
    replay_max_payload_bytes: int
    replay_max_message_chars: int
    replay_compress_payload: bool

    @property
    def replay_enabled(self) -> bool:
        return self.replay_mode != ReplayMode.OFF
