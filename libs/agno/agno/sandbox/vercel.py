"""Vercel adapter pinned to one execution session, without automatic resume."""

import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, AsyncIterator, Dict, Optional, Sequence
from uuid import uuid4

from agno.sandbox.allocation import PostgresAllocationJournal
from agno.sandbox.base import ExecResult, SandboxError, SandboxSpec
from agno.sandbox.hosted import HostedComputer, HostedSandboxProvider

# File APIs may operate as the provider's default user. Root imports validate
# exact bytes before moving them into the inaccessible control directory.
_IMPORT = """import hashlib,os,stat,sys
from pathlib import Path
source,target,size,digest=sys.argv[1:]
fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'rb') as stream:
 assert stat.S_ISREG(os.fstat(stream.fileno()).st_mode)
 value=stream.read(int(size)+1)
assert len(value)==int(size) and hashlib.sha256(value).hexdigest()==digest, 'transfer digest mismatch'
with open(target,'xb') as output: output.write(value)
os.chmod(target,0o600)
Path(source).unlink()
"""
_EXPORT = """import os,stat,sys
source,target,limit=sys.argv[1:]
fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'rb') as stream:
 info=os.fstat(stream.fileno())
 assert stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_size<=int(limit)
 value=stream.read(int(limit)+1)
assert len(value)<=int(limit)
fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
with os.fdopen(fd,'wb') as output: output.write(value)
os.chmod(target,0o444)
"""


