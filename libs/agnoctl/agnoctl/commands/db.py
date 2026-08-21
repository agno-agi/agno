"""`agno db`: check and apply AgentOS database schema migrations over the REST API."""

from typing import Any, Dict, List, Optional

import typer

from agnoctl.commands._common import (
    ensure_env_file_url_trusted,
    handle_cli_error,
    require_secure_url,
    resolve_admin_token,
)
from agnoctl.console import emit_json, print_info, print_success, print_warning
from agnoctl.discovery import discover
from agnoctl.errors import CLIError
from agnoctl.http import AgentOSAPI

db_app = typer.Typer(name="db", help="Check and apply AgentOS database schema migrations.")

UrlOption = typer.Option(
    None, "--url", help="AgentOS base URL. Default: AGENTOS_URL, then .env.production/.env, then localhost."
)
JsonOption = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption.")
AllowHttpOption = typer.Option(
    False, "--allow-http", help="Permit sending the admin credential over plaintext HTTP to a remote host."
)
TrustEnvFileOption = typer.Option(
    False, "--yes", "-y", help="Trust a remote AGENTOS_URL from a .env file without prompting."
)
DbIdOption = typer.Option(None, "--db-id", help="Limit to one database id. Default: every database of the OS.")


def _api_for(url: Optional[str], json_mode: bool, allow_http: bool, assume_yes: bool) -> AgentOSAPI:
    os_info = discover(url)
    ensure_env_file_url_trusted(
        os_info.base_url, os_info.url_source, os_info.url_source_file, assume_yes=assume_yes, json_mode=json_mode
    )
    if url is None and not json_mode:
        print_info("Using AgentOS at " + os_info.base_url + os_info.source_note())
    admin_token = resolve_admin_token(os_info.auth_mode, json_mode)
    if admin_token is not None:
        require_secure_url(os_info.base_url, allow_http=allow_http, what="the admin credential")
    return AgentOSAPI(os_info.base_url, admin_token=admin_token)


def _reports(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize the all-databases and single-database payload shapes to a list of reports."""
    if "databases" in payload:
        return [r for r in payload["databases"] if isinstance(r, dict)]
    return [payload]


def _print_pending(reports: List[Dict[str, Any]]) -> int:
    """Print the pending report for humans; return the number of pending tables."""
    total = 0
    for report in reports:
        db_id = str(report.get("db_id", "?"))
        if report.get("remote"):
            print_info("  " + db_id + ": remote database, migrated where it is hosted")
            continue
        if report.get("error"):
            print_warning("  " + db_id + ": could not be checked (" + str(report["error"]) + ")")
            continue
        pending = report.get("pending") or []
        if not pending:
            print_info("  " + db_id + ": up to date")
            continue
        print_warning("  " + db_id + ": " + str(len(pending)) + " table(s) pending")
        for item in pending:
            total += 1
            print_info(
                "    - "
                + str(item.get("table_name"))
                + " ["
                + str(item.get("table_type"))
                + "]: "
                + str(item.get("current_version"))
                + " -> "
                + str(item.get("target_version"))
            )
    return total


@db_app.command("status")
def status(
    db_id: Optional[str] = DbIdOption,
    url: Optional[str] = UrlOption,
    json_output: bool = JsonOption,
    allow_http: bool = AllowHttpOption,
    yes: bool = TrustEnvFileOption,
) -> None:
    """Show which database tables have schema migrations pending. Changes nothing."""
    try:
        with _api_for(url, json_output, allow_http, yes) as api:
            payload = api.pending_migrations(db_id=db_id)
    except CLIError as e:
        raise handle_cli_error(e, json_output)

    if json_output:
        emit_json(payload)
        return

    reports = _reports(payload)
    print_info("Database migrations:")
    total = _print_pending(reports)
    if total:
        print_warning(str(total) + " table(s) pending. Apply with: agno db migrate")
    else:
        print_success("All databases are up to date.")


@db_app.command("migrate")
def migrate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be migrated without applying anything."),
    target_version: Optional[str] = typer.Option(
        None, "--target-version", help="Schema version to migrate to (e.g. 3.0.0). Default: latest."
    ),
    db_id: Optional[str] = DbIdOption,
    url: Optional[str] = UrlOption,
    json_output: bool = JsonOption,
    allow_http: bool = AllowHttpOption,
    yes: bool = TrustEnvFileOption,
) -> None:
    """Apply pending schema migrations to the AgentOS databases."""
    try:
        with _api_for(url, json_output, allow_http, yes) as api:
            if dry_run:
                payload = api.pending_migrations(db_id=db_id)
            else:
                payload = api.migrate_databases(db_id=db_id, target_version=target_version)
    except CLIError as e:
        raise handle_cli_error(e, json_output)

    if dry_run:
        if json_output:
            emit_json(payload)
            return
        reports = _reports(payload)
        print_info("Dry run, nothing applied. Pending migrations:")
        total = _print_pending(reports)
        if total:
            print_warning(str(total) + " table(s) would be migrated. Run again without --dry-run to apply.")
        else:
            print_success("Nothing to migrate.")
        return

    status_code = payload.pop("_status_code", 200)
    if json_output:
        emit_json(payload)
        if status_code == 207:
            raise typer.Exit(1)
        return

    print_success(str(payload.get("message", "Migration finished.")))
    failed = payload.get("failed") or {}
    if failed:
        for failed_db_id, error in failed.items():
            print_warning("  " + str(failed_db_id) + ": " + str(error))
        raise typer.Exit(1)
