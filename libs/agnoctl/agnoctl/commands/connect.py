"""`agno connect`: wire a running AgentOS into coding agents as an MCP server.

Flow: discover the AgentOS -> resolve admin credential -> mint one service account per
client -> write each client's MCP config -> read the config back and verify the entry
the client will actually use, with a real MCP tools/list call -> report. Re-runs are
safe: entries that already verify are skipped, broken or stale ones are rotated.
"""

import ipaddress
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import typer

from agnoctl.clients import CLIENT_ALIASES, build_adapters
from agnoctl.clients.base import ClientAdapter
from agnoctl.commands._common import (
    _is_loopback_host,
    handle_cli_error,
    parse_expires,
    require_secure_url,
    resolve_admin_token,
    validate_server_name,
)
from agnoctl.console import emit_json, print_error, print_info, print_success, print_warning
from agnoctl.discovery import MCP_ENABLE_INSTRUCTIONS, OSInfo, discover
from agnoctl.errors import CLIError, ConflictError
from agnoctl.http import AgentOSAPI, ServiceAccount
from agnoctl.mcp_client import verify_mcp

# Exit codes: 0 = all connected, 1 = nothing connected, 2 = usage error (click's
# convention, raised by typer itself), 3 = partial success.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_PARTIAL = 3

ROTATE_HINT = "Re-run with --rotate to revoke and re-mint it, or --skip-existing to leave it untouched."

# The hosted chat apps (Claude, ChatGPT) are not ClientAdapters: they have no local
# config to write and nothing agnoctl can verify (the connector is added later, by a
# human, in the app's own UI). They are handled out of band as printed setup
# instructions: opt-in via --clients, and included automatically when the AgentOS is on
# a public URL the apps' clouds can actually reach.
CHAT_APP_ALIASES = {
    "claude-ai": "claude-ai",
    "claudeai": "claude-ai",
    "claude.ai": "claude-ai",
    "chatgpt": "chatgpt",
    "gpt": "chatgpt",
    "openai": "chatgpt",
}
# One registry entry per chat app: (UI name, where-to-add-it instructions). Adding an
# app here is the whole job -- CHAT_APPS and the instruction text derive from it.
CHAT_APPS_SPEC = {
    "claude-ai": (
        "Claude",
        "In claude.ai or the Claude desktop app: Settings -> Connectors -> Add custom connector, "
        "paste the MCP URL below, and follow the prompts (custom connectors need a paid plan).",
    ),
    "chatgpt": (
        "ChatGPT",
        "In ChatGPT: Settings -> Connectors -> Add custom connector, paste the MCP URL below, and follow "
        "the prompts (custom connectors need a paid plan; enable Developer Mode for full tool access).",
    ),
}
CHAT_APPS = tuple(CHAT_APPS_SPEC)


def _split_chat_apps(clients: Optional[str]) -> "tuple[Optional[str], List[str]]":
    """Peel chat-app requests out of --clients; returns (remaining clients, wanted apps)."""
    if not clients:
        return clients, []
    tokens = [t.strip() for t in clients.split(",") if t.strip()]
    remaining = [t for t in tokens if t.lower() not in CHAT_APP_ALIASES]
    wanted: List[str] = []
    for token in tokens:
        app = CHAT_APP_ALIASES.get(token.lower())
        if app is not None and app not in wanted:
            wanted.append(app)
    return (",".join(remaining) if remaining else None), wanted


def _reachable_from_cloud(os_info: OSInfo) -> bool:
    """True when the hosted chat apps can plausibly reach this AgentOS: public HTTPS.

    Judged on the parsed hostname, not a substring scan of the URL, so tunnel domains
    like *.localhost.run count as cloud-reachable while loopback, RFC1918/link-local
    addresses, and container-internal hosts do not.
    """
    if not os_info.mcp_url.lower().startswith("https://"):
        return False
    host = urlsplit(os_info.base_url).hostname or ""
    if _is_loopback_host(host) or host.lower() == "host.docker.internal":
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a named host on HTTPS: assume public
    return not (ip.is_private or ip.is_link_local)


