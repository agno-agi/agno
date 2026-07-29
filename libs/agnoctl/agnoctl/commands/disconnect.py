"""`agno disconnect`: remove the AgentOS MCP entry from coding-agent configs.

The inverse of connect, offline by default: config edits only, no OS and no admin
credential required. Entries are located by where they point, not by guessing names:
with `--server-name` exactly that entry is removed; otherwise every entry pointing at
the target AgentOS goes -- its live address when the OS answers, else every address
discovery would have tried (the env-file URL and the localhost defaults), so tearing
down a deployed OS never blocks disconnect. Entries pointing at any other server are
never touched. Opt-in --revoke also revokes the service accounts connect minted; only
that path needs the OS and an admin credential.
"""

from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

import typer

from agnoctl.clients import build_adapters, configured_sources, display_name
from agnoctl.commands._common import (
    ensure_env_file_url_trusted,
    handle_cli_error,
    require_secure_url,
    resolve_admin_token,
    stdin_is_interactive,
    validate_server_name,
)
from agnoctl.commands.connect import (
    CHAT_APPS_SPEC,
    _resolve_clients,
    _select_os,
    _split_chat_apps,
    exit_code_for,
)
from agnoctl.console import emit_json, print_error, print_info, print_success, print_warning, shorten_home
from agnoctl.discovery import OSInfo, _candidate_sources, discover, discover_all
from agnoctl.errors import CLIError
from agnoctl.http import AgentOSAPI


def disconnect(
    url: Optional[str] = typer.Option(
        None, "--url", help="AgentOS base URL. Default: AGENTOS_URL, then .env.production/.env, then localhost."
    ),
    clients: Optional[str] = typer.Option(
        None,
        "--clients",
        help=(
            "Comma-separated clients (claude-code,claude-desktop,codex,cursor; claude-ai and chatgpt "
            "print manual removal steps). Default: detected."
        ),
    ),
    server_name: Optional[str] = typer.Option(
        None,
        "--server-name",
        help="Remove exactly this entry name. Default: every entry pointing at the target AgentOS.",
    ),
    name: Optional[str] = typer.Option(
        None, "--name", help="With --revoke: the shared service-account name used at connect time."
    ),
    revoke: bool = typer.Option(
        False, "--revoke", help="Also revoke the matching service accounts (needs the OS and an admin credential)."
    ),
    allow_http: bool = typer.Option(
        False, "--allow-http", help="Permit sending credentials over plaintext HTTP to a remote host."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Trust a remote AGENTOS_URL from a .env file without prompting."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption."),
) -> None:
    """Disconnect this machine's coding agents from your AgentOS."""
    try:
        _disconnect(
            url=url,
            clients=clients,
            server_name=server_name,
            name=name,
            revoke=revoke,
            allow_http=allow_http,
            assume_yes=yes,
            json_mode=json_output,
        )
    except CLIError as e:
        raise handle_cli_error(e, json_output)


def _matches_targets(entry_url: str, targets: List[str]) -> bool:
    """Whether an entry's MCP URL points at one of the target base URLs.

    Same scheme+host+port AND the entry's path lives under the target's base path, so
    two AgentOS path-routed on one host (/customer-a, /customer-b) never match each
    other. A target with no path (the usual base URL) matches any path on that host.
    """
    entry = urlsplit(entry_url)
    for target in targets:
        parts = urlsplit(target)
        if entry.scheme.lower() != parts.scheme.lower():
            continue
        if (entry.netloc or "").lower() != (parts.netloc or "").lower():
            continue
        base_path = parts.path.rstrip("/")
        entry_path = entry.path or "/"
        if not base_path or entry_path == base_path or entry_path.startswith(base_path + "/"):
            return True
    return False


