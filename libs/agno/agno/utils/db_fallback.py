"""Strict-load guard for the caller-db fallback."""

from typing import Any, Dict, List, Optional


def db_fallback_divergence(config: Dict[str, Any], fallback_db: Any) -> Optional[List[str]]:
    """How a config's declared db differs from the db it would fall back to.

    Returns None when the config declares no db (nothing to compare), else the
    sorted keys on which the declared db differs from the fallback db. An empty
    list means the fallback routes like the declared db: same identity, same
    table overrides.

    An absent key in the stored config is not an override, and the connection
    field is never serialized, so neither counts as a difference. A key the
    fallback db does not report cannot be compared at all -- identity mismatch
    still surfaces through ``id``, which every db serializes.
    """
    db_config = config.get("db")
    if not isinstance(db_config, dict):
        return None
    fallback = fallback_db.to_dict() if fallback_db is not None else {}
    return sorted(
        key
        for key, value in db_config.items()
        if value is not None and key != "connection" and key in fallback and fallback[key] != value
    )


def require_db_fallback_matches(
    config: Dict[str, Any], fallback_db: Any, component_type: str, component_id: Optional[str]
) -> None:
    """Refuse a strict load whose declared db would silently become another store.

    db_from_dict rebuilds postgres, sqlite and clickhouse configs that carry
    their connection field; anything else resolves through the registry. When
    neither supplies the declared db, loaders fall back to the caller's db --
    and if that is a different store, the component's sessions, memory and runs
    durably land somewhere other than configured, which the caller cannot see
    from the answer it gets back.

    The comparison is what makes this narrow enough to be safe: when the
    declared db names the fallback db, with the same table overrides, the
    fallback is not a redirection and the load proceeds. That keeps the
    adapters whose connection field cannot serialize (mysql, mongo, redis,
    json, dynamo) working when they are the caller's own db. Lenient loads
    skip this guard entirely, so reads and listings stay available for repair.
    """
    differing = db_fallback_divergence(config, fallback_db)
    if not differing:
        return
    from agno.exceptions import ComponentRehydrationError

    db_config = config.get("db") or {}
    declared = db_config.get("id") or db_config.get("type") or "unknown"
    raise ComponentRehydrationError(
        f"{component_type.capitalize()} '{component_id}' declares db '{declared}', which could not be "
        f"reconstructed, and the db it would fall back to differs ({', '.join(differing)}); running it would "
        f"write its sessions and memory somewhere other than configured. Register that db in the registry, "
        f"or re-save the {component_type} against the db it should use."
    )
