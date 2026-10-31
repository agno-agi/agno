"""Configuration for OS Manager."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from agno.offload import ResultStore

from agno.registry._reserved import MANAGER_TEAM_ID

MANAGER_TEAM_NAME = "OS Manager"


@dataclass
class OSManager:
    """Configure the OS manager and its resources.

    When authorization is enforced, ordinary component run grants allow access.
    Protected tools check the caller's permissions during manager execution
    and delegated work. Ordinary agents retain their existing tool permissions.
    Direct Python calls and bound interfaces are trusted application entry points.

    Args:
        name: The manager team's display name.
        model: Model for the manager and its members. Uses the registry's first
            model if omitted. A model is required in one of these places.
        tools: Tools for the manager. These are not added to the registry.
        knowledge: Knowledge base the manager can search.
        learning: Learning machine for remembering users across sessions.
        root: Directory or WorkspaceContextProvider for Platform Manager to read.
            Default file exclusions apply. Extra exclusions are allowed; custom
            exemptions and allow_paths are not. Omit to disable source access.
        access_docs: Give OS Manager and Platform Manager access to the Agno documentation MCP
            server. Enabled by default. Connection failures are nonfatal; pass
            False to disable documentation access in offline deployments.
        offload_tool_results: Offload large tool results for the manager and its members.
            Enabled by default on SQLite and PostgreSQL. Pass False to disable or
            a ResultStore to customize its settings.
        instructions: Extra instructions for the manager.
        required_env: Environment variables to check during diagnostics.
        num_history_runs: Number of past runs to include in the manager's context.
        tool_call_limit: Maximum ordinary tool executions per coordinator run,
            including delegations. Defaults to 8; None disables the limit.
        member_tool_call_limit: Maximum ordinary tool executions per specialist
            invocation, including the Company Manager member when attached. Defaults to 24;
            None disables the limit. Each delegation has its own budget, not a
            shared run-wide budget. Offloaded-result read-back tools retain their
            existing exemption from both limits.
    """

    name: str = MANAGER_TEAM_NAME
    model: Optional[Any] = None
    tools: List[Any] = field(default_factory=list)
    knowledge: Optional[Any] = None
    learning: Optional[Any] = None
    root: Optional[Union[str, Path, Any]] = None
    access_docs: bool = True
    offload_tool_results: Optional[Union[bool, "ResultStore"]] = True
    instructions: Optional[str] = None
    required_env: Tuple[str, ...] = ()
    num_history_runs: int = 7
    tool_call_limit: Optional[int] = 8
    member_tool_call_limit: Optional[int] = 24

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("OSManager.name must not be empty")
        if self.num_history_runs < 0:
            raise ValueError("OSManager.num_history_runs must not be negative")

        for name in ("tool_call_limit", "member_tool_call_limit"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"OSManager.{name} must be a non-negative integer or None")

    @property
    def id(self) -> str:
        """The fixed, reserved id of the served manager team."""
        return MANAGER_TEAM_ID
