"""Credential-free harness double for exercising sandbox infrastructure."""

from typing import Any, ClassVar, Dict, Optional

from agno.agents._config import agent_dataclass
from agno.agents._media import accept_media
from agno.agents.base import BaseExternalAgent


@agent_dataclass
class FixtureAgent(BaseExternalAgent):
    """Echo harness that runs only inside a Sandbox whose env sets AGNO_SANDBOX_TEST_RUNTIME=1.

    It makes no model calls: the runtime echoes the input and records the run in the workspace.
    """

    # Seconds the runtime waits before answering, to exercise cancellation and contention.
    delay: float = 0

    _sdk_name: ClassVar[str] = "fixture"
    _sandbox_runtime: ClassVar[Optional[str]] = "fixture"

    def __post_init__(self) -> None:
        if self.sandbox is None:
            raise ValueError("FixtureAgent runs only inside a sandbox")
        super().__post_init__()

    def _media_kwargs(self, **media: Any) -> Dict[str, Any]:
        """Images and files are staged in the sandbox workspace, as for Claude and Codex."""
        return accept_media(media)
