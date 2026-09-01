import re
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Union

from agno.exceptions import PathSecurityError
from agno.utils.log import log_debug

# CON, PRN, NUL, etc. create device handles on Windows — block cross-platform for consistency
_WINDOWS_RESERVED_NAMES_RE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", re.IGNORECASE)
_WINDOWS_PATH_PREFIX_RE = re.compile(r"^([A-Za-z]:|\\\\)")


def _contains_control_chars(text: str) -> bool:
    """Check for null bytes, newlines, and other control characters."""
    return any(unicodedata.category(c) == "Cc" for c in text)


def _has_windows_path_prefix(text: str) -> bool:
    """Check for Windows drive letters (C:) or UNC paths (\\\\server)."""
    if _WINDOWS_PATH_PREFIX_RE.match(text):
        return True
    # PureWindowsPath catches edge cases the regex misses: //server, C:relative, //?/C:/
    pwp = PureWindowsPath(text)
    return bool(pwp.drive) or pwp.is_absolute()


def _check_containment(base: Path, target: Path, name: str) -> Path:
    """Resolve and verify target stays inside base; catches symlink escapes."""
    try:
        resolved_base = base.resolve()
        resolved_target = target.resolve()
    except (OSError, UnicodeEncodeError) as e:
        raise PathSecurityError(f"Cannot resolve {name!r}: {e}") from e
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise PathSecurityError(f"{name!r} resolves outside {base}") from None
    return resolved_target


def _sanitize_segment(segment: str) -> str:
    """Validate a path segment and return its canonical form.

    Strips trailing dots/spaces and rejects control chars, Windows paths,
    and reserved device names (CON, NUL, etc.).
    """
    if _contains_control_chars(segment):
        raise PathSecurityError(f"Invalid path segment: {segment!r}")
    if _has_windows_path_prefix(segment):
        raise PathSecurityError(f"Invalid path segment: {segment!r}")
    # Strip before reserved-name check so CON. matches
    stripped = segment.rstrip(". ")
    if not stripped:
        raise PathSecurityError(f"Invalid path segment: {segment!r}")
    if _WINDOWS_RESERVED_NAMES_RE.match(stripped):
        raise PathSecurityError(f"Invalid path segment: {segment!r}")
    return stripped


def sanitize_filename(filename: str) -> str:
    """Validate and return safe basename. Strips path components."""
    # NFKC normalizes unicode so ．．／ becomes ../
    filename = unicodedata.normalize("NFKC", filename)
    if _contains_control_chars(filename):
        raise PathSecurityError(f"Invalid filename: {filename!r}")
    if _has_windows_path_prefix(filename):
        raise PathSecurityError(f"Invalid filename: {filename!r}")
    if "/" in filename or "\\" in filename:
        log_debug(f"sanitize_filename discarded path components from {filename!r}")
    # rstrip prevents trailing dots creating empty names on Windows
    safe = Path(filename.replace("\\", "/")).name.rstrip(". ")
    if not safe or safe.strip(".") == "":
        raise PathSecurityError(f"Invalid filename: {filename!r}")
    return _sanitize_segment(safe)


def safe_join_filename(directory: Union[str, Path], filename: str) -> Path:
    """Join ``directory`` with the sanitized basename of ``filename``.

    Path components in ``filename`` are discarded. Use for filenames
    received from LLM output. For multi-segment paths, use
    ``safe_join_relative_path``.
    """
    base = Path(directory)
    safe = sanitize_filename(filename)
    return _check_containment(base, base / safe, filename)


def safe_join_relative_path(directory: Union[str, Path], subpath: str) -> Path:
    """Join ``directory`` with ``subpath``, preserving multi-segment paths.

    Allows inputs like ``"docs/report.md"`` and enforces containment by
    resolving both ``directory`` and the target before comparison.
    """
    if not subpath or not subpath.strip():
        raise PathSecurityError(f"Invalid subpath: {subpath!r}")
    subpath = unicodedata.normalize("NFKC", subpath)
    if _contains_control_chars(subpath):
        raise PathSecurityError(f"Invalid subpath: {subpath!r}")
    pwp = PureWindowsPath(subpath)
    if pwp.drive or pwp.is_absolute():
        raise PathSecurityError(f"Subpath must be relative: {subpath!r}")
    subpath = subpath.replace("\\", "/")
    # Validate each segment; keep "", ".", ".." for Path to resolve naturally
    cleaned_parts = []
    for segment in subpath.split("/"):
        if segment in ("", ".", ".."):
            cleaned_parts.append(segment)
            continue
        cleaned_parts.append(_sanitize_segment(segment))
    base = Path(directory)
    target = base / "/".join(cleaned_parts)
    return _check_containment(base, target, subpath)
