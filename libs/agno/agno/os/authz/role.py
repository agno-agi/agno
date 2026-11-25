"""Roles as objects, and the scope lists a role is usually built from.

    from agno.os.authz import Authorization, Role, UserDirectory, READ, RUN, PLATFORM

    member = Role("member", scopes=READ + RUN)
    platform = Role("platform", scopes=READ + RUN + PLATFORM)

    AgentOS(
        db=db,
        authorization=Authorization(roles=[member, platform]),
        user_directory=UserDirectory(default_role=member),
    )

A user holds one role, so the lists are meant to be added together: ``platform`` above is
everything ``member`` has plus platform access. Add your own scopes the same way
(``READ + RUN + ["knowledge:read"]``).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from agno.registry._reserved import MANAGER_RESOURCES

# A scope entry: a scope string (allow), a (scope, effect) pair, or a {"scope", "effect"} dict.
ScopeInput = Union[str, Tuple[str, str], Dict[str, str]]


@dataclass
class Role:
    """A managed role: an id and the scopes it grants.

    Pass roles to ``Authorization(roles=[...])``. A role that already has scopes in the database
    is left as it is, so a change an admin made through the ``/authz`` API survives a restart.
    """

    id: str
    scopes: List[ScopeInput] = field(default_factory=list)
    name: Optional[str] = None
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("A Role needs a non-empty id, e.g. Role('member', scopes=READ + RUN).")
        if isinstance(self.scopes, str):
            raise TypeError(f"Role({self.id!r}) scopes must be a list of scopes, not one string.")
        # The built-in lists are shared between roles, so a role keeps its own copy
        self.scopes = list(self.scopes)


# See the agents, teams and workflows, and read sessions.
READ: List[str] = ["agents:read", "teams:read", "workflows:read", "sessions:read"]

# Run the agents, teams and workflows, and create and rename sessions.
RUN: List[str] = ["agents:run", "teams:run", "workflows:run", "sessions:write"]

# Platform access: the built-in components, the Company, schedules and the build tools.
# It does not include agent_os:admin.
PLATFORM: List[str] = [
    # Each built-in by name, with the actions it is reached with. A role cannot hold an action wildcard.
    *(
        f"{resource.split('/')[0]}:{component_id}:{action}"
        for component_id, resource in MANAGER_RESOURCES.items()
        for action in ("read", "run")
    ),
    "company:read",
    "company:write",
    "products:read",
    "products:write",
    "products:delete",
    "projects:read",
    "projects:write",
    "projects:delete",
    "tasks:read",
    "tasks:write",
    "tasks:delete",
    "wiki:read",
    "wiki:write",
    "sources:read",
    "sources:write",
    "sources:delete",
    "routines:read",
    "routines:write",
    "routines:delete",
    "decisions:read",
    "decisions:write",
    # Every Routine write also asks for the matching schedules scope
    "schedules:read",
    "schedules:write",
    "schedules:delete",
    # What Super Agent's build tools ask for
    "components:read",
    "components:write",
    "components:delete",
    "registry:read",
    "config:read",
]
