"""`agno create`: scaffold a new AgentOS project from a starter template.

The mechanism is deliberately simple (inherited from `ag infra create`): shallow-clone
the template repository, strip its git history, and copy example secrets into place.
No registry file is kept — commands operate on the current directory.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import typer

from agnoctl.commands._common import handle_cli_error, validate_project_name
from agnoctl.console import emit_json, print_info, print_success
from agnoctl.errors import CLIError

TEMPLATES: Dict[str, str] = {
    "agentos-docker": "https://github.com/agno-agi/agentos-docker",
    "agentos-aws": "https://github.com/agno-agi/agentos-aws",
    "agentos-fly": "https://github.com/agno-agi/agentos-fly",
    "agentos-gcp": "https://github.com/agno-agi/agentos-gcp",
    "agentos-railway": "https://github.com/agno-agi/agentos-railway",
}

DEFAULT_TEMPLATE = "agentos-docker"

GIT_TIMEOUT = 300.0


def _clone(repo_url: str, target: Path) -> None:
    if shutil.which("git") is None:
        raise CLIError("git is required to create a project from a template.", hint="Install git and re-run.")
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(target)],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise CLIError("git clone timed out after " + str(int(GIT_TIMEOUT)) + "s: " + repo_url)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CLIError("git clone failed: " + (detail or repo_url))
    shutil.rmtree(target / ".git", ignore_errors=True)


def create(
    name: str = typer.Argument(..., help="Directory name for the new AgentOS project."),
    template: str = typer.Option(
        DEFAULT_TEMPLATE, "--template", "-t", help="Starter template: " + ", ".join(sorted(TEMPLATES)) + "."
    ),
    template_url: Optional[str] = typer.Option(
        None, "--url", "-u", help="Clone from a custom template repository URL instead."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption."),
) -> None:
    """Create a new AgentOS project from a starter template."""
    try:
        payload = _create(name=name, template=template, template_url=template_url)
    except CLIError as e:
        raise handle_cli_error(e, json_output)

    if json_output:
        emit_json(payload)
        return
    print_success("Created " + str(payload["path"]) + " from " + str(payload["template"]))
    print_info("")
    print_info("Next steps:")
    print_info("  cd " + name)
    print_info("  cp example.env .env  # then fill in your secrets")
    print_info("  agno up              # start it with docker compose")
    print_info("  agno connect         # make it available in your coding agents")


def _create(name: str, template: str, template_url: Optional[str]) -> Dict[str, Any]:
    validate_project_name(name)
    target = Path.cwd() / name
    if target.exists():
        raise CLIError(
            "The directory " + str(target) + " already exists.",
            hint="Pick a different name or remove the existing directory.",
        )

    if template_url:
        repo_url = template_url
        template_label = template_url
    else:
        repo_url = TEMPLATES.get(template, "")
        if not repo_url:
            raise CLIError(
                "Unknown template: " + template,
                hint="Available templates: " + ", ".join(sorted(TEMPLATES)) + ", or pass --url for a custom repo.",
            )
        template_label = template

    _clone(repo_url, target)
    return {"path": str(target), "template": template_label}
