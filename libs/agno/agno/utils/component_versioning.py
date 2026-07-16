from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

RUN_COMPONENT_PIN_KEY = "__agno_component_pin__"


def pin_component_version_metadata(
    metadata: Optional[Mapping[str, Any]],
    *,
    component_type: str,
    component_id: Optional[str],
    version: Optional[int],
) -> Optional[Dict[str, Any]]:
    """Return metadata with a pinned component snapshot for later resume/reload."""

    metadata_dict: Dict[str, Any] = dict(metadata) if metadata is not None else {}

    if component_id is not None and version is not None:
        metadata_dict[RUN_COMPONENT_PIN_KEY] = {
            "component_type": component_type,
            "component_id": component_id,
            "version": version,
        }

    return metadata_dict or None


def get_pinned_component_version(
    metadata: Optional[Mapping[str, Any]], *, component_type: str, component_id: Optional[str]
) -> Optional[int]:
    """Extract a pinned component version from run metadata when it matches the component."""

    if metadata is None:
        return None

    pin = metadata.get(RUN_COMPONENT_PIN_KEY)
    if not isinstance(pin, Mapping):
        return None

    if pin.get("component_type") != component_type:
        return None
    if component_id is not None and pin.get("component_id") != component_id:
        return None

    version = pin.get("version")
    return version if isinstance(version, int) else None
