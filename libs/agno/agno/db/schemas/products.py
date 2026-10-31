"""Validation shared by Product managers and database adapters."""

from typing import Any, Dict, Optional, Tuple


def validate_product_fields(fields: Dict[str, Any]) -> None:
    """Accept only descriptive edits; identity and lifecycle use dedicated methods."""
    unknown = set(fields) - {"name", "purpose", "metadata"}
    if unknown:
        raise ValueError(f"Unsupported product fields: {sorted(unknown)}")
    if "name" in fields and (not isinstance(fields["name"], str) or not fields["name"].strip()):
        raise ValueError("name must be a non-empty string")
    if fields.get("purpose") is not None and not isinstance(fields["purpose"], str):
        raise ValueError("purpose must be a string or None")
    if fields.get("metadata") is not None and not isinstance(fields["metadata"], dict):
        raise ValueError("metadata must be a dictionary or None")
    if "metadata" in fields:
        product_metadata(fields["metadata"])


def product_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply the archive policy without changing unrelated Product metadata."""
    result = {"archive_window_days": 14, **(metadata or {})}
    days = result["archive_window_days"]
    if not isinstance(days, int) or isinstance(days, bool) or days < 0:
        raise ValueError("metadata.archive_window_days must be a nonnegative integer")
    return result


def company_sort(sort_by: Optional[str], sort_order: Optional[str]) -> Tuple[str, str]:
    """Keep the existing default and permit explicit activity ordering."""
    field, order = sort_by or "created_at", sort_order or "desc"
    if field not in {"created_at", "updated_at"} or order not in {"asc", "desc"}:
        raise ValueError("sort_by must be created_at or updated_at; sort_order must be asc or desc")
    return field, order
