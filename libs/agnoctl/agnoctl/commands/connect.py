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
from rich.status import Status

from agnoctl.clients import CLIENT_ALIASES, build_adapters, configured_sources, display_name
from agnoctl.clients.base import ClientAdapter
from agnoctl.commands._common import (
    ADMIN_TOKEN_ENV,
    LEGACY_SERVER_NAME,
    PAT_PREFIX,
    _is_loopback_host,
    derive_server_name,
    ensure_env_file_url_trusted,
    env_admin_credential,
    handle_cli_error,
    parse_expires,
    require_mint_capable,
    require_secure_url,
    resolve_admin_token,
    stdin_is_interactive,
    validate_server_name,
)
from agnoctl.console import console, emit_json, print_error, print_info, print_success, print_warning, shorten_home
from agnoctl.discovery import (
    MCP_ENABLE_INSTRUCTIONS,
    OSInfo,
    _agentos_url_from_env_files,
    discover,
    discover_all,
)
from agnoctl.errors import APIError, CLIError, ConflictError
from agnoctl.http import AgentOSAPI, ServiceAccount
from agnoctl.mcp_client import verify_mcp

# Exit codes: 0 = all connected, 1 = nothing connected, 2 = usage error (click's
# convention, raised by typer itself), 3 = partial success.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_PARTIAL = 3

DEFAULT_EXPIRES = "90d"


def exit_code_for(results: List[Dict[str, Any]], ok_statuses: "tuple[str, ...]") -> int:
    """0 = every result ok, 1 = every real result failed, 3 = mixed. "manual" rows
    (chat-app instructions) count as ok but can neither rescue nor mask the real
    adapters' outcomes: when every real adapter failed, appended manual entries must
    not soften total failure into partial."""
    ok_count = sum(1 for r in results if r["status"] in ok_statuses)
    real_results = [r for r in results if r["status"] != "manual"]
    real_ok = sum(1 for r in real_results if r["status"] in ok_statuses)
    if ok_count == len(results):
        return EXIT_OK
    if real_results and real_ok == 0:
        return EXIT_FAILURE
    return EXIT_PARTIAL


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

