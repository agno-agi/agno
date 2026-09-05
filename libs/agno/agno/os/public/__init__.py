"""Opt-in anonymous component serving with shared PostgreSQL admission."""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from agno.os.public._limits import PublicLimiter, RateLimit

_client_id: ContextVar[str] = ContextVar("agno_public_client_id", default="unknown")


def get_public_client_id() -> str:
    """Framework-resolved identity for tool-side quotas; never a model argument."""
    return _client_id.get()


@dataclass(frozen=True)
class FileUploadLimits:
    max_files: int = 4
    max_file_bytes: int = 8 * 1024 * 1024
    allowed_types: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self):
        if not 1 <= self.max_files <= 12 or self.max_file_bytes <= 0:
            raise ValueError("Invalid file upload limits")
        for suffix, mime in self.allowed_types:
            if not suffix.startswith(".") or suffix != suffix.lower() or mime != mime.lower() or "/" not in mime:
                raise ValueError("Upload types must be lowercase suffix/MIME pairs")


@dataclass
class PublicSurface:
    agents: List[Any] = field(default_factory=list)
    workflows: List[Any] = field(default_factory=list)
    mcp: bool = False
    namespace: Optional[str] = None
    limits: Optional[Dict[str, RateLimit]] = None
    client_id: Optional[Callable] = None
    uploads: Optional[FileUploadLimits] = None
    max_body_bytes: int = 12 * 1024 * 1024
    max_run_seconds: float = 240
    max_output_bytes: int = 1024 * 1024
    max_active_runs: int = 8
    _limiter: Optional[PublicLimiter] = field(default=None, init=False, repr=False)

    @property
    def limiter(self) -> PublicLimiter:
        if self._limiter is None or not self._limiter.ready:
            raise ValueError("PublicSurface limiter is not prepared")
        return self._limiter

    def _bind(self, agent_os: Any) -> None:
        from agno.agent import Agent
        from agno.db.postgres import PostgresDb
        from agno.workflow import Workflow

        if not isinstance(agent_os.db, PostgresDb):
            raise ValueError("PublicSurface requires a synchronous PostgreSQL AgentOS db")
        namespace = self.namespace if self.namespace is not None else agent_os._public_explicit_id
        if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", namespace):
            raise ValueError("PublicSurface requires a stable explicit namespace or AgentOS.id")
        if min(self.max_body_bytes, self.max_run_seconds, self.max_output_bytes, self.max_active_runs) <= 0:
            raise ValueError("PublicSurface request bounds must be positive")
        self.namespace = namespace
        for field_name, kind in (("agents", Agent), ("workflows", Workflow)):
            registered = getattr(agent_os, field_name)
            selected: List[Any] = []
            by_id: Dict[Optional[str], Any] = {}
            for component in registered or []:
                if not isinstance(component, kind):
                    continue
                if component.id in by_id and by_id[component.id] is not component:
                    raise ValueError("Conflicting registered public component IDs")
                by_id[component.id] = component
            for component in getattr(self, field_name):
                if not isinstance(component, kind) or not any(component is entry for entry in registered or []):
                    raise ValueError("PublicSurface must select registered objects of the matching component kind")
                if not component.id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", component.id):
                    raise ValueError("PublicSurface requires stable component IDs")
                if not any(component is entry for entry in selected):
                    selected.append(component)
            setattr(self, field_name, selected)
        if self.mcp:
            config = agent_os.mcp_config
            if (
                not agent_os.mcp
                or config is None
                or config.default_tools
                or config.lifecycle_tools
                or not config.stateless
            ):
                raise ValueError(
                    "Public MCP requires explicit tools, disabled default/lifecycle tools and stateless=True"
                )
        if self._limiter is None:
            self._limiter = PublicLimiter(agent_os.db.db_engine, namespace, self.limits)


__all__ = ["PublicSurface", "RateLimit", "FileUploadLimits", "get_public_client_id"]
