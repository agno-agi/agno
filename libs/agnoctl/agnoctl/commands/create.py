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

import questionary  # type: ignore[import-not-found]
import typer
from rich import box
from rich.console import Group
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agnoctl.commands._common import handle_cli_error, stdin_is_interactive, validate_project_name
from agnoctl.commands.lifecycle import COMPOSE_FILE_NAMES
from agnoctl.console import BRAND_COLOR, MUTED_COLOR, console, emit_json, print_warning, sanitize_terminal_text
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
DEFAULT_PROJECT_NAME = "agent-platform"
TEMPLATE_CHOICES: List[str] = list(TEMPLATES)

TEMPLATE_DESCRIPTIONS: Dict[str, str] = {
    "agentos-docker": "Docker",
    "agentos-aws": "AWS",
    "agentos-azure": "Azure",
    "agentos-fly": "Fly.io",
    "agentos-gcp": "Google Cloud",
    "agentos-helm": "Helm / Kubernetes",
    "agentos-modal": "Modal",
    "agentos-railway": "Railway",
    "agentos-render": "Render",
}

TEMPLATE_SELECTOR_STYLE = questionary.Style(
    [
        ("qmark", ""),
        ("question", "bold"),
        ("instruction", "fg:#bcbcbc"),
        ("pointer", "fg:#ff8700 bold"),
        ("choice_number", "fg:#bcbcbc"),
        ("choice_name", "bold"),
        ("choice_description", "fg:#bcbcbc"),
        ("choice_default", "fg:#ff8700 bold"),
        ("answer", "fg:#ff8700 bold"),
    ]
)

SETUP_PLATFORM_SKILL = Path(".agents/skills/setup-platform/SKILL.md")

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


def _build_template_choices(*, compact: bool = False) -> List[questionary.Choice]:
    """Build the ordered, styled options used by the interactive selector."""
    name_width = max(len(template_name) for template_name in TEMPLATE_CHOICES)
    choices: List[questionary.Choice] = []

    for index, template_name in enumerate(TEMPLATE_CHOICES, start=1):
        is_default = template_name == DEFAULT_TEMPLATE
        title = [
            ("class:choice_number", str(index) + "  "),
            (
                "class:choice_name",
                template_name if compact else template_name.ljust(name_width) + "  ",
            ),
        ]
        if not compact:
            title.append(("class:choice_description", TEMPLATE_DESCRIPTIONS[template_name]))
        if is_default and not compact:
            title.append(("class:choice_default", "  (default)"))
        choices.append(questionary.Choice(title=title, value=template_name, shortcut_key=str(index)))

    return choices


def _build_template_selector() -> questionary.Question:
    """Build the terminal-native arrow-key selector."""
    compact = console.width < 60
    return questionary.select(
        "Template" if compact else "Choose a template",
        choices=_build_template_choices(compact=compact),
        default=DEFAULT_TEMPLATE,
        qmark="",
        pointer="❯",
        style=TEMPLATE_SELECTOR_STYLE,
        instruction="↑↓ move · Enter" if compact else "↑/↓ move  •  1–9 jump  •  Enter select",
        use_shortcuts=True,
        use_arrow_keys=True,
        use_jk_keys=False,
        use_emacs_keys=False,
        use_search_filter=False,
        show_selected=False,
        show_description=False,
    )


def _prompt_template() -> str:
    """Choose a template with arrow keys; Enter keeps the Docker default."""
    try:
        answer = _build_template_selector().unsafe_ask()
    except (KeyboardInterrupt, EOFError):
        raise typer.Abort() from None
    if not isinstance(answer, str) or answer not in TEMPLATES:
        raise typer.Abort()
    return answer


def _prompt_template_by_number() -> str:
    """Use a stable line prompt when terminal redraw is unavailable."""
    console.print(Text("Choose a template", style="bold"))
    for index, template_name in enumerate(TEMPLATE_CHOICES, start=1):
        suffix = "  (default)" if template_name == DEFAULT_TEMPLATE else ""
        console.print(
            Text.assemble(
                (str(index) + "  ", MUTED_COLOR),
                (template_name + "  ", "bold"),
                (TEMPLATE_DESCRIPTIONS[template_name], MUTED_COLOR),
                (suffix, BRAND_COLOR),
            )
        )

    while True:
        answer = str(typer.prompt("Template", default="1")).strip()
        if answer in TEMPLATES:
            return answer
        if answer.isdigit():
            index = int(answer)
            if 1 <= index <= len(TEMPLATE_CHOICES):
                return TEMPLATE_CHOICES[index - 1]
        print_warning("Choose a template from 1 to " + str(len(TEMPLATE_CHOICES)) + ".")


def _supports_arrow_selector() -> bool:
    """Use terminal redraw only when output and terminal capabilities support it."""
    return console.is_terminal and os.environ.get("TERM", "").lower() != "dumb"


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
                hint="Pass a name, for example: uvx agno create " + DEFAULT_PROJECT_NAME,
            )
        # A bad --template should fail here, before the user answers the name prompt.
        if template is not None and template_url is None:
            _validate_template(template)
        console.print()
        console.print(_build_create_intro())
        console.print()
        if template_url is None and template is None:
            template = _prompt_template() if _supports_arrow_selector() else _prompt_template_by_number()
            console.print()
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
        if json_output or not console.is_terminal:
            payload = _create(name=name, template=template, template_url=template_url)
        else:
            template_label = template_url or template
            with console.status(
                _build_creation_status(name, template_label),
                spinner="line",
                spinner_style=BRAND_COLOR,
            ):
                payload = _create(name=name, template=template, template_url=template_url)
    except CLIError as e:
        raise handle_cli_error(e, json_output)

    if json_output:
        emit_json(payload)
        return
    _print_completion(
        name=name,
        template_label=str(payload["template"]),
        project_dir=Path(str(payload["path"])),
        recommend_setup_skill=not template_url,
    )


