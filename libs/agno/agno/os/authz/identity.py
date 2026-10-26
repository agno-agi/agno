"""Tenant identity normalization, independent of resource authorization."""

from typing import Any, Mapping, Optional


def validate_tenant_claim(tenant_claim: Optional[str]) -> None:
    """Require a nonempty claim name when tenant identity is enabled."""
    if tenant_claim is not None and (not isinstance(tenant_claim, str) or not tenant_claim.strip()):
        raise ValueError("tenant_claim must be a nonempty string")


def tenant_id_from_claims(claims: Mapping[str, Any], tenant_claim: Optional[str]) -> Optional[str]:
    """Read an opaque tenant ID from verified claims without coercion or trimming.

    An absent claim means no tenant identity. A present invalid claim is rejected,
    including null, rather than silently falling back to a tenant-less identity.
    This identity alone does not grant access to tenant resources.
    """
    if tenant_claim is None or tenant_claim not in claims:
        return None
    tenant_id = claims[tenant_claim]
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("Invalid tenant claim: expected a nonempty string")
    return tenant_id
