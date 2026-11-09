"""Framework-owned component IDs, reserved even when their feature is disabled."""

from typing import Any, Optional

# Double hyphens distinguish built-ins; single-hyphen names are user-owned.
MANAGER_TEAM_ID = "super--agent"
BUILDER_ID = "platform--builder"
OPERATOR_ID = "platform--manager"
COMPANY_MANAGER_ID = "company--manager"
# Company Manager's former ID stays reserved so a user component cannot claim it.
LEGACY_PRODUCT_MANAGER_ID = "product-manager-internal"
# Previous manager IDs remain compatibility aliases, and stored rows keep these spellings.
# Removing an alias needs a data migration first: a stored deny that stops matching
# leaves any wildcard allow in force, so that user gains access.
# The old Product Manager spelling stays reserved, but is not revived as an alias.
MANAGER_ID_ALIASES = {
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
    *MANAGER_ID_ALIASES,
}


def _manager_id(component_id: Optional[str], resource_type: Optional[str] = None) -> Optional[str]:
    """Resolve a public manager alias without crossing component families.

    resource_type names the family as a route ("agents") or a component type ("agent").
    """
    resolved = MANAGER_ID_ALIASES.get(component_id, component_id) if component_id is not None else None
    if resource_type is not None:
        expected = "team" if resolved == MANAGER_TEAM_ID else "agent"
        if resource_type.removesuffix("s") != expected:
            return component_id
    return resolved


def _manager_ids_match(left: Optional[str], right: Optional[str], resource_type: Optional[str] = None) -> bool:
    return _manager_id(left, resource_type) == _manager_id(right, resource_type)


def is_framework_owned(component: Any) -> bool:
    """True for the built-in manager team and members, which the registry never serves."""
    return (
        getattr(component, "id", None) in RESERVED_MANAGER_IDS
        and getattr(component, "_registry_excluded", False) is True
    )


def _reserved_manager_id_message(component_id: str) -> str:
    return f"Component ID '{component_id}' is reserved. Please choose a different ID for your component."


def _manager_id_variants(component_id: str, resource_type: str) -> tuple[str, ...]:
    """Storage IDs for one manager, without rewriting historical records."""
    canonical = _manager_id(component_id, resource_type)
    return tuple(
        dict.fromkeys(
            [
                component_id,
                *[
                    alias
                    for alias, target in MANAGER_ID_ALIASES.items()
                    if target == canonical and _manager_id(alias, resource_type) == canonical
                ],
                *([canonical] if canonical else []),
            ]
        )
    )


def _raise_if_manager_catalog_collision(db: Any) -> None:
    """Refuse to shadow a custom component that predates the public manager IDs."""
    for component_id in MANAGER_ID_ALIASES.values():
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
