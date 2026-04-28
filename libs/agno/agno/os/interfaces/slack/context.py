from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from agno.tools.slack import SlackTools


# Immutable context for route-wide dependencies. Passed explicitly to handlers
# instead of relying on closure capture. Request-scoped values (channel, thread_ts,
# run_id) stay as explicit params.
@dataclass(frozen=True)
class SlackRouteContext:
    entity: Any
    entity_id: str
    entity_name: str
    entity_type: Literal["agent", "team", "workflow"]
    slack_tools: "SlackTools"
    create_client: Callable[[], Any]
    loading_text: str
    loading_messages: Optional[List[str]]
    task_display_mode: str
    buffer_size: int
    resolve_user_identity: bool
    hitl_enabled: bool
    suggested_prompts: Optional[List[Dict[str, str]]]
    max_file_size: int
    run_context_provider: Optional[Callable[..., Any]]

    def session_id(self, thread_ts: str) -> str:
        return f"{self.entity_id}:{thread_ts}"