def _chat_app_instructions(app: str, os_info: OSInfo) -> Dict[str, Any]:
    """A manual-setup result for a hosted chat app: honest steps, never a verified connection."""
    ui_name, where = CHAT_APPS_SPEC[app]
    note = None
    if not _reachable_from_cloud(os_info):
        note = (
            ui_name
            + " adds connectors from its own cloud and cannot reach a local AgentOS at "
            + os_info.base_url
            + "; deploy it behind a public HTTPS URL (or a tunnel) before adding it."
        )
    return {
        "client": app,
        "status": "manual",
        "error": None,
        "url": os_info.mcp_url,
        "instructions": [
            ui_name + " reaches MCP servers from its cloud, so the AgentOS must be on a public HTTPS URL.",
            ui_name + "'s Connectors UI authenticates with OAuth, not bearer tokens, so a token-protected "
            "AgentOS cannot be added from the UI yet; use a public or OAuth-enabled AgentOS.",
            where,
        ],
        "note": note,
    }


def _resolve_clients(
    clients: Optional[str], adapters: Dict[str, ClientAdapter], required: bool = True
) -> List[ClientAdapter]:
    if clients:
        selected: List[ClientAdapter] = []
        for raw in clients.split(","):
            key = CLIENT_ALIASES.get(raw.strip().lower())
            if key is None:
                supported = ", ".join(sorted(set(CLIENT_ALIASES.keys()) | set(CHAT_APP_ALIASES.keys())))
                raise CLIError("Unknown client: " + raw.strip(), hint="Supported clients: " + supported)
            adapter = adapters[key]
            if adapter not in selected:
                selected.append(adapter)
        return selected
    detected = [adapter for adapter in adapters.values() if adapter.detect()]
    if not detected and required:
        # ``required=False`` when the run has something else to report (the chat-app
        # auto-surface on a deployed AgentOS) -- a headless deploy box with no local
        # clients is that feature's primary home, so it must not die here.
        raise CLIError(
            "No supported clients detected on this machine.",
            hint="Install Claude Code, Claude Desktop, Codex, or Cursor, or pass --clients explicitly.",
        )
    return detected


def _mint(
    api: AgentOSAPI,
    account_name: str,
    scopes: Optional[List[str]],
    expires_in_days: Optional[int],
    never_expires: bool,
    privileged: bool,
    rotate: bool,
    skip_existing: bool,
    json_mode: bool,
) -> Optional[ServiceAccount]:
    """Mint a service account, resolving name conflicts per the idempotency policy.

    Returns None when the caller should skip this client (existing account kept).
    """
    try:
        return api.create_service_account(
            name=account_name,
            scopes=scopes,
            expires_in_days=expires_in_days,
            never_expires=never_expires,
            allow_privileged_scopes=privileged,
        )
    except ConflictError as e:
        if skip_existing:
            return None
        if not rotate:
            interactive = not json_mode and sys.stdin.isatty()
            if not interactive:
                e.hint = ROTATE_HINT
                raise
            if not typer.confirm(
                "Service account '" + account_name + "' already exists. Revoke and re-mint it?", default=False
            ):
                return None
        existing = api.find_service_account(account_name)
        if existing is not None:
            api.revoke_service_account(existing.id)
        return api.create_service_account(
            name=account_name,
            scopes=scopes,
            expires_in_days=expires_in_days,
            never_expires=never_expires,
            allow_privileged_scopes=privileged,
        )