# The one-time sign-in each client runs after a tokenless entry is written for an
# OAuth-protected MCP endpoint. {server} is the entry name.
OAUTH_SIGNIN_STEPS = {
    "claude-code": "Run: claude mcp login {server}  (or /mcp -> Authenticate inside a session)",
    "claude-desktop": "Restart Claude Desktop; mcp-remote opens the browser sign-in automatically",
    "codex": "Run: codex mcp login {server}",
    "cursor": "Open Cursor Settings -> MCP and click Connect on '{server}'",
}


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
    if os_info.oauth_enabled:
        auth_line = (
            "This AgentOS's MCP endpoint supports OAuth sign-in, which is exactly how "
            + ui_name
            + "'s Connectors UI authenticates: you will be asked to authorize when adding the connector."
        )
    else:
        auth_line = (
            ui_name + "'s Connectors UI authenticates with OAuth, not bearer tokens, so a token-protected "
            "AgentOS cannot be added from the UI yet; use a public or OAuth-enabled AgentOS."
        )
    return {
        "client": app,
        "status": "manual",
        "error": None,
        "url": os_info.mcp_url,
        "instructions": [
            ui_name + " reaches MCP servers from its cloud, so the AgentOS must be on a public HTTPS URL.",
            auth_line,
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
    status: Optional["Status"] = None,
) -> Optional[ServiceAccount]:
    """Mint a service account, resolving name conflicts per the idempotency policy.

    Returns None when the caller should skip this client (existing account kept).
    A live progress spinner is paused around the conflict prompt so it can be read.
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
            if status is not None:
                status.stop()
            confirmed = typer.confirm(
                "Service account '" + account_name + "' already exists. Revoke and re-mint it?", default=False
            )
            if status is not None:
                status.start()
            if not confirmed:
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
    url: Optional[str] = typer.Option(
        None, "--url", help="AgentOS base URL. Default: AGENTOS_URL, then .env.production/.env, then localhost."
    ),
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
    expires: str = typer.Option(DEFAULT_EXPIRES, "--expires", help="Token lifetime in days ('90d', '30') or 'never'."),
    privileged: bool = typer.Option(
        False, "--privileged", help="Required when --scopes grants write/delete/admin or service_accounts scopes."
    ),
    pat: bool = typer.Option(
        False,
        "--pat",
        help="Mint service-account tokens even when the MCP endpoint is OAuth-protected (for headless clients).",
    ),
    server_name: Optional[str] = typer.Option(
        None,
        "--server-name",
        help="MCP server entry name written to client configs. Default: derived from the AgentOS name.",
    ),
    project: bool = typer.Option(
        False, "--project", help="Write project-scoped configs (.mcp.json / .cursor/mcp.json) instead of user-level."
    ),
    rotate: bool = typer.Option(
        False,
        "--rotate",
        help=(
            "Rewrite existing entries without asking: revoke and re-mint their accounts, "
            "or convert them to OAuth sign-in on an OAuth-protected OS."
        ),
    ),
    skip_existing: bool = typer.Option(
        False, "--skip-existing", help="Never touch existing accounts or config entries."
    ),
    allow_http: bool = typer.Option(
        False, "--allow-http", help="Permit sending credentials over plaintext HTTP to a remote host."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Trust a remote AGENTOS_URL from a .env file without prompting."
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
            pat=pat,
            server_name=server_name,
            project=project,
            rotate=rotate,
            skip_existing=skip_existing,
            allow_http=allow_http,
            assume_yes=yes,
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
    pat: bool,
    server_name: Optional[str],
    project: bool,
    rotate: bool,
    skip_existing: bool,
    allow_http: bool,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    if server_name is not None:
        validate_server_name(server_name)
    expires_in_days, never_expires = parse_expires(expires)

    # Interactive runs may choose among every live AgentOS; non-interactive runs
    # (--json / no TTY) resolve the single highest-priority target, so automation is
    # deterministic and a dead env-file OS is a hard failure, never a silent retarget.
    interactive = not json_mode and stdin_is_interactive()
    if interactive:
        # The client configs are the durable record of previously connected OSes, so
        # the picker offers those too (e.g. a deployed OS connected last week vs the
        # local one running now). Non-interactive runs never see these candidates.
        candidates = discover_all(url, extra_sources=configured_sources(build_adapters(project=project)))
        os_info = _select_os(candidates, verb="connect")
        if url is None and not any(c.url_source == "env-file" for c in candidates):
            file_url, file_name = _agentos_url_from_env_files()
            if file_url:
                print_warning("Note: AGENTOS_URL in " + str(file_name) + " (" + file_url + ") did not answer.")
    else:
        os_info = discover(url)
    # Before anything sensitive (minting, config writes), confirm an off-machine URL that
    # came from an ambient .env file -- it could be redirecting us from an untrusted dir.
    ensure_env_file_url_trusted(
        os_info.base_url, os_info.url_source, os_info.url_source_file, assume_yes=assume_yes, json_mode=json_mode
    )
    if not os_info.mcp_enabled:
        raise CLIError(
            "Found an AgentOS at "
            + os_info.base_url
            + ", but its MCP server is not enabled.\n\n"
            + MCP_ENABLE_INSTRUCTIONS
        )
    # The entry name carries the OS's identity (its /info name) unless the operator chose
    # one. legacy_name marks runs where entries named "agno" (agnoctl 0.1.x) that point at
    # this OS get renamed in place; their token is reused only for a default mint (custom
    # --scopes/--expires means the operator wants a freshly provisioned account).
    legacy_name: Optional[str] = None
    if server_name is None:
        server_name = derive_server_name(os_info.name)
        if server_name != LEGACY_SERVER_NAME and not skip_existing:
            legacy_name = LEGACY_SERVER_NAME
    legacy_token_reuse = scopes is None and expires == DEFAULT_EXPIRES

    # OAuth-first: when /mcp is OAuth-protected, apps sign in through the authorization
    # server themselves -- entries are written without tokens and nothing is minted.
    # --pat opts back into minted bearers (the server accepts both) for headless clients.
    oauth_mode = os_info.oauth_enabled and not pat

    # Mint-shaping flags describe a token an OAuth run never mints; erroring beats
    # silently writing tokenless entries whose effective access comes from the
    # authorization server's grant instead of the flags.
    if oauth_mode:
        shaping = [
            flag
            for flag, used in (
                ("--name", name is not None),
                ("--scopes", scopes is not None),
                ("--expires", expires != DEFAULT_EXPIRES),
                ("--privileged", privileged),
            )
            if used
        ]
        if shaping:
            raise CLIError(
                ", ".join(shaping) + " only shape minted tokens, but this AgentOS's MCP endpoint is "
                "OAuth-protected: apps sign in through the authorization server and nothing is minted.",
                hint="Add --pat to mint service-account tokens anyway (for headless clients), or drop "
                + ", ".join(shaping)
                + ".",
            )

    if not json_mode:
        version = " (agno " + os_info.version + ")" if os_info.version else ""
        source = os_info.source_note()
        os_label = '"' + os_info.name + '" ' if os_info.name else ""
        print_info("AgentOS " + os_label + "at " + os_info.base_url + version + source + ", MCP at " + os_info.mcp_url)
        if oauth_mode:
            # Name the authorization server only when it is a separate system (an
            # external IdP); the builtin AS is the OS itself, and repeating its URL
            # with a trailing slash reads like a mystery third party.
            servers = [
                s.rstrip("/")
                for s in (os_info.oauth.authorization_servers if os_info.oauth is not None else [])
                if s.rstrip("/") != os_info.base_url.rstrip("/")
            ]
            issuer = (" via " + ", ".join(servers)) if servers else ""
            print_info("The MCP endpoint is OAuth-protected: apps complete a one-time sign-in" + issuer + ".")

    adapters = build_adapters(project=project)
    clients_remaining, wanted_apps = _split_chat_apps(clients)
    # Auto-surface the hosted chat apps only when the run wasn't scoped by --clients AND
    # the deployed OS is one they can actually add: public HTTPS, and either no token
    # gate or an OAuth-protected /mcp (their Connectors UIs authenticate with OAuth).
    # Explicitly requested chat apps are honored regardless -- their instructions carry
    # the caveats.
    auto_surface_apps = (
        clients is None and (os_info.auth_mode == "none" or os_info.oauth_enabled) and _reachable_from_cloud(os_info)
    )
    # Auto-detect only when no --clients was given; a chat-app-only request selects no adapters.
    selected = (
        _resolve_clients(clients_remaining, adapters, required=not auto_surface_apps)
        if clients is None or clients_remaining
        else []
    )

    # Minting needs a credential the server can authenticate: a protected REST plane
    # (auth_mode is that plane; the MCP OAuth posture lives in os_info.oauth and never
    # enables minting), or -- on an open plane -- an exported service-account token,
    # which the server dispatches by prefix and scope-checks in every auth mode.
    env_credential = env_admin_credential()
    minting = (
        bool(selected)
        and not oauth_mode
        and (
            os_info.auth_mode not in ("none",)
            or (pat and env_credential is not None and env_credential.startswith(PAT_PREFIX))
        )
    )
    # Dead end: minted tokens are wanted (--pat) or required (/mcp is token-protected
    # with no authorization server to sign in through), but nothing can mint here.
    # Fail before any credential prompt or config write.
    if selected and not oauth_mode and not minting and (pat or os_info.oauth is not None):
        if pat and os_info.oauth_enabled:
            or_else = "Or drop --pat to use the OAuth sign-in flow."
        elif os_info.oauth is not None:
            or_else = "Or export a previously minted token via " + ADMIN_TOKEN_ENV + " and re-run with --pat."
        else:
            or_else = "Or drop --pat to connect without a token (this MCP endpoint is unauthenticated)."
        require_mint_capable(os_info.base_url, os_info.auth_mode, or_else=or_else)
        raise CLIError(
            "This AgentOS reports no REST authentication (auth mode: "
            + os_info.auth_mode
            + ") and no admin credential is exported, so nothing can mint the tokens "
            + ("--pat asks for." if pat else "its token-protected MCP endpoint needs."),
            hint="Set OS_SECURITY_KEY (or configure JWT auth) on the server, or export "
            + ADMIN_TOKEN_ENV
            + " if minting worked before. "
            + or_else,
        )
    # When we mint, the admin token is attached to base_url and the minted PATs are written
    # into client configs and sent to the (same-origin) MCP URL. Refuse to do any of that
    # over plaintext HTTP to a non-loopback host unless the operator opted in.
    if minting:
        require_secure_url(os_info.base_url, allow_http=allow_http, what="the admin credential and minted tokens")
    elif selected and _stored_token_exists(selected, (server_name, legacy_name), os_info.mcp_url):
        # Not minting, but re-verification re-sends any token already stored in a
        # matching entry: the same plaintext rule applies to credentials we merely relay.
        require_secure_url(os_info.base_url, allow_http=allow_http, what="a token stored in a client config")
    admin_token = resolve_admin_token(os_info.auth_mode, json_mode) if minting else None
    # "Authorization is disabled" is a statement about the whole server; stay quiet when
    # an mcp.oauth block says /mcp has its own auth the REST plane knows nothing about.
    if not minting and selected and not json_mode and os_info.auth_mode == "none" and os_info.oauth is None:
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
        # Fail a bad credential fast: one cheap authed call before any minting or config
        # writes, so a rejected paste surfaces immediately instead of reading like a
        # hang. Human path only -- in --json the per-client results carry the failure.
        if api is not None and not json_mode:
            try:
                with console.status("Checking the admin credential..."):
                    api.check_admin_credential()
                print_success("Credential accepted.")
            except APIError as e:
                # 403 means authenticated but not granted service_accounts:read; the
                # mint itself needs only service_accounts:write, so keep going.
                if e.status_code != 403:
                    raise

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
            status = None if json_mode else console.status("Connecting " + display_name(adapter.key) + "...")
            try:
                if status is not None:
                    status.start()
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
                    legacy_name=legacy_name,
                    legacy_token_reuse=legacy_token_reuse,
                    oauth_mode=oauth_mode,
                    status=status,
                )
            except CLIError as e:
                result["error"] = e.full_message
            except Exception as e:  # one client's failure must never abort the run
                result["error"] = "Unexpected error (" + type(e).__name__ + "): " + str(e)
            finally:
                if status is not None:
                    status.stop()
            results.append(result)
    finally:
        if api is not None:
            api.close()

    # Spot a deployed AgentOS: when discovery lands on a public, token-free URL (typically
    # AGENTOS_URL set to the production domain), the hosted chat apps can use it too --
    # surface their setup steps without requiring --clients. Auto-surfaced apps are
    # marked so the report can render them as one compact aside instead of two full
    # instruction blocks nobody asked for; explicitly requested apps keep the detail.
    explicit_apps = set(wanted_apps)
    if auto_surface_apps:
        wanted_apps = list(CHAT_APPS)
    for app in wanted_apps:
        entry = _chat_app_instructions(app, os_info)
        if app not in explicit_apps:
            entry["auto"] = True
        results.append(entry)

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


def _select_os(candidates: List[OSInfo], verb: str) -> OSInfo:
    """Pick the target when discovery finds more than one running AgentOS.

    A numbered menu; Enter takes the first candidate, which _candidate_sources orders
    as the env-file/env URL -- the target single-source discovery resolves. Trust is
    not decided here: the chosen URL still flows through the env-file trust gate, so
    picking a remote env-file URL prompts while picking local stays silent.
    """
    if len(candidates) == 1:
        return candidates[0]
    print_info("Found multiple running AgentOS. Which one do you want to " + verb + "?")
    print_info("")
    width = max(len(c.base_url) for c in candidates)
    for index, candidate in enumerate(candidates, start=1):
        tag = "local " if _is_loopback_host(urlsplit(candidate.base_url).hostname) else "remote"
        os_label = ' "' + candidate.name + '"' if candidate.name else ""
        print_info(
            "  " + str(index) + "  " + candidate.base_url.ljust(width) + "  " + tag + os_label + candidate.source_note()
        )
    print_info("")
    prompt_label = {"connect": "Connect to", "disconnect": "Disconnect from"}.get(verb, "Select")
    while True:
        raw = str(typer.prompt(prompt_label, default="1")).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            return candidates[int(raw) - 1]
        print_warning("Enter a number between 1 and " + str(len(candidates)) + ".")


def _stored_token_exists(adapters: List[ClientAdapter], names: "tuple[Optional[str], ...]", mcp_url: str) -> bool:
    """Whether any selected client already holds a token-carrying entry for this OS."""
    for adapter in adapters:
        for name in names:
            if name is None:
                continue
            entry = adapter.read_existing(name)
            if entry is not None and entry.token is not None and entry.url == mcp_url:
                return True
    return False


def _remove_legacy_entry(adapter: ClientAdapter, os_info: OSInfo, legacy_name: str, result: Dict[str, Any]) -> None:
    """Drop the stale duplicate left by an entry rename: the "agno" entry (agnoctl
    0.1.x naming) is removed from every scope where it points at this OS -- the URL
    guard keeps a same-named entry for a different OS intact, in every scope. Cleanup
    must never fail an otherwise successful connect: an error becomes a note."""
    try:
        removal = adapter.remove(legacy_name, matches=lambda entry_url: entry_url == os_info.mcp_url)
        if removal.removed:
            result["replaced_legacy"] = legacy_name
    except Exception as e:
        note = "Could not remove the legacy '" + legacy_name + "' entry: " + str(e)
        result["note"] = (str(result["note"]) + " " + note) if result.get("note") else note


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
    legacy_name: Optional[str] = None,
    legacy_token_reuse: bool = True,
    oauth_mode: bool = False,
    status: Optional[Status] = None,
) -> None:
    account_name = name or adapter.key
    existing = adapter.read_existing(server_name)
    legacy = adapter.read_existing(legacy_name) if legacy_name is not None else None

    if existing is not None:
        if existing.url == os_info.mcp_url and not rotate:
            # Idempotency: an entry already pointing at this OS that still verifies is left
            # alone. A tokenless entry on an OAuth-protected endpoint verifies via the
            # challenge (the client holds the sign-in state, not the config).
            check = verify_mcp(
                os_info.mcp_url,
                token=existing.token,
                expect_oauth_challenge=oauth_mode and existing.token is None,
            )
            if check.ok and (existing.token is not None or not minting):
                result.update(status="already-connected", location=existing.location, verify=check.public_dict())
                if legacy_name is not None and legacy is not None:
                    _remove_legacy_entry(adapter, os_info, legacy_name, result)
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
        # Entry rename: a legacy "agno" entry pointing at this OS whose token verifies
        # hands its token to the identity-named entry, keeping the account that backs it.
        if (
            legacy is not None
            and legacy.url == os_info.mcp_url
            and legacy.token is not None
            and legacy_token_reuse
            and existing is None
            and name is None
            and not rotate
        ):
            if status is not None:
                status.update("Verifying the existing '" + str(legacy_name) + "' token...")
            if verify_mcp(os_info.mcp_url, token=legacy.token).ok:
                token = legacy.token
        if token is None:
            if name is not None:
                if shared_token is None:
                    result.update(status="skipped", error="Service account exists; kept untouched.")
                    return
                token = shared_token
            else:
                if status is not None:
                    status.update("Minting token for " + display_name(adapter.key) + "...")
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
                    status=status,
                )
                if account is None:
                    result.update(status="skipped", error="Service account exists; kept untouched.")
                    return
                token = account.token

    if status is not None:
        status.update("Writing config for " + display_name(adapter.key) + "...")
    write_result = adapter.write(server_name, os_info.mcp_url, token)
    result["location"] = write_result.location
    if write_result.note:
        result["note"] = write_result.note
    if account is not None:
        result["account"] = account.public_dict()

    if status is not None:
        status.update("Verifying " + os_info.mcp_url + "...")
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

    verify_result = verify_mcp(
        os_info.mcp_url, token=readback.token, expect_oauth_challenge=oauth_mode and readback.token is None
    )
    result["verify"] = verify_result.public_dict()
    if verify_result.ok:
        if verify_result.oauth_challenge:
            # The entry is in place and the endpoint answers with an OAuth challenge:
            # the last step -- the sign-in -- happens inside the client itself.
            result["status"] = "needs-login"
            step = OAUTH_SIGNIN_STEPS.get(adapter.key)
            if step:
                result["instructions"] = [step.replace("{server}", server_name)]
        else:
            result["status"] = "connected"
        if legacy_name is not None and legacy is not None:
            _remove_legacy_entry(adapter, os_info, legacy_name, result)
        # A client that was already configured with a *different* token still holds the
        # old one in its live, in-process MCP connection: it keeps using the now-revoked
        # token until it is restarted. Flag it so the report can say so.
        if existing is not None and existing.token is not None and token is not None and existing.token != token:
            result["rotated"] = True
        # A tokenless write that replaced a token-carrying entry (OAuth conversion via
        # --rotate, or a legacy-entry rename) erases the bearer from disk but not the
        # service account behind it: nothing here holds a credential to revoke with.
        # Flag it so the report can point at `agno tokens revoke`.
        if token is None and (
            (existing is not None and existing.token is not None)
            or (result.get("replaced_legacy") and legacy is not None and legacy.token is not None)
        ):
            result["replaced_token_entry"] = True
    else:
        result["error"] = verify_result.error


def _report(
    os_info: OSInfo,
    results: List[Dict[str, Any]],
    server_name: str,
    open_mcp_warning: Optional[str],
    json_mode: bool,
) -> None:
    exit_code = exit_code_for(results, ("connected", "already-connected", "needs-login", "manual"))

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
    # Auto-surfaced chat apps render as one compact aside at the end; only explicitly
    # requested ones get their full instruction blocks in the result list.
    auto_apps = [r for r in results if r["status"] == "manual" and r.get("auto")]
    for r in results:
        if r["status"] == "manual" and r.get("auto"):
            continue
        label = display_name(r["client"])
        if r["status"] == "connected":
            tools = (r.get("verify") or {}).get("tools")
            suffix = " (" + str(tools) + " tools)" if tools else ""
            print_success("  connected      " + label + suffix + "  ->  " + shorten_home(str(r.get("location", ""))))
        elif r["status"] == "needs-login":
            # The sign-in step lives in the "To finish" section below, next to the
            # restart step, so the row stays a one-line statement of what happened.
            print_warning("  sign in        " + label + "  ->  " + shorten_home(str(r.get("location", ""))))
        elif r["status"] == "already-connected":
            print_success("  already ok     " + label + "  ->  " + shorten_home(str(r.get("location", ""))))
        elif r["status"] == "skipped":
            print_warning("  skipped        " + label + "  (" + str(r.get("error") or "") + ")")
        elif r["status"] == "manual":
            ui_name = CHAT_APPS_SPEC[r["client"]][0] if r["client"] in CHAT_APPS_SPEC else label
            print_warning("  action needed  " + label + "  (set up in the " + ui_name + " UI)")
            for step in r.get("instructions", []):
                print_info("                 - " + step)
            if r.get("url"):
                print_info("                 MCP URL: " + str(r["url"]))
        else:
            print_error("  failed         " + label + "  (" + str(r.get("error") or "unknown error") + ")")
        if r.get("note"):
            print_warning("                 note: " + str(r["note"]))
        if r.get("replaced_legacy"):
            print_warning("                 renamed the legacy '" + str(r["replaced_legacy"]) + "' entry")

    # Entries replaced across clients are almost always the same other OS (same entry
    # name, e.g. local vs deployed instances both named "AgentOS"): say it once, with
    # the way to keep both, instead of a cryptic per-row echo.
    replaced_urls: Dict[str, List[str]] = {}
    for r in results:
        if r.get("replaced_url"):
            replaced_urls.setdefault(str(r["replaced_url"]), []).append(display_name(r["client"]))
    for url, labels in replaced_urls.items():
        print_info("")
        print_warning(
            "This replaced " + (", ".join(sorted(set(labels)))) + "'s existing '" + server_name + "' entry, "
            "which pointed at " + url + " -- those apps now connect to this OS instead."
        )
        print_info(
            "To use both, reconnect the other OS under its own entry name: "
            "agno connect --url <other-os> --server-name <name>"
        )

    # One summary + next-steps section: freshly wired clients hold no live MCP session
    # yet, and rotated ones keep using the previous (now revoked) token until they
    # restart. The sign-in steps sit HERE, numbered after the restart they depend on.
    fresh = sorted({display_name(r["client"]) for r in results if r["status"] in ("connected", "needs-login")})
    if fresh:
        signin_steps = [
            (display_name(r["client"]), r["instructions"][0])
            for r in results
            if r["status"] == "needs-login" and r.get("instructions")
        ]
        os_label = ('"' + os_info.name + '"') if os_info.name else os_info.base_url
        count = str(len(fresh)) + (" app" if len(fresh) == 1 else " apps")
        loads = "so it loads" if len(fresh) == 1 else "so they load"
        print_info("")
        verb = "Configured" if signin_steps else "Connected"
        print_success(
            verb + " " + count + " " + ("for" if signin_steps else "to") + " " + os_label + " as '" + server_name + "'."
        )
        if signin_steps:
            width = max(len(name) for name, _ in signin_steps)
            print_warning("To finish:")
            print_info("  1. Restart " + ", ".join(fresh) + " " + loads + " the new MCP server.")
            print_info("  2. Complete the one-time sign-in in each app:")
            for name, step in signin_steps:
                print_info("       " + name.ljust(width + 2) + step)
        else:
            print_warning("Restart " + ", ".join(fresh) + " " + loads + " the new MCP server.")
        if any(r.get("rotated") for r in results):
            print_warning("A rotated client keeps using its previous (now revoked) token until it restarts.")

    accounts = sorted({r["account"]["name"] for r in results if r.get("account")})
    if accounts:
        print_info("")
        # The --url pin matters: tokens resolves its own target, which may differ from
        # the OS this run connected (e.g. after picking the local OS off the menu).
        print_info(
            "Revoke any time with: agno tokens revoke <name> --url "
            + os_info.base_url
            + "  (accounts: "
            + ", ".join(accounts)
            + ")"
        )

    replaced_tokens = sorted({display_name(r["client"]) for r in results if r.get("replaced_token_entry")})
    if replaced_tokens:
        print_info("")
        print_warning(
            "The replaced entries for "
            + ", ".join(replaced_tokens)
            + " carried tokens; the service accounts behind them stay valid until they expire."
        )
        print_info("Revoke them with: agno tokens revoke <name> --url " + os_info.base_url)

    if auto_apps:
        print_info("")
        print_info("Also reachable from the hosted chat apps (claude.ai, ChatGPT):")
        print_info("  Settings -> Connectors -> Add custom connector -> " + os_info.mcp_url)
        if os_info.oauth_enabled:
            print_info("  Both authenticate with the same one-time sign-in when you add the connector.")
        print_info("  Custom connectors need a paid plan; ChatGPT needs Developer Mode for full tool access.")

    if open_mcp_warning:
        print_info("")
        print_warning(open_mcp_warning)

    raise typer.Exit(exit_code)
