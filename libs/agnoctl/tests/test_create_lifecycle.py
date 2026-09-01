"""`agno create` and `agno up/down/restart` behavior (git and docker are faked)."""

import json
import os
import re
import stat
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console, Group
from rich.text import Text
from typer.testing import CliRunner

import agnoctl.commands.create as create_module
import agnoctl.commands.lifecycle as lifecycle_module
import agnoctl.console as console_module
from agnoctl.commands.lifecycle import find_compose_file
from agnoctl.errors import CLIError
from agnoctl.main import app
from tests.conftest import all_output as _all_output

runner = CliRunner()

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@pytest.fixture(autouse=True)
def stable_console_width(monkeypatch):
    """Keep wide-layout assertions independent from the invoking shell width."""
    monkeypatch.setattr(create_module.console, "_width", 100)
    monkeypatch.setattr(console_module.err_console, "_width", 100)


def _strip_ansi(value: str) -> str:
    return ANSI_ESCAPE.sub("", value)


def _compact_rendered_text(value: str) -> str:
    borders = set("│╭╮╰╯─")
    return "".join(
        character for character in _strip_ansi(value) if not character.isspace() and character not in borders
    )


class FakeGit:
    """Simulates `git clone` by scaffolding a template directory."""

    def __init__(
        self,
        returncode: int = 0,
        with_example_env: bool = True,
        existing_env=None,
        symlink_example_env: bool = False,
        with_setup_skill: bool = True,
        with_compose_file: bool = True,
        error_detail: str = "boom",
    ):
        self.returncode = returncode
        self.with_example_env = with_example_env
        self.existing_env = existing_env
        self.symlink_example_env = symlink_example_env
        self.with_setup_skill = with_setup_skill
        self.with_compose_file = with_compose_file
        self.error_detail = error_detail
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if self.returncode == 0 and args[:2] == ["git", "clone"]:
            target = Path(args[-1])
            (target / ".git").mkdir(parents=True)
            if self.with_compose_file:
                (target / "docker-compose.yml").write_text("services: {}\n")
            if self.with_setup_skill:
                skill = target / create_module.SETUP_PLATFORM_SKILL
                skill.parent.mkdir(parents=True)
                skill.write_text("---\nname: setup-platform\n---\n")
            if self.symlink_example_env:
                (target / "example.env").symlink_to(target.parent / "outside.env")
            elif self.with_example_env:
                (target / "example.env").write_text("KEY=value\n")
            if self.existing_env is not None:
                (target / ".env").write_text(self.existing_env)
        return subprocess.CompletedProcess(
            args,
            self.returncode,
            stdout="",
            stderr=self.error_detail if self.returncode else "",
        )


@pytest.fixture
def fake_git(monkeypatch, tmp_path):
    fake = FakeGit()
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)
    return fake