def connect(
    url: Optional[str] = typer.Option(None, "--url", help="AgentOS base URL (default: autodiscover on localhost)."),
    clients: Optional[str] = typer.Option(
        None,
        "--clients",
        help=(
            "Comma-separated clients (claude-code,claude-desktop,codex,cursor; claude-ai and chatgpt "
            "print manual setup steps). Default: detected, plus claude-ai/chatgpt steps when the "
            "AgentOS is on a public URL."
        ),
    ),
    name: Optional[str] = typer.Option(
        None, "--name", help="Use one shared service account with this name instead of one per client."
    ),
    scopes: List[str] = typer.Option(
        [], "--scopes", "-s", help="Scope to grant (repeatable). Default: the server's run + read scopes."
    ),
    expires: str = typer.Option("90d", "--expires", help="Token lifetime in days ('90d', '30') or 'never'."),
    privileged: bool = typer.Option(
        False, "--privileged", help="Required when --scopes grants write/delete/admin or service_accounts scopes."
    ),
    server_name: str = typer.Option("agno", "--server-name", help="MCP server entry name written to client configs."),
    project: bool = typer.Option(
        False, "--project", help="Write project-scoped configs (.mcp.json / .cursor/mcp.json) instead of user-level."
    ),
    rotate: bool = typer.Option(False, "--rotate", help="Revoke and re-mint existing accounts without asking."),
    skip_existing: bool = typer.Option(
        False, "--skip-existing", help="Never touch existing accounts or config entries."
    ),
    allow_http: bool = typer.Option(
        False, "--allow-http", help="Permit sending credentials over plaintext HTTP to a non-loopback host."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption."),
) -> None:
    """Connect this machine's coding agents to a running AgentOS over MCP."""
    try:
        _connect(
            url=url,
            clients=clients,
            name=name,
            scopes=list(scopes) or None,
            expires=expires,
            privileged=privileged,
            server_name=server_name,
            project=project,
            rotate=rotate,
            skip_existing=skip_existing,
            allow_http=allow_http,
            json_mode=json_output,
        )
    except CLIError as e:
        raise handle_cli_error(e, json_output)


def _connect(
    url: Optional[str],
    clients: Optional[str],
    name: Optional[str],
    scopes: Optional[List[str]],
    expires: str,
    privileged: bool,
    server_name: str,
    project: bool,
    rotate: bool,
    skip_existing: bool,
    allow_http: bool,
    json_mode: bool,
) -> None:
    validate_server_name(server_name)
    expires_in_days, never_expires = parse_expires(expires)

    os_info = discover(url)
    if not os_info.mcp_enabled:
        raise CLIError(
            "Found an AgentOS at "
            + os_info.base_url
            + ", but its MCP server is not enabled.\n\n"
            + MCP_ENABLE_INSTRUCTIONS
        )
    if not json_mode:
        version = " (agno " + os_info.version + ")" if os_info.version else ""
        source = " (from AGENTOS_URL)" if os_info.url_source == "env" else ""
        print_info("AgentOS at " + os_info.base_url + version + source + ", MCP at " + os_info.mcp_url)

    adapters = build_adapters(project=project)
    clients_remaining, wanted_apps = _split_chat_apps(clients)
    # Auto-surface the hosted chat apps only when the run wasn't scoped by --clients AND
    # the deployed OS is one they can actually add: public HTTPS and no token gate (their
    # Connectors UIs authenticate with OAuth, not bearer tokens). Explicitly requested
    # chat apps are honored regardless -- their instructions carry the caveats.
    auto_surface_apps = clients is None and os_info.auth_mode == "none" and _reachable_from_cloud(os_info)
    # Auto-detect only when no --clients was given; a chat-app-only request selects no adapters.
    selected = (
        _resolve_clients(clients_remaining, adapters, required=not auto_surface_apps)
        if clients is None or clients_remaining
        else []
    )

    minting = os_info.auth_mode not in ("none",) and bool(selected)
    # When we mint, the admin token is attached to base_url and the minted PATs are written
    # into client configs and sent to the (same-origin) MCP URL. Refuse to do any of that
    # over plaintext HTTP to a non-loopback host unless the operator opted in.
    if minting:
        require_secure_url(os_info.base_url, allow_http=allow_http, what="the admin credential and minted tokens")
    admin_token = resolve_admin_token(os_info.auth_mode, json_mode) if minting else None
    if not minting and selected and not json_mode:
        print_info("Authorization is disabled on this AgentOS; connecting without credentials.")

    # Truthful-outcome check: if the OS enforces auth but /mcp answers without a token,
    # the server predates MCP token enforcement and minted headers are decorative.
    open_mcp_warning: Optional[str] = None
    if minting:
        open_probe = verify_mcp(os_info.mcp_url, token=None)
        if open_probe.ok:
            open_mcp_warning = (
                "This AgentOS accepts unauthenticated MCP requests: its agno version predates "
                "token enforcement on /mcp. Tokens were still minted and configured; upgrade "
                "agno to make them meaningful."
            )

    api = AgentOSAPI(os_info.base_url, admin_token=admin_token) if minting else None

    results: List[Dict[str, Any]] = []

    try:
        # Shared-account mode: resolve the token once, before any config is touched --
        # clients then only write configs, and none of them can hit a name conflict
        # that would re-mint (and revoke) the shared token mid-run.
        shared_token: Optional[str] = None
        if name is not None and minting and api is not None:
            shared_token = _resolve_shared_token(
                api=api,
                adapters=selected,
                os_info=os_info,
                server_name=server_name,
                name=name,
                scopes=scopes,
                expires_in_days=expires_in_days,
                never_expires=never_expires,
                privileged=privileged,
                rotate=rotate,
                skip_existing=skip_existing,
                json_mode=json_mode,
            )
        for adapter in selected:
            result: Dict[str, Any] = {"client": adapter.key, "status": "failed", "error": None}
            try:
                _connect_one(
                    adapter=adapter,
                    result=result,
                    os_info=os_info,
                    api=api,
                    server_name=server_name,
                    name=name,
                    scopes=scopes,
                    expires_in_days=expires_in_days,
                    never_expires=never_expires,
                    privileged=privileged,
                    rotate=rotate,
                    skip_existing=skip_existing,
                    json_mode=json_mode,
                    minting=minting,
                    shared_token=shared_token,
                )
            except CLIError as e:
                result["error"] = e.message + ((" " + e.hint) if e.hint else "")
            except Exception as e:  # one client's failure must never abort the run
                result["error"] = "Unexpected error (" + type(e).__name__ + "): " + str(e)
            results.append(result)
    finally:
        if api is not None:
            api.close()

    # Spot a deployed AgentOS: when discovery lands on a public, token-free URL (typically
    # AGENTOS_URL set to the production domain), the hosted chat apps can use it too --
    # surface their setup steps without requiring --clients.
    if auto_surface_apps:
        wanted_apps = list(CHAT_APPS)
    for app in wanted_apps:
        results.append(_chat_app_instructions(app, os_info))

    _report(os_info, results, server_name, open_mcp_warning, json_mode)


def _resolve_shared_token(
    api: AgentOSAPI,
    adapters: List[ClientAdapter],
    os_info: OSInfo,
    server_name: str,
    name: str,
    scopes: Optional[List[str]],
    expires_in_days: Optional[int],
    never_expires: bool,
    privileged: bool,
    rotate: bool,
    skip_existing: bool,
    json_mode: bool,
) -> Optional[str]:
    """The one token every client shares in --name mode, resolved before any config write.

    Reuse first: the CLI stores no tokens, so a token already configured for this OS in
    any selected client (and verified against /mcp) IS the shared account's token.
    Minting happens only when no client holds a working one; name conflicts resolve per
    the idempotency policy in _mint. Returns None when the account exists and the
    policy says keep it untouched (clients that need a token then report skipped).
    """
    if not rotate:
        for adapter in adapters:
            existing = adapter.read_existing(server_name)
            if existing is None or existing.url != os_info.mcp_url or existing.token is None:
                continue
            if verify_mcp(os_info.mcp_url, token=existing.token).ok:
                return existing.token
    account = _mint(
        api,
        name,
        scopes,
        expires_in_days,
        never_expires,
        privileged=privileged,
        rotate=rotate,
        skip_existing=skip_existing,
        json_mode=json_mode,
    )
    return account.token if account is not None else None


def _connect_one(
    adapter: ClientAdapter,
    result: Dict[str, Any],
    os_info: OSInfo,
    api: Optional[AgentOSAPI],
    server_name: str,
    name: Optional[str],
    scopes: Optional[List[str]],
    expires_in_days: Optional[int],
    never_expires: bool,
    privileged: bool,
    rotate: bool,
    skip_existing: bool,
    json_mode: bool,
    minting: bool,
    shared_token: Optional[str],
) -> None:
    account_name = name or adapter.key
    existing = adapter.read_existing(server_name)

    if existing is not None:
        if existing.url == os_info.mcp_url and not rotate:
            # Idempotency: an entry already pointing at this OS that still verifies is left alone.
            check = verify_mcp(os_info.mcp_url, token=existing.token)
            if check.ok and (existing.token is not None or not minting):
                result.update(status="already-connected", location=existing.location, verify=check.public_dict())
                return
            if skip_existing:
                result.update(
                    status="skipped",
                    error="Existing entry no longer verifies; re-run without --skip-existing to rotate.",
                )
                return
        elif existing.url != os_info.mcp_url:
            # The entry points at a different AgentOS; never touch it under --skip-existing.
            if skip_existing:
                result.update(
                    status="skipped",
                    location=existing.location,
                    error="Existing entry points at " + existing.url + "; left untouched.",
                )
                return
            result["replaced_url"] = existing.url

    token: Optional[str] = None
    account: Optional[ServiceAccount] = None
    if minting and api is not None:
        if name is not None:
            if shared_token is None:
                result.update(status="skipped", error="Service account exists; kept untouched.")
                return
            token = shared_token
        else:
            account = _mint(
                api,
                account_name,
                scopes,
                expires_in_days,
                never_expires,
                privileged=privileged,
                rotate=rotate,
                skip_existing=skip_existing,
                json_mode=json_mode,
            )
            if account is None:
                result.update(status="skipped", error="Service account exists; kept untouched.")
                return
            token = account.token

    write_result = adapter.write(server_name, os_info.mcp_url, token)
    result["location"] = write_result.location
    if write_result.note:
        result["note"] = write_result.note
    if account is not None:
        result["account"] = account.public_dict()

    # Verify what the client will actually use, not what we intended to write: the
    # read-back catches shadowing entries and writes that silently did not take effect.
    readback = adapter.read_existing(server_name)
    if readback is None or readback.url != os_info.mcp_url or (token is not None and readback.token != token):
        found = (readback.location + " -> " + readback.url) if readback is not None else "no entry"
        result["error"] = (
            "The config write did not take effect for '" + server_name + "' (found: " + found + "). "
            "Another entry may shadow it; remove the stale entry and re-run."
        )
        return

    verify_result = verify_mcp(os_info.mcp_url, token=readback.token)
    result["verify"] = verify_result.public_dict()
    if verify_result.ok:
        result["status"] = "connected"
        # A client that was already configured with a *different* token still holds the
        # old one in its live, in-process MCP connection: it keeps using the now-revoked
        # token until it is restarted. Flag it so the report can say so.
        if existing is not None and existing.token is not None and token is not None and existing.token != token:
            result["rotated"] = True
    else:
        result["error"] = verify_result.error


def _report(
    os_info: OSInfo,
    results: List[Dict[str, Any]],
    server_name: str,
    open_mcp_warning: Optional[str],
    json_mode: bool,
) -> None:
    # "manual" (chat-app instructions) is not a failure: agnoctl did all it can. But it
    # must not mask one either -- when every real adapter failed, appended manual
    # entries cannot soften total failure into "partial".
    ok_statuses = ("connected", "already-connected", "manual")
    ok_count = sum(1 for r in results if r["status"] in ok_statuses)
    real_results = [r for r in results if r["status"] != "manual"]
    real_ok = sum(1 for r in real_results if r["status"] in ok_statuses)
    if ok_count == len(results):
        exit_code = EXIT_OK
    elif real_results and real_ok == 0:
        exit_code = EXIT_FAILURE
    else:
        exit_code = EXIT_PARTIAL

    if json_mode:
        emit_json(
            {
                "os": os_info.public_dict(),
                "server_name": server_name,
                "results": results,
                "warning": open_mcp_warning,
                "exit_code": exit_code,
            }
        )
        raise typer.Exit(exit_code)

    print_info("")
    for r in results:
        label = r["client"]
        if r["status"] == "connected":
            tools = (r.get("verify") or {}).get("tools")
            suffix = " (" + str(tools) + " tools)" if tools else ""
            print_success("  connected      " + label + suffix + "  ->  " + str(r.get("location", "")))
        elif r["status"] == "already-connected":
            print_success("  already ok     " + label + "  ->  " + str(r.get("location", "")))
        elif r["status"] == "skipped":
            print_warning("  skipped        " + label + "  (" + str(r.get("error") or "") + ")")
        elif r["status"] == "manual":
            ui_name = CHAT_APPS_SPEC[label][0] if label in CHAT_APPS_SPEC else label
            print_warning("  action needed  " + label + "  (set up in the " + ui_name + " UI)")
            for step in r.get("instructions", []):
                print_info("                 - " + step)
            if r.get("url"):
                print_info("                 MCP URL: " + str(r["url"]))
        else:
            print_error("  failed         " + label + "  (" + str(r.get("error") or "unknown error") + ")")
        if r.get("note"):
            print_warning("                 note: " + str(r["note"]))
        if r.get("replaced_url"):
            print_warning("                 replaced an entry that pointed at " + str(r["replaced_url"]))

    if any(r.get("rotated") for r in results):
        print_info("")
        print_warning(
            "A token was rotated. Restart the affected coding agent(s) so they reconnect with the "
            "new token — a running client keeps using the previous (now revoked) token until it does."
        )

    accounts = sorted({r["account"]["name"] for r in results if r.get("account")})
    if accounts:
        print_info("")
        print_info("Revoke any time with: agno tokens revoke <name>  (accounts: " + ", ".join(accounts) + ")")
    if open_mcp_warning:
        print_info("")
        print_warning(open_mcp_warning)

    raise typer.Exit(exit_code)
