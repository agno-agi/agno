"""Authorized reads from completed sandbox checkpoints, without starting compute."""

from __future__ import annotations

import tarfile
from dataclasses import dataclass
from typing import Any, Dict, Optional

from agno.sandbox.base import SandboxError
from agno.sandbox.checkpoint import (
    CheckpointArchive,
    CheckpointRef,
    CheckpointStore,
    _archive_bytes,
    _name,
    _thread,
)
from agno.sandbox.postgres import _SandboxStore


class SandboxSessionNotFound(SandboxError):
    """The session does not exist in the requested ownership scope."""


class SandboxArtifactNotFound(SandboxError):
    """No completed checkpoint or regular workspace artifact exists at this path."""


@dataclass(frozen=True)
class SandboxArtifact:
    path: str
    content: bytes
    checkpoint: str
    run_id: str


class SandboxArtifacts:
    """Inspect session status and retrieve only regular workspace files.

    user_id is an exact ownership scope, including None. HTTP callers must resolve
    their authorization before passing an owner's identity. Native state is never
    exposed by this surface. Reads refer to the last completed turn, even while a
    newer turn is running; provisional files are not durable artifacts.
    """

    def __init__(
        self, store: _SandboxStore, objects: CheckpointStore, *, max_file_bytes: int = 8 * 1024 * 1024
    ) -> None:
        if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= 64 * 1024 * 1024:
            raise ValueError("Artifact byte limit must be between 1 byte and 64 MiB")
        self.store, self.objects, self.max_file_bytes = store, objects, max_file_bytes

    async def _record(self, agent_id: str, session_id: str, user_id: Optional[str]) -> Dict[str, Any]:
        from sqlalchemy import select

        def read(connection: Any) -> Dict[str, Any]:
            # The binding row is the only authoritative record: it is keyed per session, carries
            # the incarnation the checkpoint was stamped with, and is removed with the session it
            # belongs to. A session_data copy of the same checkpoint can be overwritten by a stale
            # session write, so it is never read here. Both rows must carry this agent and user.
            query = (
                select(self.store.bindings.c.record, self.store.bindings.c.run_id)
                .join(self.store.sessions, self.store.sessions.c.session_id == self.store.bindings.c.session_id)
                .where(
                    self.store._key(session_id),
                    self.store.bindings.c.agent_id == agent_id,
                    self.store.bindings.c.user_id == user_id,
                    self.store.sessions.c.agent_id == agent_id,
                    self.store.sessions.c.user_id == user_id,
                )
            )
            row = connection.execute(query).mappings().first()
            if row is None:
                raise SandboxSessionNotFound("Sandbox session not found")
            record = self.store._json(row["record"])
            record["active_run_id"] = row["run_id"]
            return record

        return await self.store._transaction(read)

    async def astatus(self, *, agent_id: str, session_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        record = await self._record(agent_id, session_id, user_id)
        return {
            "session_id": session_id,
            "phase": record["phase"],
            "generation": str(record["generation"]),
            "active_run_id": record["active_run_id"],
            "last_completed_run_id": record.get("last_run_id"),
            "has_checkpoint": record.get("checkpoint") is not None,
            "compute_allocated": record.get("computer") is not None,
        }

    def status(self, *, agent_id: str, session_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        return self.store._sync(self.astatus, agent_id=agent_id, session_id=session_id, user_id=user_id)

    def _inspect(self, record: Dict[str, Any], path: Optional[str], offset: int, limit: int) -> Any:
        if not record.get("checkpoint"):
            raise SandboxArtifactNotFound("No completed sandbox checkpoint")
        reference = CheckpointRef(**record["checkpoint"])
        # One access for every read of the object: the identity check and the file
        # content both come from it, so the path has to stay valid for both.
        with self.objects.open_archive(reference) as source:
            archive = CheckpointArchive()
            state = archive.validate(source)
            if (
                state.get("binding") != record.get("checkpoint_identity")
                or state.get("binding", {}).get("incarnation") != record["incarnation"]
            ):
                raise SandboxError("Artifact checkpoint does not match this session")
            with _archive_bytes(source, archive.limits) as stream, tarfile.open(fileobj=stream, mode="r:") as contents:
                if path is None:
                    files = sorted(
                        (member.name[len("workspace/") :], member.size)
                        for member in contents
                        if member.isfile() and member.name.startswith("workspace/")
                    )
                    return {
                        "checkpoint": reference.sha256,
                        "run_id": record["last_run_id"],
                        "total": len(files),
                        "files": [{"path": name, "size": size} for name, size in files[offset : offset + limit]],
                    }
                name = "workspace/" + path
                _name(name)
                try:
                    member = contents.getmember(name)
                except KeyError as error:
                    raise SandboxArtifactNotFound("Workspace artifact not found") from error
                if not member.isfile():
                    raise SandboxArtifactNotFound("Artifact must be a regular workspace file")
                if member.size > self.max_file_bytes:
                    raise SandboxError("Artifact exceeds the download byte limit")
                source_file = contents.extractfile(member)
                assert source_file is not None
                content = source_file.read(self.max_file_bytes + 1)
                if len(content) != member.size:
                    raise SandboxError("Artifact size changed while reading")
                return SandboxArtifact(path, content, reference.sha256, record["last_run_id"])

    async def alist(
        self, *, agent_id: str, session_id: str, user_id: Optional[str] = None, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Use a nonnegative offset and a 1-1000 entry limit")
        return await _thread(self._inspect, await self._record(agent_id, session_id, user_id), None, offset, limit)

    def list(
        self, *, agent_id: str, session_id: str, user_id: Optional[str] = None, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        return self.store._sync(
            self.alist, agent_id=agent_id, session_id=session_id, user_id=user_id, offset=offset, limit=limit
        )

    async def aread(
        self, path: str, *, agent_id: str, session_id: str, user_id: Optional[str] = None
    ) -> SandboxArtifact:
        _name("workspace/" + path)
        return await _thread(self._inspect, await self._record(agent_id, session_id, user_id), path, 0, 1)

    def read(self, path: str, *, agent_id: str, session_id: str, user_id: Optional[str] = None) -> SandboxArtifact:
        return self.store._sync(self.aread, path, agent_id=agent_id, session_id=session_id, user_id=user_id)
