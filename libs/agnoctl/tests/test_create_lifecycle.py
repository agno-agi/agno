"""`agno create` and `agno up/down/restart` behavior (git and docker are faked)."""

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agnoctl.commands.create as create_module
import agnoctl.commands.lifecycle as lifecycle_module
from agnoctl.commands.lifecycle import find_compose_file
from agnoctl.errors import CLIError
from agnoctl.main import app
from tests.conftest import all_output as _all_output

runner = CliRunner()


class FakeGit:
    """Simulates `git clone` by scaffolding a template directory."""

    def __init__(
        self,
        returncode: int = 0,
        with_example_env: bool = True,
        existing_env=None,
        symlink_example_env: bool = False,
    ):
        self.returncode = returncode
        self.with_example_env = with_example_env
        self.existing_env = existing_env
        self.symlink_example_env = symlink_example_env
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if self.returncode == 0 and args[:2] == ["git", "clone"]:
            target = Path(args[-1])
            (target / ".git").mkdir(parents=True)
            (target / "docker-compose.yml").write_text("services: {}\n")
            if self.symlink_example_env:
                (target / "example.env").symlink_to(target.parent / "outside.env")
            elif self.with_example_env:
                (target / "example.env").write_text("KEY=value\n")
            if self.existing_env is not None:
                (target / ".env").write_text(self.existing_env)
        return subprocess.CompletedProcess(args, self.returncode, stdout="", stderr="boom" if self.returncode else "")


@pytest.fixture
def fake_git(monkeypatch, tmp_path):
    fake = FakeGit()
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)
    return fake


def test_create_scaffolds_project(fake_git, tmp_path):
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


def test_create_interactive_uses_defaults(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    result = runner.invoke(app, ["create"], input="\n\n")

    assert result.exit_code == 0, result.output
    assert "Create an AgentOS" in result.output
    assert "1. agentos-docker (default)" in result.output
    assert "Template [1]" in result.output
    assert "Project name [agentos]" in result.output
    assert create_module.TEMPLATES["agentos-docker"] in fake_git.calls[0]
    assert (tmp_path / "agentos" / ".env").read_text() == "KEY=value\n"


def test_create_template_catalog_lists_all_supported_starters():
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


def test_create_interactive_selects_template_and_name(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    render_choice = create_module.TEMPLATE_CHOICES.index("agentos-render") + 1
    result = runner.invoke(app, ["create"], input=str(render_choice) + "\nmy-os\n")

    assert result.exit_code == 0, result.output
    assert create_module.TEMPLATES["agentos-render"] in fake_git.calls[0]
    assert (tmp_path / "my-os" / ".env").exists()


def test_create_interactive_reprompts_invalid_choices(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    invalid_choice = len(create_module.TEMPLATE_CHOICES) + 1
    result = runner.invoke(app, ["create"], input=str(invalid_choice) + "\n2\n../escape\nvalid-os\n")

    assert result.exit_code == 0, result.output
    assert "enter a number from 1 to " + str(len(create_module.TEMPLATE_CHOICES)) in result.output
    assert "Invalid project name" in result.output
    assert create_module.TEMPLATES["agentos-aws"] in fake_git.calls[0]
    assert (tmp_path / "valid-os").exists()


def test_create_interactive_reprompts_existing_default(fake_git, monkeypatch, tmp_path):
    (tmp_path / "agentos").mkdir()
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    result = runner.invoke(app, ["create"], input="\n\nfresh-os\n")

    assert result.exit_code == 0, result.output
    warning = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.stderr).split())
    assert "already exists. Choose another name." in warning
    assert (tmp_path / "fresh-os" / ".env").exists()


def test_create_explicit_name_keeps_default_without_prompt(fake_git, monkeypatch, tmp_path):
    def fail_prompt(*args, **kwargs):
        pytest.fail("explicit create must not prompt")

    monkeypatch.setattr(create_module.typer, "prompt", fail_prompt)
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    result = runner.invoke(app, ["create", "my-os"])

    assert result.exit_code == 0, result.output
    assert create_module.TEMPLATES["agentos-docker"] in fake_git.calls[0]
    assert (tmp_path / "my-os").exists()


def test_create_explicit_template_prompts_only_for_name(fake_git, monkeypatch, tmp_path):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    result = runner.invoke(app, ["create", "-t", "agentos-fly"], input="fly-os\n")

    assert result.exit_code == 0, result.output
    assert "Choose a template" not in result.output
    assert "Project name [agentos]" in result.output
    assert create_module.TEMPLATES["agentos-fly"] in fake_git.calls[0]
    assert (tmp_path / "fly-os").exists()


def test_create_bare_json_requires_name_without_prompt(fake_git, monkeypatch):
    def fail_prompt(*args, **kwargs):
        pytest.fail("JSON create must not prompt")

    monkeypatch.setattr(create_module.typer, "prompt", fail_prompt)
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: True)

    result = runner.invoke(app, ["create", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "project name is required" in payload["error"].lower()
    assert fake_git.calls == []


def test_create_bare_noninteractive_requires_name(fake_git, monkeypatch):
    monkeypatch.setattr(create_module, "stdin_is_interactive", lambda: False)

    result = runner.invoke(app, ["create"])

    assert result.exit_code == 1
    assert "project name is required" in result.output.lower()
    assert fake_git.calls == []


def test_create_human_output_is_concise(fake_git):
    result = runner.invoke(app, ["create", "my-os"])

    assert result.exit_code == 0, result.output
    assert "Created my-os from agentos-docker." in result.output
    assert "Add your secrets to my-os/.env, then cd into my-os and run agno up." in result.output
    assert "Next steps" not in result.output
    assert "cp example.env" not in result.output
    assert "agno connect" not in result.output


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
    fake = FakeGit(with_example_env=False)
    monkeypatch.setattr(create_module.subprocess, "run", fake)
    monkeypatch.setattr(create_module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["create", "my-os", "--url", "https://example.com/custom.git"])

    assert result.exit_code == 0, result.output
    assert "No example.env found." in result.output
    assert "Follow the template setup instructions" in result.output
    assert "cd into my-os" in result.output
    assert "run agno up." in result.output


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
