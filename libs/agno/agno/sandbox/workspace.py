"""Portable Git checkpoints outside a disposable sandbox's writable layer."""

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agno.sandbox.base import _sync


@dataclass(frozen=True)
class GitWorkspace:
    repo: str
    ref: str = "main"
    push: bool = True

    def branch(self, session_id: str) -> str:
        return "agno/session/" + hashlib.sha256(session_id.encode()).hexdigest()[:32]

    async def _git(self, path: Path, *args: str, check: bool = True) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(path),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), 120)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            raise
        if check and proc.returncode:
            # Git diagnostics can expose credential-bearing remote URLs.
            raise RuntimeError(f"Workspace git operation failed (exit {proc.returncode})")
        return proc.returncode or 0, stdout.decode().strip()

    async def aon_create(self, path: Path, session_id: str) -> Optional[str]:
        path.mkdir(parents=True, exist_ok=True)
        branch = self.branch(session_id)
        await self._git(path, "init", "--quiet")
        await self._git(path, "remote", "add", "origin", self.repo)
        code, _ = await self._git(path, "ls-remote", "--exit-code", "--heads", "origin", branch, check=False)
        if code not in (0, 2):
            raise RuntimeError("Could not inspect workspace checkpoint remote")
        source = branch if code == 0 else self.ref
        await self._git(path, "fetch", "--depth=1", "origin", source)
        await self._git(path, "checkout", "-B", branch, "FETCH_HEAD")
        _, commit = await self._git(path, "rev-parse", "HEAD")
        return commit

    async def acheckpoint(self, path: Path, session_id: str) -> Optional[str]:
        await self._git(path, "add", "--all")
        code, _ = await self._git(path, "diff", "--cached", "--quiet", check=False)
        if code == 1:
            await self._git(
                path,
                "-c",
                "user.name=Agno sandbox",
                "-c",
                "user.email=sandbox@localhost",
                "commit",
                "--quiet",
                "-m",
                "Checkpoint coding session",
            )
        elif code != 0:
            raise RuntimeError("Could not inspect workspace changes")
        if not self.push:
            return None  # A local commit does not survive container destruction.
        await self._git(path, "push", "origin", "HEAD:refs/heads/" + self.branch(session_id))
        _, commit = await self._git(path, "rev-parse", "HEAD")
        return commit

    def on_create(self, path: Path, session_id: str) -> Optional[str]:
        return _sync(self.aon_create(path, session_id))

    def checkpoint(self, path: Path, session_id: str) -> Optional[str]:
        return _sync(self.acheckpoint(path, session_id))
