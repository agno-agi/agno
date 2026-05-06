"""Shared security helpers for the hardened agno tools.

This module centralizes the defensive validators used across multiple
toolkits so the behaviour is consistent and auditable in one place.

All helpers are designed to be:

* Pure — no I/O apart from :func:`validate_public_url`, which must
  perform DNS resolution to do its job.
* Conservative — when in doubt they raise :class:`ValueError`. The
  toolkits catch these and turn them into user-facing error strings
  so the LLM sees a structured refusal instead of a crash.
* Cheap enough to call on every tool invocation. The module has no
  heavy imports; toolkits import from here lazily.

Nothing in this file is part of the public agno API surface. External
code should continue to use the high-level toolkits; the helpers here
are an implementation detail.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from typing import FrozenSet, Optional, Tuple
from urllib.parse import urlparse

# --- SQL -----------------------------------------------------------------

SQL_IDENTIFIER_RE: re.Pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

_SELECT_ONLY_RE: re.Pattern = re.compile(
    r"^\s*(?:WITH\s+[\s\S]+?\bSELECT\b|SELECT)\b",
    re.IGNORECASE,
)

_FORBIDDEN_STMT_RE: re.Pattern = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|"
    r"REVOKE|COPY|CALL|MERGE|REPLACE|ATTACH|DETACH|LOAD|INSTALL)\b",
    re.IGNORECASE,
)


def validate_sql_identifier(name: str) -> str:
    """Validate ``name`` as a safe SQL identifier.

    SQL parameter binding cannot substitute identifiers (table or
    column names), so they must be validated before being interpolated
    into a query. This helper accepts only ``[A-Za-z_][A-Za-z0-9_]{0,62}``.

    Args:
        name: Candidate identifier.

    Returns:
        The ``name`` unchanged on success.

    Raises:
        ValueError: If ``name`` is not a string or does not match the
            identifier pattern.
    """
    if not isinstance(name, str) or not SQL_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}. Identifiers must match [A-Za-z_][A-Za-z0-9_]{{0,62}}.")
    return name


def assert_read_only_sql(query: str) -> str:
    """Reject any query that is not a single read-only ``SELECT``/``WITH``.

    This is a defence-in-depth check; callers **must also** open the
    connection in read-only mode (or inside a read-only transaction)
    so that a bypass of this check still cannot write.

    The check is intentionally strict:

    * Rejects empty queries.
    * Rejects multiple statements (``;`` other than a single trailing
      terminator).
    * Requires the statement to start with ``SELECT`` or
      ``WITH ... SELECT``.
    * Rejects any query containing a write/DDL keyword
      (``INSERT``, ``UPDATE``, ``DELETE``, ``DROP``, etc.).

    Args:
        query: The SQL text.

    Returns:
        The ``query`` unchanged on success.

    Raises:
        ValueError: On any rule violation.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Empty SQL query.")
    if ";" in query.strip().rstrip(";"):
        raise ValueError("Multiple statements are not permitted in read-only mode.")
    if not _SELECT_ONLY_RE.match(query):
        raise ValueError("Only SELECT / WITH ... SELECT queries are permitted in read-only mode.")
    if _FORBIDDEN_STMT_RE.search(query):
        raise ValueError("Query contains a write / DDL keyword which is blocked in read-only mode.")
    return query


# --- Shell ---------------------------------------------------------------

SHELL_METACHARS: FrozenSet[str] = frozenset(";|&`$><\n\r\\\"'")


def sanitize_shell_arg(arg: str) -> str:
    """Reject shell args that contain metacharacters.

    ``subprocess.run`` in the shell toolkit is already invoked with
    ``shell=False``, but agents frequently forward these args into
    tools that *do* spawn shells. Refusing metachars at the edge
    contains the blast radius.

    Args:
        arg: A single command-line argument.

    Returns:
        The ``arg`` unchanged on success.

    Raises:
        ValueError: If ``arg`` is not a string or contains any of
            ``;``, ``|``, ``&``, backtick, ``$``, ``>``, ``<``, newline,
            backslash, or quote characters.
    """
    if not isinstance(arg, str):
        raise ValueError("Shell args must be strings.")
    bad = SHELL_METACHARS.intersection(arg)
    if bad:
        raise ValueError(f"Shell argument contains disallowed metacharacter(s): {''.join(sorted(bad))!r}")
    return arg


# --- Filesystem ----------------------------------------------------------