def test_create_scaffolds_project(fake_git, tmp_path, monkeypatch):
    def fail_status(self, *args, **kwargs):
        pytest.fail("JSON create must not construct human progress output")

    monkeypatch.setattr(Console, "status", fail_status)
    result = runner.invoke(app, ["create", "my-os", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["template"] == "agentos-docker"
    project = tmp_path / "my-os"
    assert payload == {"path": str(project), "template": "agentos-docker"}
    assert (project / "docker-compose.yml").exists()
    assert not (project / ".git").exists()
    assert (project / "example.env").exists()
    assert (project / ".env").read_text() == "KEY=value\n"
    if os.name != "nt":
        assert stat.S_IMODE((project / ".env").stat().st_mode) == 0o600
    clone_args = fake_git.calls[0]
    assert "https://github.com/agno-agi/agentos-docker" in clone_args
    assert result.stderr == ""
    assert "\x1b" not in result.output and "\r" not in result.output
    assert "AgentOS created" not in result.output
    assert "Next steps" not in result.output


def test_create_interactive_uses_defaults(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(create_module, "_prompt_template_by_number", lambda: create_module.DEFAULT_TEMPLATE)

    result = runner.invoke(app, ["create"], input="\n")

    assert result.exit_code == 0, result.output
    assert "Create an AgentOS" in result.output
    assert "Build your agent platform." in result.output
    assert "Let's scaffold a new project for you, please choose your cloud provider." in result.output
    assert "Project name [agent-platform]" in result.output
    assert create_module.TEMPLATES["agentos-docker"] in fake_git.calls[0]
    assert (tmp_path / "agent-platform" / ".env").read_text() == "KEY=value\n"


def test_create_template_selector_lists_all_supported_starters():
    expected = {
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
    assert create_module.TEMPLATES == expected
    assert create_module.TEMPLATE_CHOICES == list(expected)
    assert set(create_module.TEMPLATE_DESCRIPTIONS) == set(expected)

    choices = create_module._build_template_choices()
    assert [choice.value for choice in choices] == create_module.TEMPLATE_CHOICES
    assert [choice.shortcut_key for choice in choices] == [str(index) for index in range(1, 10)]
    labels = ["".join(fragment[1] for fragment in choice.title) for choice in choices]
    for template_name, description, label in zip(
        create_module.TEMPLATE_CHOICES,
        create_module.TEMPLATE_DESCRIPTIONS.values(),
        labels,
    ):
        assert template_name in label
        assert description in label
    assert "(default)" in labels[0]


def test_template_selector_configuration(monkeypatch):
    captured = {}

    class FakeQuestion:
        def unsafe_ask(self):
            return create_module.DEFAULT_TEMPLATE

    def fake_select(message, **kwargs):
        captured["message"] = message
        captured.update(kwargs)
        return FakeQuestion()

    monkeypatch.setattr(create_module.questionary, "select", fake_select)

    assert create_module._prompt_template() == create_module.DEFAULT_TEMPLATE
    assert captured["message"] == "Choose a template"
    assert captured["default"] == create_module.DEFAULT_TEMPLATE
    assert captured["pointer"] == "❯"
    assert "↑/↓ move" in captured["instruction"]
    assert "1–9 jump" in captured["instruction"]
    assert captured["use_arrow_keys"] is True
    assert captured["use_shortcuts"] is True


def test_template_selector_compacts_for_narrow_terminals(monkeypatch):
    captured = {}

    def fake_select(message, **kwargs):
        captured["message"] = message
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(create_module.questionary, "select", fake_select)
    monkeypatch.setattr(create_module.console, "_width", 32)

    create_module._build_template_selector()

    assert captured["message"] == "Template"
    assert captured["instruction"] == "↑↓ move · Enter"
    labels = ["".join(fragment[1] for fragment in choice.title) for choice in captured["choices"]]
    assert labels[0] == "1  agentos-docker"
    assert labels[-1] == "9  agentos-render"
    assert all(
        description not in label for description in create_module.TEMPLATE_DESCRIPTIONS.values() for label in labels
    )
    assert all(len(" ❯ " + label) <= 32 for label in labels)


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("\r", "agentos-docker"),
        ("\x1b[B\r", "agentos-aws"),
        ("\x1b[A\r", "agentos-render"),
        ("8\r", "agentos-railway"),
    ],
)
def test_template_selector_keyboard_navigation(keys, expected):
    with create_pipe_input() as pipe_input:
        pipe_input.send_text(keys)
        with create_app_session(input=pipe_input, output=DummyOutput()):
            assert create_module._prompt_template() == expected


@pytest.mark.skipif(os.name == "nt", reason="the stdlib PTY module is POSIX-only")
def test_create_arrow_selector_transitions_to_name_prompt_in_narrow_pty(tmp_path):
    import fcntl
    import pty
    import select
    import signal
    import struct
    import sys
    import termios
    import time

    repo_root = Path(__file__).resolve().parents[3]
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 32, 0, 0))
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repo_root / "libs" / "agnoctl")
    environment["TERM"] = "xterm-256color"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "agnoctl.main",
            "create",
        ],
        cwd=tmp_path,
        env=environment,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
    )
    os.close(slave_fd)

    output = b""
    sent_selection = False
    sent_abort = False
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                if b"agentos-render" in output and not sent_selection:
                    os.write(master_fd, b"\x1b[B\r")
                    sent_selection = True
                if b"Project name" in output and not sent_abort:
                    process.send_signal(signal.SIGINT)
                    sent_abort = True
            elif process.poll() is not None:
                break
        try:
            return_code = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
            pytest.fail("create did not exit after selecting a template and aborting the name prompt")
    finally:
        os.close(master_fd)

    assert sent_selection is True
    assert sent_abort is True
    assert return_code == 1, output.decode(errors="replace")
    assert output.count(b"agentos-aws") >= 2
    assert b"Project name" in output and b"agent-platform" in output
    assert b"Aborted" in output
    assert list(tmp_path.iterdir()) == []


