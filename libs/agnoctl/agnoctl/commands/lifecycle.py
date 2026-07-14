"""`agno up/down/restart`: run the project with docker compose.

This ports the path of the legacy `ag infra` CLI that real projects use: templates ship
a compose file, and up/down/restart shell out to `docker compose`. The legacy Python
resource engine (per-resource Docker/AWS orchestration) is intentionally not ported —
its production path is under redesign (see the agno-infra 2.0 spec).
"""

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from agnoctl.commands._common import handle_cli_error
from agnoctl.console import emit_json, print_info, print_success
from agnoctl.errors import CLIError

# Same names and order the legacy CLI recognized.
COMPOSE_FILE_NAMES = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]

COMPOSE_TIMEOUT = 600.0

JsonOption = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption.")
FileOption = typer.Option(None, "--file", "-f", help="Compose file to use (default: autodetect in ./ and ./infra).")
DryRunOption = typer.Option(False, "--dry-run", "-dr", help="Print the docker compose command without running it.")


def find_compose_file(explicit: Optional[str] = None, cwd: Optional[Path] = None) -> Path:
    base = cwd or Path.cwd()
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = base / path
        if not path.exists():
            raise CLIError("Compose file not found: " + str(path))
        return path
    for directory in (base, base / "infra"):
        for name in COMPOSE_FILE_NAMES:
            candidate = directory / name
            if candidate.exists():
                return candidate
    raise CLIError(
        "No compose file found in " + str(base) + " or " + str(base / "infra") + ".",
        hint="Run from an AgentOS project (agno create <name>) or pass --file.",
    )


def _run_compose(compose_file: Path, args: List[str], dry_run: bool, json_mode: bool) -> Dict[str, Any]:
    command = ["docker", "compose", "-f", str(compose_file)] + args
    if dry_run:
        return {"command": command, "compose_file": str(compose_file), "dry_run": True}
    if shutil.which("docker") is None:
        raise CLIError("docker is required.", hint="Install Docker and make sure `docker` is on PATH.")
    try:
        result = subprocess.run(
            command,
            cwd=str(compose_file.parent),
            timeout=COMPOSE_TIMEOUT,
            stdin=subprocess.DEVNULL,
            capture_output=json_mode,
            text=True,
        )
    except subprocess.TimeoutExpired:
        raise CLIError("docker compose timed out after " + str(int(COMPOSE_TIMEOUT)) + "s.")
    if result.returncode != 0:
        detail = ((result.stderr or "") if json_mode else "").strip()
        raise CLIError(
            "docker compose exited with code " + str(result.returncode) + ((": " + detail) if detail else "."),
        )
    return {"command": command, "compose_file": str(compose_file), "dry_run": False}


def up(
    file: Optional[str] = FileOption,
    pull: bool = typer.Option(False, "--pull", "-p", help="Always pull newer images."),
    dry_run: bool = DryRunOption,
    json_output: bool = JsonOption,
) -> None:
    """Start the project: docker compose up -d --build."""
    try:
        compose_file = find_compose_file(file)
        args = ["up", "-d", "--build"]
        if pull:
            args += ["--pull", "always"]
        payload = _run_compose(compose_file, args, dry_run, json_output)
    except CLIError as e:
        raise handle_cli_error(e, json_output)
    _finish(payload, "Project is up (" + str(payload["compose_file"]) + ").", json_output)


def down(
    file: Optional[str] = FileOption,
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Also remove named volumes (destroys data)."),
    dry_run: bool = DryRunOption,
    json_output: bool = JsonOption,
) -> None:
    """Stop the project: docker compose down."""
    try:
        compose_file = find_compose_file(file)
        args = ["down"]
        if volumes:
            args += ["--volumes"]
        payload = _run_compose(compose_file, args, dry_run, json_output)
    except CLIError as e:
        raise handle_cli_error(e, json_output)
    _finish(payload, "Project is down (" + str(payload["compose_file"]) + ").", json_output)


def restart(
    file: Optional[str] = FileOption,
    pull: bool = typer.Option(False, "--pull", "-p", help="Always pull newer images on the way back up."),
    dry_run: bool = DryRunOption,
    json_output: bool = JsonOption,
) -> None:
    """Restart the project: down, then up."""
    try:
        compose_file = find_compose_file(file)
        down_payload = _run_compose(compose_file, ["down"], dry_run, json_output)
        if not dry_run:
            time.sleep(2)
        up_args = ["up", "-d", "--build"]
        if pull:
            up_args += ["--pull", "always"]
        up_payload = _run_compose(compose_file, up_args, dry_run, json_output)
    except CLIError as e:
        raise handle_cli_error(e, json_output)
    payload = {"down": down_payload, "up": up_payload, "compose_file": str(compose_file), "dry_run": dry_run}
    _finish(payload, "Project restarted (" + str(compose_file) + ").", json_output)


def _finish(payload: Dict[str, Any], message: str, json_mode: bool) -> None:
    if json_mode:
        emit_json(payload)
        return
    if payload.get("dry_run"):
        command = payload.get("command") or (payload.get("up") or {}).get("command")
        print_info("Would run: " + " ".join(command or []))
        return
    print_success(message)
