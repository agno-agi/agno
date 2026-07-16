"""`agno create`: scaffold a new AgentOS project from a starter template.

The mechanism is deliberately simple (inherited from `ag infra create`): shallow-clone
the template repository, strip its git history, and copy example secrets into place.
No registry file is kept — commands operate on the current directory.

Bare `agno create` (no args) is interactive: pick a starter template, then a project
directory name. Flags and positional args skip the prompts. Automation (`--json` or a
non-TTY) requires an explicit name; the default template is used unless `--template`
or `--url` is provided.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import typer

from agnoctl.commands._common import handle_cli_error, stdin_is_interactive, validate_project_name
from agnoctl.console import emit_json, print_info, print_success, print_warning
from agnoctl.errors import CLIError

TEMPLATES: Dict[str, str] = {
    "agentos-docker": "https://github.com/agno-agi/agentos-docker",
    "agentos-aws": "https://github.com/agno-agi/agentos-aws",
    "agentos-fly": "https://github.com/agno-agi/agentos-fly",
    "agentos-gcp": "https://github.com/agno-agi/agentos-gcp",
    "agentos-railway": "https://github.com/agno-agi/agentos-railway",
}

# Display order for the interactive menu; first entry is the Enter default.
TEMPLATE_ORDER: List[str] = [
    "agentos-docker",
    "agentos-aws",
    "agentos-fly",
    "agentos-gcp",
    "agentos-railway",
]

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


def _default_name_from_url(url: str) -> str:
    """Best-effort directory name from a custom template URL (last path segment)."""
    path = urlsplit(url).path.rstrip("/")
    leaf = path.rsplit("/", 1)[-1] if path else ""
    if leaf.endswith(".git"):
        leaf = leaf[: -len(".git")]
    return leaf or "agentos"


def _prompt_template() -> str:
    """Numbered template menu; Enter selects the default (agentos-docker)."""
    print_info("Select starter template or press Enter for default (" + DEFAULT_TEMPLATE + ")")
    for index, template_name in enumerate(TEMPLATE_ORDER, start=1):
        print_info("  [" + str(index) + "] " + template_name)
    print_info("")
    while True:
        raw = str(typer.prompt("Chosen Template", default="1")).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(TEMPLATE_ORDER):
            return TEMPLATE_ORDER[int(raw) - 1]
        print_warning("Enter a number between 1 and " + str(len(TEMPLATE_ORDER)) + ".")


def _prompt_project_name(default: str) -> str:
    """Ask for the project name, validating until the name is usable."""
    while True:
        name = str(typer.prompt("Project Name", default=default)).strip()
        try:
            validate_project_name(name)
            return name
        except CLIError as e:
            print_warning(e.message)
            if e.hint:
                print_warning(e.hint)


def _resolve_create_inputs(
    name: Optional[str],
    template: Optional[str],
    template_url: Optional[str],
    *,
    json_output: bool,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Fill in missing name/template via prompts, or fail clearly in non-interactive mode.

    Interactive (TTY, not --json): missing template → numbered menu; missing name →
    directory prompt (defaulted from the chosen template / URL). Non-interactive: a
    missing name is an error; a missing template falls back to agentos-docker when a
    name was supplied (automation / `agno create <name> --json`), matching prior
    behavior.
    """
    interactive = not json_output and stdin_is_interactive()

    if template_url is None and template is None:
        if interactive:
            template = _prompt_template()
        elif name is not None:
            # Explicit name in automation: keep the historical docker default.
            template = DEFAULT_TEMPLATE
        else:
            raise CLIError(
                "A project name is required in non-interactive mode.",
                hint="Pass a directory name, and optionally --template / -t (one of: "
                + ", ".join(TEMPLATE_ORDER)
                + "), or run `agno create` in a terminal.",
            )

    if name is None:
        if template_url is not None:
            default_name = _default_name_from_url(template_url)
        else:
            default_name = template or DEFAULT_TEMPLATE
        if interactive:
            name = _prompt_project_name(default_name)
        else:
            raise CLIError(
                "A project name is required in non-interactive mode.",
                hint="Pass a directory name: agno create <name> [--template ...] [--json]",
            )

    return name, template, template_url


def create(
    name: Optional[str] = typer.Argument(
        None,
        help="Directory name for the new AgentOS project. Prompted interactively when omitted.",
    ),
    template: Optional[str] = typer.Option(
        None,
        "--template",
        "-t",
        help="Starter template: " + ", ".join(TEMPLATE_ORDER) + ". Prompted interactively when omitted.",
        show_default=False,
    ),
    template_url: Optional[str] = typer.Option(
        None, "--url", "-u", help="Clone from a custom template repository URL instead."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption."),
) -> None:
    """Create a new AgentOS project from a starter template.

    With no arguments, prompts for a starter template and project directory name
    (same flow as the legacy `ag infra create`).
    """
    try:
        name, template, template_url = _resolve_create_inputs(name, template, template_url, json_output=json_output)
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


def _create(name: str, template: Optional[str], template_url: Optional[str]) -> Dict[str, Any]:
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
        chosen = template or DEFAULT_TEMPLATE
        repo_url = TEMPLATES.get(chosen, "")
        if not repo_url:
            raise CLIError(
                "Unknown template: " + chosen,
                hint="Available templates: " + ", ".join(TEMPLATE_ORDER) + ", or pass --url for a custom repo.",
            )
        template_label = chosen

    _clone(repo_url, target)
    return {"path": str(target), "template": template_label}
