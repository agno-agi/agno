"""Pluggable authorization providers for AgentOS.

The ``AuthorizationProvider`` interface is the seam between AgentOS's request
handling and the logic that decides "can this principal do this action on this
resource". The built-in :class:`ScopeAuthorizationProvider` implements the
existing JWT-scope RBAC with zero external dependencies, so the default
behaviour is unchanged.

Customers who need a richer model (relationship-based / ReBAC, attribute-based,
or an external engine such as Casbin, OpenFGA or Cerbos) implement the same
interface and pass it via ``AuthorizationConfig(authorization_provider=...)``.

This mirrors the provider pattern used elsewhere in the ecosystem
(e.g. ``check`` / ``require`` / ``filter_accessible``) so the swap is a config
change rather than a fork of the request pipeline.
"""

from agno.os.authz.audit import AuditEvent, AuditSink, DbAuditSink, LoggingAuditSink
from agno.os.authz.provider import (
    AuthorizationContext,
    AuthorizationProvider,
)
from agno.os.authz.scope_provider import ScopeAuthorizationProvider

__all__ = [
    "AuthorizationContext",
    "AuthorizationProvider",
    "ScopeAuthorizationProvider",
    "AuditEvent",
    "AuditSink",
    "LoggingAuditSink",
    "DbAuditSink",
]