def _disconnect(
    url: Optional[str],
    clients: Optional[str],
    server_name: Optional[str],
    name: Optional[str],
    revoke: bool,
    allow_http: bool,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    if server_name is not None:
        validate_server_name(server_name)

    # Discovery locates the OS whose entries should go; it is best-effort because the
    # most common reason to disconnect is that the OS is already gone. Only --revoke,
    # which must talk to the OS, treats "no running AgentOS" as fatal. Non-interactive
    # runs use single-target discover() so automation stays deterministic.
    os_info: Optional[OSInfo] = None
    if revoke or server_name is None:
        interactive = not json_mode and stdin_is_interactive()
        try:
            os_info = (
                _select_os(discover_all(url, extra_sources=configured_sources(build_adapters())), verb="disconnect")
                if interactive
                else discover(url)
            )
        except CLIError:
            if revoke:
                raise
            os_info = None

    # The removal targets: entries pointing at the live OS's address, or -- when
    # nothing answers -- at any address discovery would have tried for this directory.
    matcher: Optional[Callable[[str], bool]] = None
    target_urls: List[str] = []
    if server_name is None:
        target_urls = [os_info.base_url] if os_info is not None else [s[0] for s in _candidate_sources(url)]

        def _match(entry_url: str) -> bool:
            return _matches_targets(entry_url, target_urls)

        matcher = _match
        if os_info is None and not json_mode:
            print_info("No running AgentOS found; removing entries pointing at: " + ", ".join(target_urls))

    api: Optional[AgentOSAPI] = None
    if revoke and os_info is not None:
        # The admin credential is about to ride on this URL: same gates as connect.
        ensure_env_file_url_trusted(
            os_info.base_url, os_info.url_source, os_info.url_source_file, assume_yes=assume_yes, json_mode=json_mode
        )
        if os_info.auth_mode not in ("none",):
            require_secure_url(os_info.base_url, allow_http=allow_http, what="the admin credential")
        admin_token = resolve_admin_token(os_info.auth_mode, json_mode)
        api = AgentOSAPI(os_info.base_url, admin_token=admin_token)

    adapters = build_adapters()
    clients_remaining, wanted_apps = _split_chat_apps(clients)
    selected = (
        _resolve_clients(clients_remaining, adapters, required=not wanted_apps)
        if clients is None or clients_remaining
        else []
    )

    results: List[Dict[str, Any]] = []
    removed_token_entry = False
    for adapter in selected:
        result: Dict[str, Any] = {"client": adapter.key, "status": "not-found", "error": None}
        try:
            # The resolving entries, read before removal: whether a removed entry carried
            # a token decides the revoke reminder below (an OAuth OS holds sign-in state
            # in the client, but a --pat run minted a real account there too).
            entries = adapter.list_entries()
            if server_name is not None:
                names = [server_name]
            elif matcher is not None:
                # Every known name is a removal candidate, not just those whose
                # RESOLVING entry matches: precedence can hide the target's entry behind
                # a same-named one for another OS in a higher-precedence scope. remove()
                # applies the URL guard per scope, so non-matching names are no-ops.
                names = list(entries)
            else:
                names = []
            removed_names: List[str] = []
            locations: List[str] = []
            for candidate in names:
                removal = adapter.remove(candidate, matches=matcher)
                if removal.removed:
                    removed_names.append(candidate)
                    entry = entries.get(candidate)
                    if entry is not None and entry.token is not None:
                        removed_token_entry = True
                    if removal.location and removal.location not in locations:
                        locations.append(removal.location)
            if removed_names:
                result["status"] = "removed"
                result["removed"] = removed_names
                result["location"] = ", ".join(locations)
        except CLIError as e:
            result.update(status="failed", error=e.full_message)
        except Exception as e:  # one client's failure must never abort the run
            result.update(status="failed", error="Unexpected error (" + type(e).__name__ + "): " + str(e))
        results.append(result)

    # Hosted chat apps have no local config to edit; say where the human removes them.
    for app in wanted_apps:
        ui_name = CHAT_APPS_SPEC[app][0] if app in CHAT_APPS_SPEC else app
        results.append(
            {
                "client": app,
                "status": "manual",
                "error": None,
                "instructions": ["Remove the connector in the " + ui_name + " UI: Settings -> Connectors."],
            }
        )

    # --revoke: best-effort, after the config removals, one account per selected client
    # (or the one shared --name account) -- mirroring how connect named them at mint time.
    revocations: List[Dict[str, Any]] = []
    if api is not None:
        account_names = [name] if name else sorted(adapter.key for adapter in selected)
        with api:
            for account_name in account_names:
                revocation: Dict[str, Any] = {"account": account_name, "status": "revoked", "error": None}
                try:
                    account = api.find_service_account(account_name)
                    if account is None:
                        revocation["status"] = "not-found"
                    else:
                        api.revoke_service_account(account.id)
                except CLIError as e:
                    revocation.update(status="failed", error=e.full_message)
                except Exception as e:
                    revocation.update(status="failed", error="Unexpected error (" + type(e).__name__ + "): " + str(e))
                revocations.append(revocation)

    _report(os_info, server_name, target_urls, results, revocations, revoke, removed_token_entry, json_mode)


def _report(
    os_info: Optional[OSInfo],
    server_name: Optional[str],
    target_urls: List[str],
    results: List[Dict[str, Any]],
    revocations: List[Dict[str, Any]],
    revoke: bool,
    removed_token_entry: bool,
    json_mode: bool,
) -> None:
    # not-found is a clean outcome: nothing to undo.
    exit_code = exit_code_for(results, ("removed", "not-found", "manual"))
    if exit_code == 0 and any(r["status"] == "failed" for r in revocations):
        exit_code = 3

    if json_mode:
        emit_json(
            {
                "os": os_info.public_dict() if os_info is not None else None,
                "server_name": server_name,
                "target_urls": target_urls or None,
                "results": results,
                "revocations": revocations,
                "exit_code": exit_code,
            }
        )
        raise typer.Exit(exit_code)

    print_info("")
    for r in results:
        label = display_name(r["client"])
        if r["status"] == "removed":
            names = ", ".join(r.get("removed") or [])
            print_success(
                "  removed        " + label + " ('" + names + "')  ->  " + shorten_home(str(r.get("location", "")))
            )
        elif r["status"] == "not-found":
            print_info("  not found      " + label + "  (no matching entry)")
        elif r["status"] == "manual":
            print_warning("  action needed  " + label)
            for step in r.get("instructions", []):
                print_info("                 - " + step)
        else:
            print_error("  failed         " + label + "  (" + str(r.get("error") or "unknown error") + ")")

    for revocation in revocations:
        if revocation["status"] == "revoked":
            print_success("  revoked        service account '" + str(revocation["account"]) + "'")
        elif revocation["status"] == "not-found":
            print_info("  no account     '" + str(revocation["account"]) + "' (already revoked or never minted)")
        else:
            print_error(
                "  revoke failed  '"
                + str(revocation["account"])
                + "'  ("
                + str(revocation.get("error") or "unknown error")
                + ")"
            )

    # A running client holds its MCP connection in-process; the entry's removal only
    # takes effect when the client restarts.
    cleared = sorted({display_name(r["client"]) for r in results if r["status"] == "removed"})
    if cleared:
        print_info("")
        print_warning("Restart " + ", ".join(cleared) + " to drop the connection.")
        # The reminder keys on what was actually removed, not the server's auth mode:
        # tokenless entries (OAuth sign-in, auth-less OS) have nothing to revoke, while
        # a token-carrying entry backs a still-valid account even on an OAuth OS
        # (connect --pat mints there too).
        if not revoke and removed_token_entry:
            url_hint = (" --url " + os_info.base_url) if os_info is not None else ""
            print_info(
                "Tokens minted for these apps stay valid. Revoke them with: agno tokens revoke <name>" + url_hint
            )

    raise typer.Exit(exit_code)
