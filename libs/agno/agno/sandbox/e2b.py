"""E2B adapter for prepared templates, with no implicit resume or create retries."""

import shlex
from typing import Any, Dict, Optional, Sequence

from agno.sandbox.allocation import PostgresAllocationJournal
from agno.sandbox.base import ExecResult, SandboxError, SandboxSpec
from agno.sandbox.checkpoint import _thread
from agno.sandbox.hosted import HostedComputer, HostedSandboxProvider


class E2BSandboxProvider(HostedSandboxProvider):
    """Use an E2B template containing the root-owned Agno hosted runtime.

    Requires Python 3.10+ and the optional ``e2b-sandbox`` extra. CPU and memory
    must match the prepared template; disk/PID limits use provider defaults.
    API credentials stay on the service. E2B lifetime expiry kills compute;
    paused computers are never automatically resumed by this adapter.
    """

    backend = "e2b"

    def __init__(
        self,
        namespace: str,
        journal: PostgresAllocationJournal,
        *,
        api_key: Optional[str] = None,
        max_allocations: int = 10,
        lifetime: int = 1800,
        request_timeout: float = 30,
    ) -> None:
        super().__init__(namespace, journal, max_allocations=max_allocations, lifetime=lifetime)
        try:
            import e2b
        except ImportError as error:
            raise ImportError("Install agno[e2b-sandbox] with Python 3.10+ to use E2B sandboxes") from error
        if request_timeout <= 0:
            raise ValueError("E2B request timeout must be positive")
        self._sdk = e2b
        self._options: Dict[str, Any] = dict(request_timeout=request_timeout, retries=0)
        if api_key is not None:
            self._options["api_key"] = api_key

    def _detail(self, provider_ref: str) -> Any:
        # The public connect operation resumes paused sandboxes. This read-only
        # generated endpoint retains the envd token omitted by public get_info,
        # allowing transport construction without any lifecycle mutation.
        from e2b.api import handle_api_exception
        from e2b.api.client.api.sandboxes import get_sandboxes_sandbox_id
        from e2b.api.client.models import SandboxDetail
        from e2b.api.client_sync import get_api_client
        from e2b.connection_config import ConnectionConfig

        response = get_sandboxes_sandbox_id.sync_detailed(
            provider_ref, client=get_api_client(ConnectionConfig(**self._options))
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 300:
            raise handle_api_exception(response)
        if not isinstance(response.parsed, SandboxDetail):
            raise SandboxError("E2B returned an invalid sandbox detail")
        return response.parsed

    @staticmethod
    def _computer(detail: Any) -> HostedComputer:
        metadata = detail.metadata
        if not isinstance(metadata, dict):
            raise SandboxError("E2B sandbox is missing ownership metadata")
        return HostedComputer(detail.sandbox_id, metadata, str(detail.state))

    def _transport(self, provider_ref: str) -> Any:
        from e2b.connection_config import ConnectionConfig
        from packaging.version import Version

        detail = self._detail(provider_ref)
        if detail is None or str(detail.state) != "running":
            raise SandboxError("E2B computer is not running; implicit resume is disabled")
        token = detail.envd_access_token
        if not isinstance(token, str) or not token:
            raise SandboxError("E2B secure transport token is unavailable")
        headers = {
            "E2b-Sandbox-Id": provider_ref,
            "E2b-Sandbox-Port": str(ConnectionConfig.envd_port),
            "X-Access-Token": token,
        }
        return self._sdk.Sandbox(
            sandbox_id=provider_ref,
            sandbox_domain=detail.domain if isinstance(detail.domain, str) else None,
            envd_version=Version(detail.envd_version),
            envd_access_token=token,
            connection_config=ConnectionConfig(extra_sandbox_headers=headers, **self._options),
        )

    async def _create(self, spec: SandboxSpec, metadata: Dict[str, str]) -> HostedComputer:
        def create() -> HostedComputer:
            sandbox = self._sdk.Sandbox.create(
                template=spec.image,
                timeout=self.lifetime,
                metadata=metadata,
                envs=dict(spec.env),
                secure=True,
                allow_internet_access=spec.network == "internet",
                lifecycle={"on_timeout": "kill", "auto_resume": False},
                **self._options,
            )
            # The creation response already supplies the authoritative immutable
            # ID. Binding must survive failure of a subsequent detail lookup.
            return HostedComputer(sandbox.sandbox_id, metadata, "running")

        return await _thread(create)

    async def _check_resources(self, spec: SandboxSpec, computer: HostedComputer) -> None:
        detail = await _thread(self._detail, computer.provider_ref)
        if detail is None or detail.cpu_count != spec.cpus or detail.memory_mb != spec.memory_mb:
            raise SandboxError("E2B template CPU/memory differs from the requested specification")
        if detail.allow_internet_access is not (spec.network == "internet"):
            raise SandboxError("E2B network policy differs from the requested specification")

    async def _get(self, provider_ref: str) -> Optional[HostedComputer]:
        detail = await _thread(self._detail, provider_ref)
        return None if detail is None else self._computer(detail)

    async def _inventory(self, token: str) -> Sequence[HostedComputer]:
        def inventory() -> Sequence[HostedComputer]:
            from e2b.api.client.models import SandboxState
            from e2b.sandbox.sandbox_api import SandboxQuery

            paginator = self._sdk.Sandbox.list(
                query=SandboxQuery(
                    metadata={"namespace": self.namespace, "token": token},
                    state=[SandboxState.RUNNING, SandboxState.PAUSED],
                ),
                **self._options,
            )
            computers = []
            while paginator.has_next:
                for info in paginator.next_items():
                    computers.append(HostedComputer(info.sandbox_id, info.metadata, str(info.state)))
            return computers

        return await _thread(inventory)

    async def _delete(self, provider_ref: str) -> None:
        await _thread(self._sdk.Sandbox.kill, sandbox_id=provider_ref, **self._options)

    async def _command(self, provider_ref: str, argv: Sequence[str], *, timeout: float) -> ExecResult:
        def command() -> ExecResult:
            from e2b.sandbox.commands.command_handle import CommandExitException

            sandbox = self._transport(provider_ref)
            try:
                result = sandbox.commands.run(
                    shlex.join(argv), user="root", timeout=timeout, request_timeout=timeout + 5
                )
            except CommandExitException as error:
                result = error
            return ExecResult(result.exit_code, result.stdout, result.stderr)

        return await _thread(command)

    async def _write(self, provider_ref: str, path: str, payload: bytes) -> None:
        await _thread(lambda: self._transport(provider_ref).files.write(path, payload, user="root"))

    async def _read(self, provider_ref: str, path: str, *, max_bytes: int) -> bytes:
        def read() -> bytes:
            sandbox = self._transport(provider_ref)
            if sandbox.files.get_info(path, user="root").size > max_bytes:
                raise SandboxError("E2B transfer exceeds its byte limit")
            chunks, size = [], 0
            with sandbox.files.read(path, format="stream", user="root", request_timeout=120) as stream:
                for chunk in stream:
                    size += len(chunk)
                    if size > max_bytes:
                        raise SandboxError("E2B transfer exceeds its byte limit")
                    chunks.append(chunk)
            return b"".join(chunks)

        return await _thread(read)
