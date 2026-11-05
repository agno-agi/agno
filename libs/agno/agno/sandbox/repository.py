"""Prepare a session's pinned repository inside its sandbox before starting the model."""

import base64
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from agno.sandbox.base import SandboxError


@dataclass(frozen=True)
class Repository:
    """GitHub repository whose branch is pinned on a sandbox session's first turn."""

    url: str
    branch: str = "main"

    def __post_init__(self) -> None:
        validate_repository({"url": self.url, "branch": self.branch})


def validate_repository(value: Any) -> Dict[str, str]:
    """Validate repository configuration without Git or network access."""
    if not isinstance(value, dict) or set(value) != {"url", "branch"}:
        raise ValueError("repository requires exactly url and branch")
    url, branch = value["url"], value["branch"]
    if (
        not isinstance(url, str)
        or not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url)
        or any(part in (".", "..") for part in url.split("/")[-2:])
    ):
        raise ValueError("repository.url must be a GitHub HTTPS repository without credentials")
    # git check-ref-format --branch rules, without requiring Git on the service host.
    if (
        not isinstance(branch, str)
        or not branch
        or branch == "HEAD"
        or branch.startswith("-")
        or branch.endswith(".")
        or ".." in branch
        or "@{" in branch
        or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", branch)
        or any(not part or part.startswith(".") or part.endswith(".lock") for part in branch.split("/"))
    ):
        raise ValueError("repository.branch must be a valid Git branch name")
    return dict(value)


