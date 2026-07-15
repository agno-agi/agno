"""`agno create` and `agno up/down/restart` behavior (git and docker are faked)."""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agnoctl.commands.create as create_module
import agnoctl.commands.lifecycle as lifecycle_module
from agnoctl.commands.lifecycle import find_compose_file
from agnoctl.errors import CLIError
from agnoctl.main import app

runner = CliRunner()


class FakeGit:
    """Simulates `git clone` by scaffolding a template directory."""

    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if self.returncode == 0 and args[:2] == ["git", "clone"]:
            target = Path(args[-1])
            (target / ".git").mkdir(parents=True)
            (target / "docker-compose.yml").write_text("services: {}\n")
            (target / "example.env").write_text("KEY=value\n")
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
    assert (project / "docker-compose.yml").exists()
    assert not (project / ".git").exists()
    # create clones only: it ships example.env but never seeds .env itself.
    assert (project / "example.env").exists()
    assert not (project / ".env").exists()
    assert "secrets" not in payload
    clone_args = fake_git.calls[0]
    assert "https://github.com/agno-agi/agentos-docker" in clone_args


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
