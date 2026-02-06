from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

if TYPE_CHECKING:
    from pydantic import BaseModel

    from agno.filters import FilterExpr


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
