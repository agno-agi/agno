"""Serialization helpers for the registry router."""

from typing import Any, Optional

from agno.os.schema import (
    MemoryManagerMetadata,
    RegistryContentResponse,
    RegistryResourceType,
    SessionSummaryManagerMetadata,
)


def safe_str(v: Any) -> Optional[str]:
    """Return a stripped, non-empty string for a value, or None."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v)


def class_path(obj: Any) -> str:
    """Return the full module path of an object's class."""
    cls = obj.__class__
    return f"{cls.__module__}.{cls.__name__}"


def build_memory_manager_resource(manager: Any) -> RegistryContentResponse:
    """Build a RegistryContentResponse for a memory manager."""
    manager_id = safe_str(getattr(manager, "id", None)) or manager.__class__.__name__
    manager_name = safe_str(getattr(manager, "name", None)) or manager_id
    model = getattr(manager, "model", None)
    db = getattr(manager, "db", None)
    metadata = MemoryManagerMetadata(
        class_path=class_path(manager),
        owner_id=safe_str(getattr(manager, "owner_id", None)),
        owner_type=safe_str(getattr(manager, "owner_type", None)),
        model_class=class_path(model) if model else None,
        model_id=safe_str(getattr(model, "id", None)) if model else None,
        db_class=class_path(db) if db else None,
        add_memories=getattr(manager, "add_memories", None),
        update_memories=getattr(manager, "update_memories", None),
        delete_memories=getattr(manager, "delete_memories", None),
        clear_memories=getattr(manager, "clear_memories", None),
    )
    return RegistryContentResponse(
        name=manager_name,
        id=manager_id,
        type=RegistryResourceType.MEMORY_MANAGER,
        metadata=metadata.model_dump(exclude_none=True),
    )


def build_session_summary_manager_resource(manager: Any) -> RegistryContentResponse:
    """Build a RegistryContentResponse for a session summary manager."""
    manager_id = safe_str(getattr(manager, "id", None)) or manager.__class__.__name__
    manager_name = safe_str(getattr(manager, "name", None)) or manager_id
    model = getattr(manager, "model", None)
    metadata = SessionSummaryManagerMetadata(
        class_path=class_path(manager),
        owner_id=safe_str(getattr(manager, "owner_id", None)),
        owner_type=safe_str(getattr(manager, "owner_type", None)),
        model_class=class_path(model) if model else None,
        model_id=safe_str(getattr(model, "id", None)) if model else None,
        last_n_runs=getattr(manager, "last_n_runs", None),
        conversation_limit=getattr(manager, "conversation_limit", None),
    )
    return RegistryContentResponse(
        name=manager_name,
        id=manager_id,
        type=RegistryResourceType.SESSION_SUMMARY_MANAGER,
        metadata=metadata.model_dump(exclude_none=True),
    )
