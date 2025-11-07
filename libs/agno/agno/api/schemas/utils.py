from enum import Enum


class TelemetryRunEventType(str, Enum):
    AGENT = "agent"
    EVAL = "eval"
    TEAM = "team"
    WORKFLOW = "workflow"


def get_sdk_version() -> str:
    """Return the installed agno SDK version from package metadata.

    Falls back to "unknown" if the package metadata isn't available.
    """
    from importlib.metadata import version as pkg_version

    try:
        return pkg_version("agno")
    except Exception:
        return "unknown"
