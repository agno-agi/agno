"""Company details field validation, independent of storage adapters."""

from typing import Any, Dict


def validate_company_details(fields: Dict[str, Any]) -> None:
    """Only human-owned descriptive fields can be changed."""
    if fields.keys() - {"name", "description"}:
        raise ValueError("Only company name and description can be changed")
    if "name" in fields and (
        not isinstance(fields["name"], str) or not fields["name"].strip() or len(fields["name"]) > 255
    ):
        raise ValueError("Company name must contain 1 to 255 characters")
    description = fields.get("description")
    if description is not None and (not isinstance(description, str) or len(description) > 20000):
        raise ValueError("Company description must contain at most 20000 characters")
    # PostgreSQL text cannot store NUL, so reject it on every adapter.
    if "\x00" in str(fields.get("name") or "") or "\x00" in str(description or ""):
        raise ValueError("Company details must not contain NUL characters")
