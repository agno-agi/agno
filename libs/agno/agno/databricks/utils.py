from typing import Dict, Optional, Set

from agno.utils.log import log_warning

RETRYABLE_STATUS_CODES: Set[int] = {408, 409, 429, 500, 502, 503, 504}


def normalize_host(host: Optional[str]) -> Optional[str]:
    if host is None:
        return None

    normalized = host.strip().rstrip("/")
    if normalized == "":
        return None

    if normalized.startswith("http://"):
        log_warning(
            f"Databricks host uses http:// ({normalized}). "
            "Consider using https:// for production environments."
        )

    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    return normalized


def build_url(base_url: str, endpoint: str) -> str:
    if base_url.strip() == "":
        raise ValueError("Databricks base_url cannot be empty")

    if endpoint.startswith(("http://", "https://")):
        return endpoint

    normalized_base = base_url.rstrip("/")
    normalized_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    return f"{normalized_base}{normalized_endpoint}"


def merge_headers(*header_sets: Optional[Dict[str, str]]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for header_set in header_sets:
        if header_set:
            merged.update(header_set)
    return merged
