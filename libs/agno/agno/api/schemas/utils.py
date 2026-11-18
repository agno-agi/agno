from enum import Enum
from functools import lru_cache


class TelemetryRunEventType(str, Enum):
    AGENT = "agent"
    EVAL = "eval"
    TEAM = "team"
    WORKFLOW = "workflow"


@lru_cache(maxsize=1)
def get_sdk_version() -> str:
    """Return the installed agno SDK version from package metadata.

    Falls back to "unknown" if the package metadata isn't available. Cached:
    every telemetry schema calls this as a field default on the caller's thread,
    and the metadata lookup re-parses the package METADATA file each time.
    """
    from importlib.metadata import version as pkg_version

    try:
        return pkg_version("agno")
    except Exception:
        return "unknown"
