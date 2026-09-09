"""File toolkits.

``FileTools`` reads and writes files under a directory; ``FileGenerationTools`` builds
artifacts (PDF, DOCX, CSV, ...) and hands them back as run output.

Both resolve on first access (PEP 562) so importing ``FileTools`` does not pull
``reportlab`` and ``python-docx`` in behind it.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agno.tools.file.file import DEFAULT_EXCLUDE_PATTERNS, TEXT_EXTENSIONS, FileTools, path_matches_exclude
    from agno.tools.file.generation import CODE_LANGUAGE_MAP, DOCX_AVAILABLE, PDF_AVAILABLE, FileGenerationTools

__all__ = [
    "CODE_LANGUAGE_MAP",
    "DEFAULT_EXCLUDE_PATTERNS",
    "DOCX_AVAILABLE",
    "FileGenerationTools",
    "FileTools",
    "PDF_AVAILABLE",
    "TEXT_EXTENSIONS",
    "path_matches_exclude",
]

_LAZY_ATTRS = {
    "CODE_LANGUAGE_MAP": "agno.tools.file.generation",
    "DEFAULT_EXCLUDE_PATTERNS": "agno.tools.file.file",
    "DOCX_AVAILABLE": "agno.tools.file.generation",
    "FileGenerationTools": "agno.tools.file.generation",
    "FileTools": "agno.tools.file.file",
    "PDF_AVAILABLE": "agno.tools.file.generation",
    "TEXT_EXTENSIONS": "agno.tools.file.file",
    "path_matches_exclude": "agno.tools.file.file",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list:
    return sorted(set(globals()) | set(__all__))
