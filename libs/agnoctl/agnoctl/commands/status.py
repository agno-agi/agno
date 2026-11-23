"""`agno status`: orientation — what OS is running, how it is secured, what is connected."""

from typing import Optional

import typer

from agnoctl.clients import build_adapters
from agnoctl.commands._common import derive_server_name, handle_cli_error
from agnoctl.console import emit_json, print_info, print_success
from agnoctl.discovery import discover
from agnoctl.errors import CLIError


def status(
    url: Optional[str] = typer.Option(
        None, "--url", help="AgentOS base URL. Default: AGENTOS_URL, then .env.production/.env, then localhost."
    ),
    server_name: Optional[str] = typer.Option(
        None, "--server-name", help="MCP server entry name to look for. Default: derived from the AgentOS name."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption."),
) -> None:
    """Show the discovered AgentOS and which coding agents are connected to it."""
    try:
        os_info = discover(url)
    except CLIError as e:
        raise handle_cli_error(e, json_output)

    # Look for what connect would write today: the OS-name-derived entry.
    if server_name is None:
        server_name = derive_server_name(os_info.name)

    adapters = build_adapters()
    clients = []
    for adapter in adapters.values():
        entry = adapter.read_existing(server_name) if adapter.detect() else None
        clients.append(
            {
                "client": adapter.key,
                "detected": adapter.detect(),
                "configured": entry is not None,
                "location": entry.location if entry else None,
            }
        )

    if json_output:
        emit_json({"os": os_info.public_dict(), "clients": clients})
        return

    version = " (agno " + os_info.version + ")" if os_info.version else ""
    print_success("AgentOS: " + os_info.base_url + os_info.source_note() + version)
    mcp = os_info.mcp_url if os_info.mcp_enabled else "disabled"
    print_info("  MCP: " + mcp)
    print_info("  Auth mode: " + os_info.auth_mode)
    # auth_mode is the REST plane only; without this line an OAuth-protected /mcp
    # would read as an unsecured deployment ("Auth mode: none").
    if os_info.oauth is not None:
        servers = os_info.oauth.authorization_servers
        mcp_auth = ("OAuth via " + ", ".join(servers)) if servers else "token-protected (no authorization server)"
        print_info("  MCP auth: " + mcp_auth)
    print_info("")
    for c in clients:
        if not c["detected"]:
            print_info("  " + str(c["client"]) + ": not detected")
        elif c["configured"]:
            print_info("  " + str(c["client"]) + ": configured (" + str(c["location"]) + ")")
        else:
            print_info("  " + str(c["client"]) + ": detected, not connected (run: agno connect)")
