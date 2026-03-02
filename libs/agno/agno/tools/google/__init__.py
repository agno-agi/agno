from importlib import import_module
from typing import Any

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "GmailTools": ("agno.tools.google.gmail", "GmailTools"),
    "GoogleBigQueryTools": ("agno.tools.google.bigquery", "GoogleBigQueryTools"),
    "GoogleCalendarTools": ("agno.tools.google.calendar", "GoogleCalendarTools"),
    "GoogleDriveTools": ("agno.tools.google.drive", "GoogleDriveTools"),
    "GoogleMapTools": ("agno.tools.google.maps", "GoogleMapTools"),
    "GoogleSheetsTools": ("agno.tools.google.sheets", "GoogleSheetsTools"),
    "YouTubeTools": ("agno.tools.google.youtube", "YouTubeTools"),
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        module = import_module(module_path)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