def resolve_within(candidate: str, base: Path) -> Tuple[bool, Path]:
    """Resolve ``candidate`` under ``base`` and confirm containment.

    Symlinks are resolved before the prefix check so users cannot
    point a symlink at an external location and read through it.

    On failure the returned path is the resolved ``base``, never a
    partially-resolved escape path — callers can treat the first
    element of the tuple as the sole authorisation signal.

    Args:
        candidate: A path that may be absolute or relative. Relative
            paths are joined onto ``base``.
        base: The directory that ``candidate`` must stay inside.

    Returns:
        ``(ok, path)``. ``ok`` is True iff ``path`` is contained
        within ``base`` after symlink resolution.
    """
    base_resolved = base.resolve()
    p = Path(candidate)
    if not p.is_absolute():
        p = base_resolved / p
    try:
        resolved = p.resolve()
    except Exception:
        return False, base_resolved
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        return False, base_resolved
    return True, resolved


def validate_glob_pattern(pattern: str) -> str:
    """Reject glob patterns that try to escape the base directory.

    Absolute paths and any component equal to ``..`` are rejected.
    Symlink escape is still possible at match time; callers should
    additionally filter ``Path.glob`` results through
    :func:`resolve_within`.

    Args:
        pattern: The glob expression as typed by the caller.

    Returns:
        The ``pattern`` unchanged on success.

    Raises:
        ValueError: If ``pattern`` is empty, absolute, or contains
            ``..``.
    """
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("Glob pattern must be a non-empty string.")
    p = Path(pattern)
    if p.is_absolute():
        raise ValueError("Absolute glob patterns are not permitted.")
    if ".." in p.parts:
        raise ValueError("Parent-directory '..' is not permitted in glob.")
    return pattern


# --- SSRF ----------------------------------------------------------------

_PRIVATE_IP_ERROR: str = (
    "URL resolves to a private, loopback, link-local, multicast, "
    "reserved, or unspecified address which is blocked by default. "
    "Pass allow_private_networks=True to override."
)


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """Return True if ``ip`` falls in a range SSRF callers must avoid."""
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def validate_public_url(
    url: str,
    allow_private_networks: bool = False,
    allowed_schemes: Tuple[str, ...] = ("http", "https"),
) -> str:
    """Validate ``url`` against the SSRF blocklist.

    The scheme must be in ``allowed_schemes`` and — unless the caller
    explicitly sets ``allow_private_networks=True`` — every address
    the hostname resolves to (all A/AAAA records) must be a public
    unicast address. Hostnames that fail to resolve are refused.

    Args:
        url: The full URL to validate.
        allow_private_networks: When True, skip the address-class
            check (still enforces the scheme allowlist). Use only for
            intranet/VPC targets that the deployer intends to reach.
        allowed_schemes: Tuple of lowercase URL schemes to accept.

    Returns:
        The ``url`` unchanged on success.

    Raises:
        ValueError: On any rule violation.
    """
    if not isinstance(url, str) or not url:
        raise ValueError("URL must be a non-empty string.")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in allowed_schemes:
        raise ValueError(f"URL scheme {parsed.scheme!r} is not in the allowlist {allowed_schemes!r}.")
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL {url!r} has no hostname.")
    if allow_private_networks:
        return url
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve host {host!r}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(ip):
            raise ValueError(f"{_PRIVATE_IP_ERROR} (host={host}, ip={ip})")
    return url


# --- Secrets -------------------------------------------------------------

_REDACTED: str = "***REDACTED***"


def redact_password(value: Optional[str]) -> str:
    """Return a fixed redacted marker for use in ``__repr__``.

    Returns an empty string when ``value`` is falsy so object reprs
    with no password set stay tidy (``password=`` rather than
    ``password=***REDACTED***``).

    Args:
        value: The original secret value, or None.

    Returns:
        ``"***REDACTED***"`` when ``value`` is truthy, else ``""``.
    """
    return _REDACTED if value else ""


def unwrap_secret(value: object) -> Optional[str]:
    """Extract the plain-text secret value from a ``SecretStr``-like input.

    Accepts any object exposing ``get_secret_value()`` (for example a
    ``pydantic.SecretStr``) as well as plain strings and ``None``.
    Avoids importing pydantic at module load time so the helper stays
    usable in lightweight contexts.

    Args:
        value: A ``SecretStr``, plain string, or ``None``.

    Returns:
        The underlying string, or ``None`` when ``value`` is ``None``.
    """
    if value is None:
        return None
    get_secret = getattr(value, "get_secret_value", None)
    if callable(get_secret):
        return get_secret()
    return str(value)
