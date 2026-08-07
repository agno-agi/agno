from typing import Dict, List


def get_remote_access_scope_mappings(
    prefix: str = "/remote",
    include_agents: bool = True,
    include_teams: bool = True,
) -> Dict[str, List[str]]:
    """RBAC scope mappings for the RemoteAccess interface routes.

    Execution routes require :run, read-only routes require :read. Only families
    actually mounted by the interface are included, matching attach_routes.
    """
    p = prefix.rstrip("/")
    mappings: Dict[str, List[str]] = {}

    if include_agents:
        mappings.update(
            {
                f"GET {p}/agents": ["agents:read"],
                f"GET {p}/agents/*": ["agents:read"],
                f"POST {p}/agents/*/runs": ["agents:run"],
                f"POST {p}/agents/*/runs/*/continue": ["agents:run"],
                f"POST {p}/agents/*/runs/*/cancel": ["agents:run"],
            }
        )
    if include_teams:
        mappings.update(
            {
                f"GET {p}/teams": ["teams:read"],
                f"GET {p}/teams/*": ["teams:read"],
                f"POST {p}/teams/*/runs": ["teams:run"],
                f"POST {p}/teams/*/runs/*/continue": ["teams:run"],
                f"POST {p}/teams/*/runs/*/cancel": ["teams:run"],
            }
        )

    return mappings