def test_template_selector_converts_keyboard_interrupt_to_clean_abort():
    with create_pipe_input() as pipe_input:
        pipe_input.send_text("\x03")
        with create_app_session(input=pipe_input, output=DummyOutput()):
            with pytest.raises(create_module.typer.Abort):
                create_module._prompt_template()


def test_create_selector_abort_exits_without_cloning(fake_git, monkeypatch):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(create_module.console, "_force_terminal", True)
    monkeypatch.setenv("TERM", "xterm-256color")

    class AbortedQuestion:
        def unsafe_ask(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(create_module, "_build_template_selector", AbortedQuestion)

    result = runner.invoke(app, ["create"])

    assert result.exit_code == 1
    assert "Aborted." in _all_output(result)
    assert fake_git.calls == []


def test_create_uses_numbered_fallback_when_output_cannot_redraw(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(create_module.console, "_force_terminal", False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(
        create_module,
        "_prompt_template",
        lambda: pytest.fail("redirected output must not use the arrow selector"),
    )

    result = runner.invoke(app, ["create"], input="2\nmy-os\n")

    assert result.exit_code == 0, result.output
    assert "Template [1]" in result.output
    assert create_module.TEMPLATES["agentos-aws"] in fake_git.calls[0]
    assert (tmp_path / "my-os").is_dir()


def test_create_uses_numbered_fallback_for_dumb_terminal(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(create_module.console, "_force_terminal", True)
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setattr(
        create_module,
        "_prompt_template",
        lambda: pytest.fail("TERM=dumb must not use the arrow selector"),
    )

    result = runner.invoke(app, ["create"], input="2\nmy-os\n")

    assert result.exit_code == 0, result.output
    assert create_module.TEMPLATES["agentos-aws"] in fake_git.calls[0]
    assert (tmp_path / "my-os").is_dir()


def test_create_interactive_selects_template_and_name(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(create_module, "_prompt_template_by_number", lambda: "agentos-render")

    result = runner.invoke(app, ["create"], input="my-os\n")

    assert result.exit_code == 0, result.output
    assert create_module.TEMPLATES["agentos-render"] in fake_git.calls[0]
    assert (tmp_path / "my-os" / ".env").exists()


def test_create_interactive_reprompts_invalid_project_name(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(create_module, "_prompt_template_by_number", lambda: "agentos-aws")

    result = runner.invoke(app, ["create"], input="../escape\nvalid-os\n")

    assert result.exit_code == 0, result.output
    output = _strip_ansi(_all_output(result))
    assert "Invalid project name" in output
    assert create_module.TEMPLATES["agentos-aws"] in fake_git.calls[0]
    assert (tmp_path / "valid-os").exists()


def test_create_interactive_reprompts_existing_default(fake_git, monkeypatch, tmp_path):
    (tmp_path / "agent-platform").mkdir()
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(create_module, "_prompt_template_by_number", lambda: create_module.DEFAULT_TEMPLATE)

    result = runner.invoke(app, ["create"], input="\nfresh-os\n")

    assert result.exit_code == 0, result.output
    warning = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.stderr).split())
    assert "already exists. Choose another name." in warning
    assert (tmp_path / "fresh-os" / ".env").exists()


def test_create_explicit_name_keeps_default_without_prompt(fake_git, monkeypatch, tmp_path):
    def fail_prompt(*args, **kwargs):
        pytest.fail("explicit create must not prompt")

    monkeypatch.setattr(create_module.typer, "prompt", fail_prompt)
    monkeypatch.setattr(create_module, "_build_template_selector", fail_prompt)
    monkeypatch.setattr(create_module, "_prompt_template_by_number", fail_prompt)
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    result = runner.invoke(app, ["create", "my-os"])

    assert result.exit_code == 0, result.output
    assert create_module.TEMPLATES["agentos-docker"] in fake_git.calls[0]
    assert (tmp_path / "my-os").exists()


def test_create_explicit_template_prompts_only_for_name(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(
        create_module,
        "_build_template_selector",
        lambda: pytest.fail("an explicit template must bypass the selector"),
    )
    monkeypatch.setattr(
        create_module,
        "_prompt_template_by_number",
        lambda: pytest.fail("an explicit template must bypass the numbered fallback"),
    )

    result = runner.invoke(app, ["create", "-t", "agentos-fly"], input="fly-os\n")

    assert result.exit_code == 0, result.output
    assert "Choose a template" not in result.output
    assert "Project name [agent-platform]" in result.output
    assert create_module.TEMPLATES["agentos-fly"] in fake_git.calls[0]
    assert (tmp_path / "fly-os").exists()


def test_create_bare_json_requires_name_without_prompt(fake_git, monkeypatch):
    def fail_prompt(*args, **kwargs):
        pytest.fail("JSON create must not prompt")

    monkeypatch.setattr(create_module.typer, "prompt", fail_prompt)
    monkeypatch.setattr(create_module, "_build_template_selector", fail_prompt)
    monkeypatch.setattr(create_module, "_prompt_template_by_number", fail_prompt)
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    result = runner.invoke(app, ["create", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "project name is required" in payload["error"].lower()
    assert payload["hint"] == "Pass a name, for example: uvx agno create agent-platform"
    assert result.stderr == ""
    assert "\x1b" not in result.output and "\r" not in result.output
    assert "Create an AgentOS" not in result.output
    assert fake_git.calls == []


def test_create_bare_noninteractive_requires_name(fake_git, monkeypatch):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: False)
    monkeypatch.setattr(
        create_module,
        "_build_template_selector",
        lambda: pytest.fail("non-interactive create must not construct a selector"),
    )
    monkeypatch.setattr(
        create_module,
        "_prompt_template_by_number",
        lambda: pytest.fail("non-interactive create must not construct a numbered fallback"),
    )

    result = runner.invoke(app, ["create"])

    assert result.exit_code == 1
    assert "project name is required" in result.output.lower()
    assert "uvx agno create agent-platform" in _all_output(result)
    assert fake_git.calls == []


def test_create_human_output_guides_recommended_and_manual_setup(fake_git):
    result = runner.invoke(app, ["create", "my-os"])

    assert result.exit_code == 0, result.output
    assert "AgentOS created" in result.output
    assert "Project" in result.output and "my-os" in result.output
    assert "Template" in result.output and "agentos-docker" in result.output
    assert "Location" in result.output and "./my-os" in result.output
    assert "Next steps" in result.output
    assert "Open the project" in result.output
    assert "cd my-os" in result.output
    assert "Set up the platform" in result.output
    assert "Recommended" in result.output
    assert "Use a coding agent" in result.output
    assert "Ask your coding agent:" in result.output
    ask_line = next(index for index, line in enumerate(result.output.splitlines()) if "Ask your coding agent:" in line)
    assert _compact_rendered_text(result.output.splitlines()[ask_line + 1]) == ""
    assert "Run the setup-platform skill in .agents/skills/" in result.output
    assert "Or set it up manually" in result.output
    assert "Add your secrets to .env, then run:" in result.output
    assert "uvx agno up" in result.output
    assert "run agno up" not in result.output
    assert "cp example.env" not in result.output
    assert "agno connect" not in result.output


def test_create_recommended_setup_keeps_truthful_manual_fallback_without_compose(monkeypatch, tmp_path):
    fake = FakeGit(with_setup_skill=True, with_compose_file=False)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os"])

    assert result.exit_code == 0, result.output
    assert "Recommended" in result.output
    assert "Run the setup-platform skill in .agents/skills/" in result.output
    assert "Or set it up manually" in result.output
    assert "Follow the template's setup instructions" in result.output
    assert "uvx agno up" not in result.output


def test_create_does_not_overwrite_existing_env(monkeypatch, tmp_path):
    fake = FakeGit(existing_env="KEEP_ME=true\n")
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os", "--json"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "my-os" / ".env").read_text() == "KEEP_ME=true\n"


def test_create_custom_url_without_example_env(monkeypatch, tmp_path):
    fake = FakeGit(with_example_env=False)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["create", "my-os", "--url", "https://example.com/custom.git", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "my-os" / ".env").exists()


def test_create_custom_url_without_example_env_has_truthful_handoff(monkeypatch, tmp_path):
    # A custom repository does not earn Agno's recommendation merely by
    # shipping an arbitrary skill with the same name as the maintained one.
    fake = FakeGit(with_example_env=False, with_setup_skill=True)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os", "--url", "https://example.com/custom.git"])

    assert result.exit_code == 0, result.output
    assert "Follow the template setup instructions" in result.output
    assert "cd my-os" in result.output
    assert "uvx agno up" in result.output
    assert "setup-platform skill" not in result.output
    assert "Recommended" not in result.output


def test_create_custom_url_is_rendered_literally(monkeypatch, tmp_path):
    template_url = "https://example.com/" + ("long-segment-" * 8) + "template[blue].git"
    fake = FakeGit(with_setup_skill=False)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os", "--url", template_url])

    assert result.exit_code == 0, result.output
    compact_output = _compact_rendered_text(result.output)
    assert template_url in compact_output
    assert "…" not in result.output
    assert template_url in fake.calls[0]


def test_create_custom_url_terminal_controls_are_rendered_inert(monkeypatch, tmp_path):
    template_url = "https://example.com/template\x1b[2J.git"
    fake = FakeGit(with_setup_skill=False)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os", "--url", template_url])

    assert result.exit_code == 0, result.output
    assert "\x1b[2J" not in result.output
    assert "\\x1b[2J" in result.output
    assert template_url in fake.calls[0]


def test_create_long_project_name_preserves_copyable_command(fake_git):
    name = "agent-platform-" + ("x" * 90)

    result = runner.invoke(app, ["create", name])

    assert result.exit_code == 0, result.output
    compact_output = _compact_rendered_text(result.output)
    assert "cd" + name in compact_output
    assert "./" + name in compact_output
    assert "…" not in result.output


def test_create_human_error_renders_dynamic_value_literally(fake_git):
    result = runner.invoke(app, ["create", "[blue]"])

    assert result.exit_code == 1
    assert "Invalid project name: [blue]" in _strip_ansi(_all_output(result))
    assert fake_git.calls == []


def test_create_custom_url_without_supported_setup_follows_template(monkeypatch, tmp_path):
    fake = FakeGit(with_example_env=False, with_setup_skill=False, with_compose_file=False)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os", "--url", "https://example.com/custom.git"])

    assert result.exit_code == 0, result.output
    assert "cd my-os" in result.output
    assert "Follow the template guide" in result.output
    assert "Use the template's setup instructions" in result.output
    assert "setup-platform skill" not in result.output
    assert "uvx agno up" not in result.output


def test_create_output_fits_narrow_terminal(fake_git, monkeypatch):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(create_module, "_prompt_template_by_number", lambda: create_module.DEFAULT_TEMPLATE)
    narrow_console = Console(width=32, color_system=None, force_terminal=False)
    monkeypatch.setattr(create_module, "console", narrow_console)

    result = runner.invoke(app, ["create"], input="\n")

    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.output)
    assert all(len(line) <= 32 for line in output.splitlines())
    assert ".agents/skills/" in output
    assert "uvx agno up" in output
    assert "…" not in output


@pytest.mark.parametrize(
    ("has_setup_skill", "has_compose_file", "has_env_file"),
    [
        (True, True, True),
        (True, True, False),
        (True, False, False),
        (False, True, True),
        (False, True, False),
        (False, False, False),
    ],
)
def test_next_steps_fit_narrow_terminal_for_every_setup_path(
    has_setup_skill,
    has_compose_file,
    has_env_file,
):
    stream = StringIO()
    render_console = Console(file=stream, width=32, color_system=None)
    render_console.print(
        create_module._build_next_steps(
            "agent-platform",
            has_setup_skill=has_setup_skill,
            has_compose_file=has_compose_file,
            has_env_file=has_env_file,
        )
    )
    output = stream.getvalue()
    compact_output = _compact_rendered_text(output)

    assert all(len(line) <= 32 for line in output.splitlines())
    assert "…" not in output
    if has_setup_skill:
        assert "Runthesetup-platformskillin.agents/skills/" in compact_output
    else:
        assert "setup-platform" not in output
    if has_compose_file:
        assert "uvxagnoup" in compact_output
    else:
        assert "uvxagnoup" not in compact_output
    if has_setup_skill and not has_compose_file:
        assert "Orsetitupmanually" in compact_output
        assert "Followthetemplate'ssetupinstructions" in compact_output


def test_create_rich_renderables_preserve_text_across_color_modes():
    screen = Group(
        create_module._build_create_intro(),
        Text(""),
        create_module._build_created_panel("agent-platform", "agentos-docker"),
        Text(""),
        create_module._build_next_steps(
            "agent-platform",
            has_setup_skill=True,
            has_compose_file=True,
            has_env_file=True,
        ),
    )

    def render(*, force_terminal: bool, color_system=None, no_color: bool = False) -> str:
        stream = StringIO()
        render_console = Console(
            file=stream,
            width=80,
            force_terminal=force_terminal,
            color_system=color_system,
            no_color=no_color,
        )
        render_console.print(screen)
        return stream.getvalue()

    plain = render(force_terminal=False)
    colored = render(force_terminal=True, color_system="256")
    no_color = render(force_terminal=True, color_system="256", no_color=True)

    assert "\x1b" not in plain
    assert "\x1b" in colored
    assert _strip_ansi(colored) == plain
    assert "Recommended" in plain
    assert "\x1b[38;5;208m" not in no_color
    assert "\x1b[38;5;250m" not in no_color
    assert "\x1b[38;5;76m" not in no_color
    assert "\x1b[1;36m" not in no_color
    assert _strip_ansi(no_color) == plain
    assert "Recommended" in no_color


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_copy_example_env_rejects_symlinked_source(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.env"
    outside.write_text("SECRET=outside\n")
    (project / "example.env").symlink_to(outside)

    with pytest.raises(CLIError, match="symlinked"):
        create_module._copy_example_env(project)

    assert not (project / ".env").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_copy_example_env_rejects_dangling_destination_symlink(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "example.env").write_text("KEY=value\n")
    outside = tmp_path / "outside.env"
    (project / ".env").symlink_to(outside)

    with pytest.raises(CLIError, match="symlinked"):
        create_module._copy_example_env(project)

    assert not outside.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_create_symlinked_example_env_fails_cleanly_via_cli(monkeypatch, tmp_path):
    fake = FakeGit(symlink_example_env=True)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os"])

    assert result.exit_code == 1
    assert "symlinked" in _all_output(result)
    assert not (tmp_path / "my-os").exists()

    # The retry must hit the same refusal, not "directory already exists".
    second = runner.invoke(app, ["create", "my-os", "--json"])
    assert second.exit_code == 1
    assert "symlinked" in json.loads(second.output)["error"]
    assert not (tmp_path / "my-os").exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_create_reports_leftover_dir_when_cleanup_fails(monkeypatch, tmp_path):
    fake = FakeGit(symlink_example_env=True)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "my-os"

    real_rmtree = create_module.shutil.rmtree

    def locked_rmtree(path, *args, **kwargs):
        if Path(path) == target:
            raise OSError("locked")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(create_module.shutil, "rmtree", locked_rmtree)

    result = runner.invoke(app, ["create", "my-os", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "symlinked" in payload["error"]
    assert str(target) in payload["hint"]
    assert target.exists()


def test_create_empty_template_is_rejected(fake_git):
    result = runner.invoke(app, ["create", "my-os", "-t", "", "--json"])

    assert result.exit_code == 1
    assert "Unknown template" in json.loads(result.output)["error"]
    assert fake_git.calls == []


def test_create_unknown_template_rejected_before_name_prompt(fake_git, monkeypatch):
    def fail_prompt(*args, **kwargs):
        pytest.fail("a bad --template must fail before any prompt")

    monkeypatch.setattr(create_module.typer, "prompt", fail_prompt)
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    result = runner.invoke(app, ["create", "-t", "bogus"])

    assert result.exit_code == 1
    assert "Unknown template" in _all_output(result)
    assert fake_git.calls == []


@pytest.mark.parametrize("name", ["../escape", "a/b", "/tmp/abs", ".."])
def test_create_rejects_path_traversal_names(fake_git, name):
    result = runner.invoke(app, ["create", name, "--json"])
    assert result.exit_code == 1
    assert "Invalid project name" in json.loads(result.output)["error"]
    # git clone must never have run for a rejected name.
    assert fake_git.calls == []


def test_create_refuses_existing_directory(fake_git, tmp_path):
    (tmp_path / "my-os").mkdir()
    result = runner.invoke(app, ["create", "my-os", "--json"])
    assert result.exit_code == 1
    assert "already exists" in json.loads(result.output)["error"]


def test_create_unknown_template(fake_git):
    result = runner.invoke(app, ["create", "my-os", "-t", "nope", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "Unknown template" in payload["error"]
    assert "agentos-docker" in payload["hint"]


@pytest.mark.parametrize("template", sorted(create_module.TEMPLATES))
def test_create_known_templates_clone_their_repo(fake_git, template):
    result = runner.invoke(app, ["create", "my-os", "-t", template, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["template"] == template
    assert create_module.TEMPLATES[template] in fake_git.calls[0]


def test_create_custom_url(fake_git):
    result = runner.invoke(app, ["create", "my-os", "-u", "https://example.com/custom.git", "--json"])
    assert result.exit_code == 0, result.output
    assert "https://example.com/custom.git" in fake_git.calls[0]


def test_create_clone_failure(monkeypatch, tmp_path):
    fake = FakeGit(returncode=128)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["create", "my-os", "--json"])
    assert result.exit_code == 1
    assert "git clone failed" in json.loads(result.output)["error"]


def test_create_human_clone_failure_renders_terminal_controls_inert(monkeypatch, tmp_path):
    fake = FakeGit(returncode=128, error_detail="remote says \x1b[2Jcleared")
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os"])
    output = _all_output(result)

    assert result.exit_code == 1
    assert "\x1b[2J" not in output
    assert "\\x1b[2J" in output


# -- infra -----------------------------------------------------------------------------


def test_find_compose_file_autodetect(tmp_path):
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "compose.yaml").write_text("services: {}\n")
    assert find_compose_file(cwd=tmp_path) == tmp_path / "infra" / "compose.yaml"
    # Root-level files win over infra/ ones.
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    assert find_compose_file(cwd=tmp_path) == tmp_path / "docker-compose.yml"


def test_find_compose_file_missing(tmp_path):
    with pytest.raises(CLIError) as exc_info:
        find_compose_file(cwd=tmp_path)
    assert "No compose file" in exc_info.value.message


def test_infra_up_dry_run_command(monkeypatch, tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["up", "--pull", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == [
        "docker",
        "compose",
        "-f",
        str(tmp_path / "docker-compose.yml"),
        "up",
        "-d",
        "--build",
        "--pull",
        "always",
    ]
    assert payload["dry_run"] is True


def test_infra_down_dry_run_volumes(monkeypatch, tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["down", "-v", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["command"][-2:] == ["down", "--volumes"]


def test_infra_up_runs_compose(monkeypatch, tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((list(args), kwargs.get("cwd")))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(lifecycle_module.subprocess, "run", fake_run)
    monkeypatch.setattr(lifecycle_module.shutil, "which", lambda name: "/usr/bin/docker")
    result = runner.invoke(app, ["up", "--json"])
    assert result.exit_code == 0, result.output
    args, cwd = calls[0]
    assert args[:4] == ["docker", "compose", "-f", str(tmp_path / "docker-compose.yml")]
    assert cwd == str(tmp_path)


def test_infra_compose_failure_maps_to_exit_1(monkeypatch, tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        lifecycle_module.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 17, stdout="", stderr="broken"),
    )
    monkeypatch.setattr(lifecycle_module.shutil, "which", lambda name: "/usr/bin/docker")
    result = runner.invoke(app, ["up", "--json"])
    assert result.exit_code == 1
    assert "exited with code 17" in json.loads(result.output)["error"]
