"""Framework-owned component IDs, reserved even when their feature is disabled."""

from typing import Any

# Public API identifiers: reserve these exact names for built-in managers.
MANAGER_TEAM_ID = "superagent"
BUILDER_ID = "platform-builder"
# The restricted agent that runs Company Routines unattended, and the default Routine executor.
# Served for the scheduler; chat and listings leave it out.
MINI_AGENT_ID = "miniagent"
# A former ID of the agent that ran Routines. It stays reserved so a user component cannot claim it.
LEGACY_PRODUCT_MANAGER_ID = "product-manager-internal"
# IDs used before 3.2, each with the ID that now does its work. They stay reserved so a user
# component cannot inherit their grants or history, and no longer resolve. Stored rows keep these
# spellings: a stored deny on one stops matching, which is why startup refuses managed-role
# policies that still use them.
FORMER_MANAGER_IDS = {
    "os-manager-internal": MANAGER_TEAM_ID,
    "platform-builder-internal": BUILDER_ID,
    "platform-manager-internal": MANAGER_TEAM_ID,
    "company-manager-internal": MANAGER_TEAM_ID,
}
# Routines ran on this former manager as well. Mini Agent runs them now, not Super Agent.
FORMER_ROUTINE_EXECUTOR_ID = "company-manager-internal"
# The policy resource of each built-in component. Super Agent is served as a team, the others as
# agents: a policy that names the wrong family matches nothing.
MANAGER_RESOURCES = {
    MANAGER_TEAM_ID: f"teams/{MANAGER_TEAM_ID}",
    BUILDER_ID: f"agents/{BUILDER_ID}",
    MINI_AGENT_ID: f"agents/{MINI_AGENT_ID}",
}
RESERVED_MEMBER_IDS = frozenset({BUILDER_ID, "platform-builder-internal", "platform-manager-internal"})
RESERVED_MANAGER_IDS = RESERVED_MEMBER_IDS | {
    MANAGER_TEAM_ID,
    MINI_AGENT_ID,
    LEGACY_PRODUCT_MANAGER_ID,
    *FORMER_MANAGER_IDS,
}


def _listed(components: Any) -> list:
    """Served components as listings show them. Mini Agent is served for the scheduler only."""
    return [component for component in components or [] if getattr(component, "id", None) != MINI_AGENT_ID]


def is_framework_owned(component: Any) -> bool:
    """True for the built-in manager team and members, which the registry never serves."""
    return (
        getattr(component, "id", None) in RESERVED_MANAGER_IDS
        and getattr(component, "_registry_excluded", False) is True
    )


def _reserved_manager_id_message(component_id: str) -> str:
    current = FORMER_MANAGER_IDS.get(component_id)
    if current is not None:
        also = f", or '{MINI_AGENT_ID}' for a Routine executor" if component_id == FORMER_ROUTINE_EXECUTOR_ID else ""
        return f"Manager ID '{component_id}' was replaced by '{current}' in Agno 3.2. Use the new ID{also}."
    return f"Component ID '{component_id}' is reserved. Please choose a different ID for your component."


def _raise_if_manager_catalog_collision(db: Any) -> None:
    """Refuse to shadow a custom component that predates the public manager IDs."""
    for component_id in sorted({*FORMER_MANAGER_IDS.values(), MINI_AGENT_ID}):
        try:
            row = db.get_component(component_id, include_deleted=True)
        except NotImplementedError:
            return  # This adapter has no component catalog to collide with.
        if row is not None:
            raise ValueError(
                f"Stored component ID {component_id!r} is now reserved. Rename or migrate this custom component and its sessions and permissions before enabling managers."
            )


def _check_manager_catalog(agent_os: Any, db: Any) -> None:
    """Check each database once per AgentOS; building the managers reaches this several times."""
    if id(db) not in agent_os._manager_catalog_checked:
        _raise_if_manager_catalog_collision(db)
        agent_os._manager_catalog_checked.add(id(db))