class VercelSandboxProvider(HostedSandboxProvider):
    """Vercel v2 session-bound execution using prepared VCR images.

    Requires Python 3.10+ and ``agno[vercel-sandbox]``. Configure a token, team and
    project on the service. All process/file operations use an exact runtime
    session handle; sandbox-level automatic resume/replay is never used.
    """

    backend = "vercel"

    def __init__(
        self,
        namespace: str,
        journal: PostgresAllocationJournal,
        *,
        token: Optional[str] = None,
        team_id: Optional[str] = None,
        project_id: Optional[str] = None,
        region: Optional[str] = None,
        max_allocations: int = 10,
        lifetime: int = 1800,
    ) -> None:
        super().__init__(namespace, journal, max_allocations=max_allocations, lifetime=lifetime)
        try:
            import vercel.sandbox as sdk
        except ImportError as error:
            raise ImportError("Install agno[vercel-sandbox] with Python 3.10+ to use Vercel sandboxes") from error
        token = token or os.environ.get("VERCEL_TOKEN")
        team_id = team_id or os.environ.get("VERCEL_TEAM_ID")
        project_id = project_id or os.environ.get("VERCEL_PROJECT_ID")
        if not token or not team_id or not project_id:
            raise ValueError("Vercel requires a service token, team ID and project ID")
        credentials = sdk.SandboxCredentials(token=token, team_id=team_id, project_id=project_id)

        async def credential_factory() -> Any:
            return credentials

        self._sdk, self.project_id = sdk, project_id
        self._options = sdk.SandboxServiceOptions(
            credentials_factory=credential_factory, region=region, file_transfer_timeout=timedelta(seconds=120)
        )

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        # A short-lived client works across both async callers and public sync
        # wrappers, without sharing an HTTP pool across unrelated event loops.
        client = self._sdk.SandboxClient.create(options=self._options)
        try:
            yield client
        finally:
            await client.aclose()

    def _validate_spec(self, spec: SandboxSpec) -> None:
        super()._validate_spec(spec)
        if int(spec.cpus) != spec.cpus:
            raise ValueError("Vercel requires an integral vCPU count")

    def _computer(self, sandbox: Any) -> HostedComputer:
        if sandbox.project_id != self.project_id:
            raise SandboxError("Vercel sandbox belongs to a different project")
        reference = json.dumps([self.project_id, sandbox.name, sandbox.current_session_id], separators=(",", ":"))
        state = str(sandbox.status)
        return HostedComputer(
            reference, sandbox.tags or {}, "exited" if state in ("stopped", "failed", "aborted") else state
        )

    async def _lookup(self, client: Any, provider_ref: str, *, running: bool = False) -> Any:
        project, name, session_id = json.loads(provider_ref)
        if project != self.project_id:
            raise SandboxError("Vercel provider reference belongs to a different project")
        try:
            sandbox = await client.get_sandbox(name=name)
        except self._sdk.SandboxApiError as error:
            if error.status_code != 404:
                raise
            if running:
                raise SandboxError("Vercel computer is missing") from error
            return None
        if sandbox.current_session_id != session_id:
            raise SandboxError("Vercel execution session changed; refusing implicit recovery")
        if running and str(sandbox.status) != "running":
            raise SandboxError("Vercel computer is not running; implicit resume is disabled")
        self._computer(sandbox)
        return sandbox

    async def _session(self, client: Any, provider_ref: str) -> Any:
        sandbox = await self._lookup(client, provider_ref, running=True)
        session = sandbox.current_session
        if session is None:
            # SDK GET can omit the expanded session. Listing history is read-only;
            # session() would resume compute and must never be used here.
            sessions = await sandbox.list_sessions(page_size=100)
            session = next((value for value in sessions if value.id == sandbox.current_session_id), None)
        if session is None or session.id != sandbox.current_session_id or str(session.status) != "running":
            raise SandboxError("Vercel exact runtime session is unavailable")
        return session

    async def _create(self, spec: SandboxSpec, metadata: Dict[str, str]) -> HostedComputer:
        async with self._client() as client:
            sandbox = await client.create_sandbox(
                name=metadata["name"] + "-" + metadata["token"][:12],
                image=spec.image,
                resources=self._sdk.SandboxResources(vcpus=int(spec.cpus), memory=spec.memory_mb),
                execution_time_limit=self.lifetime,
                persistent=False,
                env=dict(spec.env),
                tags=metadata,
                network_policy=self._sdk.NetworkPolicy.deny_all()
                if spec.network == "none"
                else self._sdk.NetworkPolicy.allow_all(),
                destroy=False,
            )
            return self._computer(sandbox)

    async def _check_resources(self, spec: SandboxSpec, computer: HostedComputer) -> None:
        async with self._client() as client:
            sandbox = await self._lookup(client, computer.provider_ref, running=True)
            if sandbox.vcpus != spec.cpus or sandbox.memory != spec.memory_mb:
                raise SandboxError("Vercel CPU/memory differs from the requested specification")
            policy = sandbox.network_policy
            if policy is None or policy.mode != ("deny-all" if spec.network == "none" else "allow-all"):
                raise SandboxError("Vercel network policy differs from the requested specification")

    async def _get(self, provider_ref: str) -> Optional[HostedComputer]:
        async with self._client() as client:
            sandbox = await self._lookup(client, provider_ref)
            return None if sandbox is None else self._computer(sandbox)

    async def _inventory(self, token: str) -> Sequence[HostedComputer]:
        async with self._client() as client:
            query = self._sdk.SandboxQueryByName(name_prefix="agno-", tag=self._sdk.TagFilter(key="token", value=token))
            return [
                self._computer(sandbox)
                async for sandbox in client.query_sandboxes(query=query)
                if (sandbox.tags or {}).get("namespace") == self.namespace
            ]

    async def _delete(self, provider_ref: str) -> None:
        async with self._client() as client:
            sandbox = await self._lookup(client, provider_ref)
            if sandbox is not None:
                await sandbox.destroy(delete_orphan_snapshots=False)

    async def _command(self, provider_ref: str, argv: Sequence[str], *, timeout: float) -> ExecResult:
        async with self._client() as client:
            session = await self._session(client, provider_ref)
            result = await session.run_process(
                argv[0], list(argv[1:]), sudo=True, kill_after=timeout, capture_output=True
            )
            return ExecResult(result.returncode, result.stdout or "", result.stderr or "")

    async def _write(self, provider_ref: str, path: str, payload: bytes) -> None:
        staging = "/tmp/agno-upload-" + uuid4().hex
        async with self._client() as client:
            session = await self._session(client, provider_ref)
            await session.fs.write_bytes(staging, payload, mode=0o600)
            result = await session.run_process(
                "python",
                ["-I", "-c", _IMPORT, staging, path, str(len(payload)), hashlib.sha256(payload).hexdigest()],
                sudo=True,
                kill_after=120,
                capture_output=True,
            )
            if result.returncode:
                raise SandboxError("Vercel protected upload failed: " + (result.stderr or "")[-500:])

    async def _read(self, provider_ref: str, path: str, *, max_bytes: int) -> bytes:
        staging = "/tmp/agno-download-" + uuid4().hex
        async with self._client() as client:
            session = await self._session(client, provider_ref)
            result = await session.run_process(
                "python",
                ["-I", "-c", _EXPORT, path, staging, str(max_bytes)],
                sudo=True,
                kill_after=120,
                capture_output=True,
            )
            if result.returncode:
                raise SandboxError("Vercel protected download failed: " + (result.stderr or "")[-500:])
            chunks, size = [], 0
            async with session.fs.open(staging, "rb") as stream:
                while chunk := await stream.read(min(1024 * 1024, max_bytes - size + 1)):
                    size += len(chunk)
                    if size > max_bytes:
                        raise SandboxError("Vercel transfer exceeds its byte limit")
                    chunks.append(chunk)
            # Staging data is session-local and disappears on mandatory teardown.
            return b"".join(chunks)
