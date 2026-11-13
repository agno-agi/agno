"""`agno login`, `agno logout` and `agno os register`: connect the CLI and a deployed
AgentOS to the AgentOS control plane (os.agno.com)."""

import os
import socket
import webbrowser
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

import typer

from agnoctl.cloud import (
    CLOUD_APP_URL,
    CloudAPI,
    credentials_path,
    delete_credentials,
    save_credentials,
)
from agnoctl.commands._common import handle_cli_error, stdin_is_interactive
from agnoctl.console import console, emit_json, err_console, print_info, print_success, shorten_home
from agnoctl.discovery import URL_ENV_VAR, _agentos_url_from_env_files, _is_loopback_host
from agnoctl.errors import CLIError
from agnoctl.http import AgentOSAPI

JWKS_URL_ENV = "JWT_JWKS_URL"
DEFAULT_ENV_FILE = ".env.production"

JsonOption = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption.")

os_app = typer.Typer(name="os", help="Register a deployed AgentOS on " + CLOUD_APP_URL + ".")


def login(
    api_url: Optional[str] = typer.Option(
        None,
        "--api-url",
        help="Control-plane API to sign in to, e.g. https://os-api-stg.agno.com. Later commands use the same one.",
    ),
    no_browser: bool = typer.Option(False, "--no-browser", help="Print the login URL instead of opening a browser."),
    json_output: bool = JsonOption,
) -> None:
    """Sign in to os.agno.com. Approve the login in a browser; the CLI waits."""
    try:
        with CloudAPI(api_url=api_url) as api:
            device = api.start_device_login()
            url = device.verification_uri_complete or device.verification_uri
            # stdout is reserved for the JSON result, so instructions go to stderr in both modes.
            err_console.print("Open " + url + " to sign in.", highlight=False)
            err_console.print("Confirm that the page shows the code " + device.user_code + ".", highlight=False)
            if not no_browser and not json_output and stdin_is_interactive():
                webbrowser.open(url)
            credentials = api.wait_for_device_login(device)
        path = save_credentials(credentials)
    except CLIError as e:
        raise handle_cli_error(e, json_output)

    if json_output:
        emit_json(
            {
                "api_url": credentials.api_url,
                "email": credentials.email,
                "organization_id": credentials.organization_id,
                "credentials_file": str(path),
            }
        )
        return
    print_success("Signed in to " + CLOUD_APP_URL + " as " + (credentials.email or "unknown user") + ".")
    print_info("Login saved to " + shorten_home(str(path)) + ".")


def logout(json_output: bool = JsonOption) -> None:
    """Delete the stored os.agno.com login from this machine."""
    removed = delete_credentials()
    if json_output:
        emit_json({"logged_out": removed, "credentials_file": str(credentials_path())})
        return
    print_info("Signed out." if removed else "You were not signed in.")


def upsert_env_value(path: Path, key: str, value: str) -> None:
    """Set KEY=value in a .env file, replacing every uncommented assignment of KEY.

    Other lines are kept as written. A new file is created readable only by the user,
    since production env files hold secrets.
    """
    lines: List[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    assignment = key + "=" + value
    replaced = False
    out: List[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("export ") or stripped.startswith("export\t"):
            stripped = stripped[len("export") :].lstrip()
        name, sep, _ = stripped.partition("=")
        if sep and name.strip() == key:
            if not replaced:
                out.append(assignment)
                replaced = True
            continue
        out.append(raw)
    if not replaced:
        out.append(assignment)
    if not path.exists():
        os.close(os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _default_name(url: str) -> str:
    """The AgentOS name from /info, falling back to the URL's host."""
    with AgentOSAPI(url, timeout=5.0) as api:
        info = api.info() or {}
    name = info.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return urlsplit(url).hostname or socket.gethostname()


def _resolve_url(url: Optional[str]) -> str:
    if url:
        return url.rstrip("/")
    env_url = os.environ.get(URL_ENV_VAR)
    if env_url:
        return env_url.rstrip("/")
    file_url, _ = _agentos_url_from_env_files()
    if file_url:
        return file_url
    raise CLIError(
        "No AgentOS URL to register.",
        hint="Pass --url, or set " + URL_ENV_VAR + " in the environment or " + DEFAULT_ENV_FILE + ".",
    )


@os_app.command("register")
def register(
    url: Optional[str] = typer.Option(
        None, "--url", help="Public URL of the deployed AgentOS. Default: AGENTOS_URL, then .env.production/.env."
    ),
    name: Optional[str] = typer.Option(None, "--name", help="Display name. Default: the AgentOS name, then the host."),
    env_file: Path = typer.Option(
        Path(DEFAULT_ENV_FILE), "--env-file", help="Env file that receives " + JWKS_URL_ENV + "."
    ),
    no_env_file: bool = typer.Option(False, "--no-env-file", help="Print the JWKS URL without writing a file."),
    json_output: bool = JsonOption,
) -> None:
    """Register an AgentOS on os.agno.com and write its JWKS URL to the env file.

    Running it again for the same URL reuses the existing registration. The AgentOS
    verifies os.agno.com tokens once it restarts with JWT_JWKS_URL set.
    """
    try:
        target = _resolve_url(url)
        parts = urlsplit(target)
        # The AgentOS UI calls the OS from the browser, so a local OS is valid. A remote
        # one must use TLS, since the browser sends it tokens.
        if parts.scheme != "https" and not _is_loopback_host(parts.hostname):
            raise CLIError(
                "A remote AgentOS must use an https:// URL, not " + target + ".",
            )
        with CloudAPI.logged_in() as api:
            registered = api.find_operating_system(target)
            created = registered is None
            if registered is None:
                registered = api.create_operating_system(name or _default_name(target), target)
            elif not registered.enabled_jwt:
                raise CLIError(
                    "'" + registered.name + "' is already registered without JWT token provisioning.",
                    hint="Enable JWT for it in the AgentOS UI on " + CLOUD_APP_URL + ", then run this again.",
                )
            jwks_url = api.jwks_url(registered.id)
        if not no_env_file:
            upsert_env_value(env_file, JWKS_URL_ENV, jwks_url)
    except CLIError as e:
        raise handle_cli_error(e, json_output)

    if json_output:
        emit_json(
            {
                "os_id": registered.id,
                "name": registered.name,
                "endpoint_url": registered.endpoint_url,
                "created": created,
                "jwks_url": jwks_url,
                "env_file": None if no_env_file else str(env_file),
            }
        )
        return
    verb = "Registered" if created else "Found"
    print_success(verb + " '" + registered.name + "' on " + CLOUD_APP_URL + " (id " + registered.id + ").")
    if no_env_file:
        console.print(JWKS_URL_ENV + "=" + jwks_url, highlight=False)
    else:
        print_info("Wrote " + JWKS_URL_ENV + " to " + str(env_file) + ".")
    print_info("Redeploy the AgentOS so it picks up " + JWKS_URL_ENV + ".")
