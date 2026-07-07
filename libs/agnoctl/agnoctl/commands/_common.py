"""Helpers shared by CLI commands."""

import ipaddress
import os
import sys
from typing import Optional, Tuple
from urllib.parse import urlsplit

import typer

from agnoctl.errors import CLIError

ADMIN_TOKEN_ENV = "AGNO_ADMIN_TOKEN"
SECURITY_KEY_ENV = "OS_SECURITY_KEY"

_SERVER_NAME_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def validate_server_name(server_name: str) -> None:
    """MCP server entry names must stay flat: a dotted name would create nested TOML
    tables in Codex's config that later reads could never find."""
    if not server_name or not set(server_name) <= _SERVER_NAME_ALLOWED:
        raise CLIError(
            "Invalid --server-name: " + server_name,
            hint="Use letters, digits, '-' and '_' only.",
        )


def validate_project_name(name: str) -> None:
    """A project name becomes a directory under the CWD, so it must be a single flat path
    segment. Reject absolute paths, path separators, and '..' (which would let a scaffold
    escape the CWD or clobber an arbitrary directory) by holding it to the same
    conservative character set as MCP server names."""
    if not name or not set(name) <= _SERVER_NAME_ALLOWED:
        raise CLIError(
            "Invalid project name: " + name,
            hint="Use a single directory name of letters, digits, '-' and '_' only (no '/', '..' or absolute paths).",
        )


def _is_loopback_host(host: Optional[str]) -> bool:
    """True for hosts that never leave the machine: localhost, 127.0.0.0/8, ::1, and the
    unspecified addresses (0.0.0.0, ::) that dev servers bind to."""
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


def require_secure_url(url: str, *, allow_http: bool, what: str = "a credential") -> None:
    """Refuse to attach a bearer credential over plaintext HTTP to a non-loopback host.

    The admin token and freshly minted PATs are sent as ``Authorization: Bearer`` headers;
    over http:// to a remote host that hands the secret to anyone on the path. TLS is
    required unless the target is loopback (local dev) or the operator has explicitly
    opted in with ``--allow-http`` for a trusted private network.
    """
    if allow_http:
        return
    parts = urlsplit(url)
    if parts.scheme.lower() == "https":
        return
    if _is_loopback_host(parts.hostname):
        return
    raise CLIError(
        "Refusing to send " + what + " to " + url + " over plaintext HTTP.",
        hint="Use an https:// URL, or pass --allow-http to override on a trusted private network.",
    )


def resolve_admin_token(auth_mode: str, json_mode: bool) -> Optional[str]:
    """Resolve the admin credential used to call the service-accounts API.

    Order: AGNO_ADMIN_TOKEN env, OS_SECURITY_KEY env, interactive prompt. Prompting is
    disabled in --json mode and when stdin is not a TTY, so agent-driven runs fail with
    a clear instruction instead of hanging.
    """
    if auth_mode == "none":
        return None
    token = os.environ.get(ADMIN_TOKEN_ENV) or os.environ.get(SECURITY_KEY_ENV)
    if token:
        return token
    if json_mode or not sys.stdin.isatty():
        raise CLIError(
            "This AgentOS requires an admin credential to mint tokens (auth mode: " + auth_mode + ").",
            hint="Set " + ADMIN_TOKEN_ENV + " (or " + SECURITY_KEY_ENV + ") and re-run.",
        )
    return typer.prompt("Admin credential for this AgentOS", hide_input=True)


def stdin_is_interactive() -> bool:
    """Whether we can prompt the user. False in automation contexts (non-TTY); commands
    also treat --json as non-interactive. Wrapped so it can be stubbed in tests, where the
    runner swaps sys.stdin out from under a direct isatty patch."""
    return sys.stdin.isatty()


def parse_expires(value: str) -> Tuple[Optional[int], bool]:
    """Parse an --expires value into (expires_in_days, never_expires).

    Accepts a bare number of days ("90"), a d-suffixed form ("90d"), or "never".
    """
    cleaned = value.strip().lower()
    if cleaned == "never":
        return None, True
    if cleaned.endswith("d"):
        cleaned = cleaned[:-1]
    if not cleaned.isdigit() or int(cleaned) < 1:
        raise CLIError(
            "Invalid --expires value: " + value,
            hint="Use a number of days like '90' or '90d', or 'never'.",
        )
    return int(cleaned), False


def handle_cli_error(error: CLIError, json_mode: bool) -> "typer.Exit":
    """Print a CLIError appropriately for the output mode and return the Exit to raise."""
    from agnoctl.console import emit_json, print_error, print_warning

    if json_mode:
        payload = {"error": error.message}
        if error.hint:
            payload["hint"] = error.hint
        emit_json(payload)
    else:
        print_error(error.message)
        if error.hint:
            print_warning(error.hint)
    return typer.Exit(error.exit_code)
