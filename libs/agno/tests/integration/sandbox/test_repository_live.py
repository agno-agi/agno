"""Opt-in public GitHub checkout, without model calls or repository credentials."""

import json
import os
import subprocess

import pytest

from agno.sandbox.repository import _aprepare


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("AGNO_TEST_LIVE_REPOSITORY") != "1", reason="Set AGNO_TEST_LIVE_REPOSITORY=1")
async def test_public_github_fetch(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_READ_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    configured = {"url": "https://github.com/octocat/Hello-World", "branch": "master"}
    native = tmp_path / "native"
    checkout = await _aprepare(configured, tmp_path / "workspace", native, resume=False)
    marker = json.loads((native / "repository.json").read_text())
    assert marker["url"] == configured["url"] and marker["branch"] == configured["branch"]
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    assert actual == marker["commit"]
    assert (checkout / "README").is_file()