def validate_repository_override(metadata: Any, repository: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Validate an optional first-turn pin, including on turns where the marker wins."""
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        raise ValueError("Run metadata must be a JSON object")
    if "repository" not in metadata:
        return None
    value = metadata["repository"]
    if not isinstance(value, dict) or set(value) not in ({"commit"}, {"branch"}):
        raise ValueError("metadata.repository requires exactly commit or branch; url cannot be overridden")
    if repository is None:
        raise ValueError("metadata.repository requires agent.repository=Repository(...)")
    if "branch" in value:
        validate_repository({**repository, "branch": value["branch"]})
        return dict(value)
    if not isinstance(value["commit"], str) or not re.fullmatch(r"[0-9a-fA-F]{40}", value["commit"]):
        raise ValueError("metadata.repository.commit must be a full 40-hex commit SHA")
    return {"commit": value["commit"].lower()}


class RepositoryPreparationError(SandboxError):
    """A retryable preparation failure before any model or tools have run."""


def _read_pin(native: Path, repository: Dict[str, str]) -> Dict[str, str]:
    try:
        pin = json.loads((native / "repository.json").read_text())
        if (
            not isinstance(pin, dict)
            or set(pin) not in ({"url", "branch", "commit"}, {"url", "branch", "commit", "configured_branch"})
            or pin["url"] != repository["url"]
            or pin.get("configured_branch", pin["branch"]) != repository["branch"]
            or not isinstance(pin["commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", pin["commit"])
        ):
            raise ValueError
        validate_repository({"url": pin["url"], "branch": pin["branch"]})
    except (OSError, ValueError):
        raise ValueError("Restored repository does not match the configured repository and pinned source") from None
    return {key: pin[key] for key in ("url", "branch", "commit")}


def _exclude_uploads(checkout: Path) -> None:
    """Keep attachments staged under the checkout's .agno/ out of git status and git add."""
    exclude = checkout / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    existing = exclude.read_text() if exclude.is_file() else ""
    if "/.agno/" not in existing.splitlines():
        with exclude.open("a") as handle:
            handle.write(("" if not existing or existing.endswith("\n") else "\n") + "/.agno/\n")


def _check_env() -> None:
    if "GITHUB_TOKEN" in os.environ:
        raise ValueError("Sandbox repository access requires GITHUB_READ_TOKEN; remove GITHUB_TOKEN")


def _prepare(
    repository: Dict[str, str],
    workspace: Path,
    native: Path,
    *,
    resume: bool,
    override: Optional[Dict[str, str]] = None,
) -> Path:
    repository = validate_repository(repository)
    override = validate_repository_override({"repository": override} if override is not None else None, repository)
    _check_env()
    target = workspace / "repository"
    marker = native / "repository.json"
    staging = workspace / ".repository-prepare"
    temporary = native / "repository.json.tmp"
    moved = False
    try:
        if staging.exists():
            shutil.rmtree(staging)
        if marker.exists():
            _read_pin(native, repository)
            if not (target / ".git").is_dir():
                raise RepositoryPreparationError("Repository checkpoint is missing its checkout")
            # Preserve the engineer's commits and uncommitted files on later turns.
            _exclude_uploads(target)
            return target
        if resume:
            raise RepositoryPreparationError("Repository checkpoint is missing its source identity")
        if target.exists():
            raise ValueError("Repository checkpoint is missing its source identity")
        staging.mkdir(parents=True)
        # Discard inherited Git overrides, helpers and tracing. Authentication exists only
        # in the child environment, never in argv, a remote URL, or a Git config file.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        token = env.pop("GITHUB_READ_TOKEN", None)
        env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        settings = [("http.followRedirects", "false"), ("credential.helper", ""), ("core.hooksPath", os.devnull)]
        if token:
            encoded = base64.b64encode(("x-access-token:" + token).encode()).decode()
            settings.append(("http.https://github.com/.extraheader", "Authorization: Basic " + encoded))
        env["GIT_CONFIG_COUNT"] = str(len(settings))
        for index, (key, value) in enumerate(settings):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value

        def git(*args: str) -> str:
            try:
                result = subprocess.run(
                    ["git", *args], cwd=staging, env=env, capture_output=True, text=True, timeout=120
                )
                if result.returncode:
                    raise ValueError
                return result.stdout.strip()
            except (OSError, ValueError, subprocess.SubprocessError):
                raise RepositoryPreparationError(
                    "Repository preparation failed; check repository access and branch"
                ) from None

        git("init", "--quiet")
        git("remote", "add", "origin", repository["url"])
        branch = (override or {}).get("branch", repository["branch"])
        commit = (override or {}).get("commit")
        if commit is None:
            ref = "refs/heads/" + branch
            resolved = git("ls-remote", "--exit-code", "--refs", "origin", ref).split()
            if len(resolved) != 2 or resolved[1] != ref or not re.fullmatch(r"[0-9a-f]{40}", resolved[0]):
                raise RepositoryPreparationError("Repository preparation failed; check repository access and branch")
            commit = resolved[0]
        git("fetch", "--depth=1", "origin", commit)
        git("checkout", "--detach", commit)
        if git("rev-parse", "HEAD") != commit:
            raise RepositoryPreparationError("Repository preparation failed; checkout does not match the pinned commit")
        _exclude_uploads(staging)
        staging.rename(target)
        moved = True
        native.mkdir(parents=True, exist_ok=True)
        pin = {"url": repository["url"], "branch": branch, "commit": commit}
        if branch != repository["branch"]:
            # Keep agent configuration identity separate from the effective first-turn branch.
            pin["configured_branch"] = repository["branch"]
        temporary.write_text(json.dumps(pin, sort_keys=True))
        temporary.replace(marker)
        return target
    except OSError:
        raise RepositoryPreparationError("Repository preparation failed; check workspace storage") from None
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if temporary.is_file():
            temporary.unlink()
        if moved and not marker.exists():
            shutil.rmtree(target)


async def _aprepare(
    repository: Dict[str, str],
    workspace: Path,
    native: Path,
    *,
    resume: bool,
    override: Optional[Dict[str, str]] = None,
) -> Path:
    # Drain filesystem work before cancellation can hand this workspace to a retry.
    from agno.sandbox.checkpoint import _thread

    return await _thread(_prepare, repository, workspace, native, resume=resume, override=override)
