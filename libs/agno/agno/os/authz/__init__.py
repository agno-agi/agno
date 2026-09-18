"""Pluggable authorization providers for AgentOS.

The ``AuthorizationProvider`` interface is the seam between AgentOS's request
handling and the logic that decides "can this principal do this action on this
resource". The built-in :class:`ScopeAuthorizationProvider` implements the
existing JWT-scope RBAC with zero external dependencies, so the default
behaviour is unchanged.

Customers who need a richer model (relationship-based / ReBAC, attribute-based,
or an external engine such as OpenFGA, SpiceDB or Cerbos) implement the same
interface and pass it via ``Authorization(authorization_provider=...)``.

Managed roles (runtime-editable RBAC) are backed by agno's own
:class:`NativePolicyEngine` behind the swappable :class:`PolicyEngine` port — no
third-party policy engine in the default path.
"""

from agno.os.authz.audit import AuditEvent, AuditSink, DbAuditSink, LoggingAuditSink
from agno.os.authz.authorization import Authorization
from agno.os.authz.engine import EngineAuthorizationProvider, PolicyEngine, ScopeEntry
from agno.os.authz.fga import FGAAuthorizationProvider, FGAClient
from agno.os.authz.native_engine import NativePolicyEngine
from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
from agno.os.authz.role_store import RoleStore
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.authz.user_directory import UserDirectory
from agno.os.authz.user_store import UserStore

__all__ = [
    # The Authorization object: verification + roles + users + audit + admin API, wired into AgentOS.
    "Authorization",
    "AuthorizationContext",
    "AuthorizationProvider",
    "ScopeAuthorizationProvider",
    # Managed roles: the product surface + swappable backend (port, generic
    # provider, native default engine). get_roles_router lives in admin_router and
    # is imported directly to keep this package import FastAPI-free.
    "RoleStore",
    # The credential-less user directory (the no-IdP tier). Dependency-free like
    # RoleStore, so it belongs on the same package seam.
    "UserStore",
    "UserDirectory",
    "PolicyEngine",
    "ScopeEntry",
    "EngineAuthorizationProvider",
    "NativePolicyEngine",
    # Fine-grained / relationship-based authz (ReBAC). The provider + port are
    # dependency-free; the OpenFGA adapter (OpenFGAClient) lives behind agno[fga].
    "FGAAuthorizationProvider",
    "FGAClient",
    "AuditEvent",
    "AuditSink",
    "LoggingAuditSink",
    "DbAuditSink",
]
