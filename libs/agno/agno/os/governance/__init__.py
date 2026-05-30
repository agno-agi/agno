"""AgentOS Governance — Track B: persisted end-users, scope templates, and audit.

This package adds a stateful layer on top of the Track A token primitives:

- ``GovernanceStore`` persists end-users, scope templates, issued tokens,
  and an audit log to the AgentOS database (Postgres or SQLite).
- HTTP routers (``/scope-templates``, ``/end-users``, ``/audit-log``) wrap
  the store and gate it behind dedicated scopes.
- ``JWTMiddleware`` calls into the store on every authenticated request to
  enforce revocation (with a small in-memory TTL cache).

Track A (``AgentOS.issue_token()`` and ``POST /tokens``) keeps working
exactly as before — Track B is additive.
"""

from agno.os.governance.store import (
    AuditLogEntry,
    EndUser,
    EndUserStatus,
    GovernanceStore,
    IssuedToken,
    ScopeTemplate,
    TokenStatus,
)

__all__ = [
    "AuditLogEntry",
    "EndUser",
    "EndUserStatus",
    "GovernanceStore",
    "IssuedToken",
    "ScopeTemplate",
    "TokenStatus",
]
