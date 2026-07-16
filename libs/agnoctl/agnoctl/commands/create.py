"""`agno create`: scaffold a new AgentOS project from a starter template.

The mechanism is deliberately simple (inherited from `ag infra create`): shallow-clone
the template repository, strip its git history, and copy example.env to .env. No
registry file is kept — commands operate on the current directory.

Bare `agno create` is interactive: choose a starter template, then name the project.
Explicit arguments keep the command deterministic for scripts and coding agents.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import typer

from agnoctl.commands._common import handle_cli_error, stdin_is_interactive, validate_project_name
from agnoctl.console import emit_json, print_heading, print_info, print_success, print_warning
from agnoctl.errors import CLIError

TEMPLATES: Dict[str, str] = {
    "agentos-docker": "https://github.com/agno-agi/agentos-docker",
    "agentos-aws": "https://github.com/agno-agi/agentos-aws",
    "agentos-azure": "https://github.com/agno-agi/agentos-azure",
    "agentos-fly": "https://github.com/agno-agi/agentos-fly",
    "agentos-gcp": "https://github.com/agno-agi/agentos-gcp",
    "agentos-helm": "https://github.com/agno-agi/agentos-helm",
    "agentos-modal": "https://github.com/agno-agi/agentos-modal",
    "agentos-railway": "https://github.com/agno-agi/agentos-railway",
    "agentos-render": "https://github.com/agno-agi/agentos-render",
}

DEFAULT_TEMPLATE = "agentos-docker"
DEFAULT_PROJECT_NAME = "agentos"
TEMPLATE_CHOICES: List[str] = list(TEMPLATES)

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


def _copy_example_env(project_dir: Path) -> None:
    """Seed a private .env when the template provides example.env.

    Custom templates may use a different environment layout, and a tracked .env must
    never be overwritten.
    """
    example_env = project_dir / "example.env"
    env_file = project_dir / ".env"
    if example_env.is_symlink() or env_file.is_symlink():
        raise CLIError("Refusing to create .env from a symlinked template file.")
    if env_file.exists():
        if not env_file.is_file():
            raise CLIError(str(env_file) + " exists but is not a file.")
        return
    if not example_env.is_file():
        return

    no_follow = getattr(os, "O_NOFOLLOW", 0)
    binary = getattr(os, "O_BINARY", 0)
    source_flags = os.O_RDONLY | no_follow | binary
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow | binary
    created = False
    try:
        with os.fdopen(os.open(example_env, source_flags), "rb") as source:
            destination_fd = os.open(env_file, destination_flags, 0o600)
            created = True
            with os.fdopen(destination_fd, "wb") as destination:
                shutil.copyfileobj(source, destination)
    except OSError as e:
        if created:
            try:
                env_file.unlink()
            except OSError:
                pass
        raise CLIError("Could not create " + str(env_file) + ": " + str(e))


def _prompt_template() -> str:
    """Show a stable numbered menu; Enter chooses agentos-docker."""
    print_info("Choose a template:")
    for index, template_name in enumerate(TEMPLATE_CHOICES, start=1):
        suffix = " (default)" if template_name == DEFAULT_TEMPLATE else ""
        print_info("  " + str(index) + ". " + template_name + suffix)

    while True:
        answer = str(typer.prompt("Template", default=str(TEMPLATE_CHOICES.index(DEFAULT_TEMPLATE) + 1))).strip()
        if answer in TEMPLATES:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(TEMPLATE_CHOICES):
            return TEMPLATE_CHOICES[int(answer) - 1]
        print_warning("Choose a template by name or enter a number from 1 to " + str(len(TEMPLATE_CHOICES)) + ".")


def _prompt_project_name() -> str:
    """Prompt until the project name is safe and available in the current directory."""
    while True:
        name = str(typer.prompt("Project name", default=DEFAULT_PROJECT_NAME)).strip()
        try:
            validate_project_name(name)
        except CLIError as e:
            print_warning(e.message)
            if e.hint:
                print_warning(e.hint)
            continue

        target = Path.cwd() / name
        if target.exists():
            print_warning("The directory " + str(target) + " already exists. Choose another name.")
            continue
        return name


def _validate_template(template: str) -> None:
    if template not in TEMPLATES:
        raise CLIError(
            "Unknown template: " + template,
            hint="Available templates: " + ", ".join(TEMPLATE_CHOICES) + ", or pass --url for a custom repo.",
        )


def _resolve_create_inputs(
    name: Optional[str],
    template: Optional[str],
    template_url: Optional[str],
    *,
    json_output: bool,
) -> Tuple[str, str]:
    """Prompt only for missing interactive input and preserve explicit CLI behavior."""
    interactive = not json_output and stdin_is_interactive()

    if name is None:
        if not interactive:
            raise CLIError(
                "A project name is required in non-interactive mode.",
                hint="Pass a name, for example: agno create agentos",
            )
        # A bad --template should fail here, before the user answers the name prompt.
        if template is not None and template_url is None:
            _validate_template(template)
        print_info("")
        print_heading("Create an AgentOS")
        print_info("")
        if template_url is None and template is None:
            template = _prompt_template()
            print_info("")
        name = _prompt_project_name()

    return name, DEFAULT_TEMPLATE if template is None else template


def create(
    name: Optional[str] = typer.Argument(
        None,
        help="Directory name for the new AgentOS project. Prompt default: " + DEFAULT_PROJECT_NAME + ".",
    ),
    template: Optional[str] = typer.Option(
        None,
        "--template",
        "-t",
        help="Starter template: " + ", ".join(TEMPLATE_CHOICES) + ". Default when omitted: " + DEFAULT_TEMPLATE + ".",
        show_default=False,
    ),
    template_url: Optional[str] = typer.Option(
        None, "--url", "-u", help="Clone from a custom template repository URL instead."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit a single JSON document for machine consumption."),
) -> None:
    """Create a new AgentOS project from a starter template."""
    try:
        name, template = _resolve_create_inputs(
            name,
            template,
            template_url,
            json_output=json_output,
        )
        payload = _create(name=name, template=template, template_url=template_url)
    except CLIError as e:
        raise handle_cli_error(e, json_output)

    if json_output:
        emit_json(payload)
        return
    print_info("")
    print_success("Created " + name + " from " + str(payload["template"]) + ".")
    print_info("")
    env_file = Path(str(payload["path"])) / ".env"
    if env_file.is_file():
        print_info("Add your secrets to " + name + "/.env, then cd into " + name + " and run agno up.")
    else:
        print_info(
            "No example.env found. Follow the template setup instructions, then cd into " + name + " and run agno up."
        )


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
        _validate_template(template)
        repo_url = TEMPLATES[template]
        template_label = template

    _clone(repo_url, target)
    try:
        _copy_example_env(target)
    except CLIError as e:
        # A failed seed must not leave the half-created project behind; a retry
        # would fail "directory already exists" and hide the real error.
        try:
            shutil.rmtree(target)
        except OSError:
            e.hint = "Remove the leftover directory " + str(target) + ", then re-run."
        raise
    return {"path": str(target), "template": template_label}
