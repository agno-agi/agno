"""Framework-owned component IDs, reserved even when their feature is disabled."""

from typing import Any

# Public API identifiers: reserve these exact names for built-in managers.
MANAGER_TEAM_ID = "superagent"
BUILDER_ID = "platform-builder"
OPERATOR_ID = "platform-manager"
COMPANY_MANAGER_ID = "company-manager"
# Company Manager's former ID stays reserved so a user component cannot claim it.
LEGACY_PRODUCT_MANAGER_ID = "product-manager-internal"
# IDs used before 3.2. They stay reserved so a user component cannot inherit their grants or
# history, and no longer resolve. Stored rows keep these spellings: a stored deny on one stops
# matching, which is why startup refuses managed-role policies that still use them.
FORMER_MANAGER_IDS = {
    "os-manager-internal": MANAGER_TEAM_ID,
    "platform-builder-internal": BUILDER_ID,
    "platform-manager-internal": OPERATOR_ID,
    "company-manager-internal": COMPANY_MANAGER_ID,
}
RESERVED_MEMBER_IDS = frozenset({BUILDER_ID, OPERATOR_ID, "platform-builder-internal", "platform-manager-internal"})
RESERVED_MANAGER_IDS = RESERVED_MEMBER_IDS | {
    MANAGER_TEAM_ID,
    COMPANY_MANAGER_ID,
    LEGACY_PRODUCT_MANAGER_ID,
    *FORMER_MANAGER_IDS,
}


def is_framework_owned(component: Any) -> bool:
    """True for the built-in manager team and members, which the registry never serves."""
    return (
        getattr(component, "id", None) in RESERVED_MANAGER_IDS
        and getattr(component, "_registry_excluded", False) is True
    )


def _reserved_manager_id_message(component_id: str) -> str:
    current = FORMER_MANAGER_IDS.get(component_id)
    if current is not None:
        return f"Manager ID '{component_id}' was renamed to '{current}' in Agno 3.2. Use the new ID."
    return f"Component ID '{component_id}' is reserved. Please choose a different ID for your component."


def _raise_if_manager_catalog_collision(db: Any) -> None:
    """Refuse to shadow a custom component that predates the public manager IDs."""
    for component_id in FORMER_MANAGER_IDS.values():
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
