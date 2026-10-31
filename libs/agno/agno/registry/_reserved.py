"""Framework-owned component IDs, reserved even when their feature is disabled."""

from typing import Any

MANAGER_TEAM_ID = "os-manager-internal"
BUILDER_ID = "platform-builder-internal"
OPERATOR_ID = "platform-manager-internal"
COMPANY_MANAGER_ID = "company-manager-internal"
# Company Manager's former ID stays reserved so a user component cannot claim it.
LEGACY_PRODUCT_MANAGER_ID = "product-manager-internal"
RESERVED_MEMBER_IDS = frozenset({BUILDER_ID, OPERATOR_ID})
RESERVED_MANAGER_IDS = RESERVED_MEMBER_IDS | {MANAGER_TEAM_ID, COMPANY_MANAGER_ID, LEGACY_PRODUCT_MANAGER_ID}


def is_framework_owned(component: Any) -> bool:
    """True for the built-in manager team and members, which the registry never serves."""
    return (
        getattr(component, "id", None) in RESERVED_MANAGER_IDS
        and getattr(component, "_registry_excluded", False) is True
    )


def _reserved_manager_id_message(component_id: str) -> str:
    return f"Component ID '{component_id}' is reserved. Please choose a different ID for your component."