def _print_completion(
    name: str,
    template_label: str,
    project_dir: Path,
    *,
    recommend_setup_skill: bool,
) -> None:
    """Render the human success summary and supported setup paths."""
    has_setup_skill = recommend_setup_skill and (project_dir / SETUP_PLATFORM_SKILL).is_file()
    has_compose_file = any(
        (directory / compose_file).is_file()
        for directory in (project_dir, project_dir / "infra")
        for compose_file in COMPOSE_FILE_NAMES
    )

    console.print()
    console.print(_build_created_panel(name, template_label))
    console.print()
    console.print(
        _build_next_steps(
            name,
            has_setup_skill=has_setup_skill,
            has_compose_file=has_compose_file,
            has_env_file=(project_dir / ".env").is_file(),
        )
    )


def _build_create_intro() -> Panel:
    copy = Group(
        Text("Build your agent platform.", style="bold"),
        Text(
            "Let's scaffold a new project for you, please choose your cloud provider.",
            style=MUTED_COLOR,
        ),
    )
    return Panel.fit(
        copy,
        title=Text("Create an AgentOS", style="bold " + BRAND_COLOR),
        title_align="left",
        border_style=BRAND_COLOR,
        box=box.ROUNDED,
        padding=(0, 2),
    )


def _build_creation_status(name: str, template_label: str) -> Text:
    return Text.assemble(
        "Creating ",
        (sanitize_terminal_text(name), "bold"),
        " from ",
        (sanitize_terminal_text(template_label), "bold"),
        "...",
    )


def _build_created_panel(name: str, template_label: str) -> Panel:
    summary = Table.grid(padding=(0, 2), pad_edge=False)
    summary.add_column(style=MUTED_COLOR, no_wrap=True)
    summary.add_column(overflow="fold")
    summary.add_row("Project", Text(sanitize_terminal_text(name), style="bold", overflow="fold"))
    summary.add_row("Template", Text(sanitize_terminal_text(template_label), style="bold", overflow="fold"))
    summary.add_row("Location", Text(sanitize_terminal_text("./" + name), style="bold", overflow="fold"))
    return Panel.fit(
        summary,
        title=Text("AgentOS created", style="bold chartreuse3"),
        title_align="left",
        border_style="chartreuse3",
        box=box.ROUNDED,
        padding=(0, 2),
    )


def _command(command: str, *, left: int = 2) -> Padding:
    return Padding(Text(sanitize_terminal_text(command), style="bold", overflow="fold"), (0, 0, 0, left))


def _setup_body(title: Text, instruction: str, command: str) -> Group:
    return Group(
        title,
        Text(instruction, style=MUTED_COLOR),
        _command(command),
    )


def _build_recommended_setup() -> Panel:
    return Panel.fit(
        Group(
            Text("Use a coding agent", style="bold"),
            Text("Ask your coding agent:", style=MUTED_COLOR),
            Text(""),
            _command("Run the setup-platform skill in .agents/skills/", left=0),
        ),
        title=Text("Recommended", style="bold " + BRAND_COLOR),
        title_align="left",
        border_style=BRAND_COLOR,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _build_next_steps(
    name: str,
    *,
    has_setup_skill: bool,
    has_compose_file: bool,
    has_env_file: bool,
) -> Group:
    steps = Table.grid(padding=(0, 1), pad_edge=False)
    steps.add_column(justify="right", no_wrap=True)
    steps.add_column()

    open_project = Group(
        Text("Open the project", style="bold"),
        _command("cd " + name),
    )
    steps.add_row(Text("  1", style="bold " + BRAND_COLOR), open_project)

    if has_setup_skill:
        setup_title = Text("Set up the platform", style="bold")
        recommended_setup = _build_recommended_setup()
        if has_compose_file:
            instruction = (
                "Add your secrets to .env, then run:"
                if has_env_file
                else "Follow the template setup instructions, then run:"
            )
            setup = Group(
                setup_title,
                recommended_setup,
                Text(""),
                _setup_body(Text("Or set it up manually", style="bold"), instruction, "uvx agno up"),
            )
        else:
            setup = Group(
                setup_title,
                recommended_setup,
                Text(""),
                Text("Or set it up manually", style="bold"),
                Text(
                    "Follow the template's setup instructions to finish configuring and start the project.",
                    style=MUTED_COLOR,
                ),
            )
    elif has_compose_file:
        instruction = (
            "Add your secrets to .env, then run:"
            if has_env_file
            else "Follow the template setup instructions, then run:"
        )
        setup = _setup_body(Text("Set up the platform", style="bold"), instruction, "uvx agno up")
    else:
        setup = Group(
            Text("Follow the template guide", style="bold"),
            Text(
                "Use the template's setup instructions to finish configuring and start the project.",
                style=MUTED_COLOR,
            ),
        )

    steps.add_row("", Text(""))
    steps.add_row(Text("  2", style="bold " + BRAND_COLOR), setup)

    return Group(
        Text("Next steps", style="bold"),
        Text(""),
        steps,
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
