"""Docker execution for customer-operated trusted-team deployments."""

import asyncio
import base64
import hashlib
import ipaddress
import json
import math
import os
import secrets
import tempfile
import threading
import weakref
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Sequence, Tuple

from agno.sandbox.base import ExecResult, Sandbox, SandboxError, SandboxHandle, _identity, _retention, _sync

if TYPE_CHECKING:
    from agno.sandbox.checkpoint import CheckpointStore
    from agno.sandbox.transfer import CheckpointTransfer

_LABEL = "io.agno.sandbox."
# One provider-owned bridge per host with inter-container traffic off: sandboxes reach the
# internet and the host's published ports but not each other. Its subnet is pinned so it never
# draws from Docker's default address pools, which are small and shared with everything else.
_ISOLATED = "isolated"
_ISOLATED_NETWORK = "agno-sandbox"
_DEFAULT_SUBNET = "172.30.0.0/22"
_ICC_OPTION = "com.docker.network.bridge.enable_icc"
# Environment variable carrying the container's runtime bearer token.
_TOKEN_ENV = "AGNO_SANDBOX_RUNTIME_TOKEN"
# How long create waits for a freshly started runtime server to answer /health.
_RUNTIME_READY_SECONDS = 15.0
_RUNNER = (Path(__file__).parent.parent / "_exec.py").read_text()


async def _close_with_loop(owner: "weakref.ReferenceType[DockerSandbox]", client: Any) -> None:
    loop = asyncio.get_running_loop()
    try:
        while True:
            # The loop holds tasks only weakly; this pending timer is what keeps the closer alive,
            # and closing the loop drops it, so nothing outlives the loop.
            await asyncio.sleep(3600)
    except GeneratorExit:
        # Collected after its loop closed; no loop is left to close the client on.
        raise
    except BaseException:
        sandbox = owner()
        if sandbox is not None:
            with sandbox._http_lock:
                if sandbox._http.get(loop, (None,))[0] is client:
                    del sandbox._http[loop]
        await client.aclose()
        raise


def _cancel_closers(
    clients: Dict[asyncio.AbstractEventLoop, Tuple[Any, "asyncio.Task[None]"]], lock: threading.Lock
) -> None:
    with lock:
        entries = list(clients.items())
    for loop, (_, task) in entries:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(task.cancel)


class DockerSandbox(Sandbox):
    """Linux/Python sandbox compute with explicit env and no host filesystem bind mounts.

    The Docker daemon is trusted infrastructure. Its socket is never mounted into
    the sandbox. Files are ephemeral tmpfs: stop/destroy requires an external
    checkpoint for recovery. This class alone is not a durable session service.
    """

    def __init__(
        self,
        image: str,
        *,
        namespace: str = "default",
        cpus: float = 2.0,
        memory_mb: int = 2048,
        pids_limit: int = 256,
        workspace_mb: int = 512,
        network: str = "none",
        docker_binary: str = "docker",
        runtime_port: Optional[int] = None,
        runtime_host: str = "127.0.0.1",
        subnet: str = _DEFAULT_SUBNET,
        checkpoints: Optional["CheckpointStore"] = None,
        env: Optional[Mapping[str, str]] = None,
        execution_timeout: float = 900,
        retain_checkpoints: Optional[int] = 3,
    ) -> None:
        for value in (image, namespace, network):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError("Sandbox image, namespace and network must be nonempty strings")
        if image.startswith("-") or network == "host" or network.startswith("container:"):
            raise ValueError("Option-like images and shared host/container networking are not supported")
        if type(cpus) not in (int, float) or not math.isfinite(cpus) or cpus <= 0:
            raise ValueError("Sandbox CPU limit must be a positive number")
        if any(type(value) is not int or value < 1 for value in (memory_mb, pids_limit, workspace_mb)):
            raise ValueError("Sandbox memory, process and workspace limits must be positive integers")
        if runtime_port is not None and (type(runtime_port) is not int or not 1 <= runtime_port <= 65535):
            raise ValueError("Sandbox runtime port must be between 1 and 65535")
        if runtime_port is not None and network == "none":
            raise ValueError(
                "The runtime server needs a network to publish its port; use 'isolated', 'bridge' or a managed network"
            )
        if (
            not isinstance(runtime_host, str)
            or not runtime_host
            or runtime_host.startswith("-")
            or any(char.isspace() or char in ":/\x00" for char in runtime_host)
        ):
            raise ValueError("Sandbox runtime host must be a bare IP address or host name")
        self.image = image
        self.namespace = namespace
        self.cpus = float(cpus)
        self.memory_mb = memory_mb
        self.pids_limit = pids_limit
        self.workspace_mb = workspace_mb
        self.network = network
        self.docker_binary = docker_binary
        # The image runs the runtime as an HTTP server on this port, published on the host's
        # loopback, so start/poll are pooled requests instead of a docker exec each. None keeps
        # the sleep entrypoint and the exec transport, which any image with python supports.
        self.runtime_port = runtime_port
        # The address the port is published on and advertised as. Loopback reaches only this
        # host's replicas; with a daemon shared across hosts, set the daemon host's address
        # every replica can reach. Every request then needs the container's bearer token.
        self.runtime_host = runtime_host
        # The isolated network's address range. An explicit subnet never draws from Docker's
        # default pools; a /22 stays under the roughly 1000 interfaces one bridge can carry.
        try:
            parsed = ipaddress.ip_network(subnet, strict=True)
        except (ValueError, TypeError) as error:
            raise ValueError("Sandbox subnet must be an IPv4 network in CIDR form, such as 172.30.0.0/22") from error
        if parsed.version != 4 or parsed.prefixlen > 30:
            raise ValueError("Sandbox subnet must be an IPv4 network no smaller than a /30")
        self.subnet = str(parsed)
        if not math.isfinite(execution_timeout) or not 0 < execution_timeout <= 86400:
            raise ValueError("Sandbox execution timeout must be between 0 and 86400 seconds")
        self.checkpoints = checkpoints
        self.env = dict(env) if env is not None else None
        self.execution_timeout = execution_timeout
        self.retain_checkpoints = _retention(retain_checkpoints)
        self._http: Dict[asyncio.AbstractEventLoop, Tuple[Any, "asyncio.Task[None]"]] = {}
        # Sync calls from several threads share the cache, and each loop's closer removes its own entry.
        self._http_lock = threading.Lock()
        # A sandbox discarded while its loop still runs closes its clients on that loop.
        weakref.finalize(self, _cancel_closers, self._http, self._http_lock)
        self._network_ready = False

    def checkpoint_transfer(self, store: "CheckpointStore") -> "CheckpointTransfer":
        from agno.sandbox.docker.transfer import DockerCheckpointTransfer

        return DockerCheckpointTransfer(self, store)

    @property
    def network_name(self) -> str:
        """The Docker network containers join: the host's one Agno-managed bridge for 'isolated'."""
        return _ISOLATED_NETWORK if self.network == _ISOLATED else self.network

    async def _anetwork(self) -> str:
        """Ensure the host's isolated bridge exists with our subnet and label, once per provider.

        One network per host serves every namespace: with inter-container traffic off, sharing it
        adds no reach between sandboxes, and a pinned subnet keeps it out of Docker's default
        address pools. It is never removed with a container; ``aremove_network`` deletes it on
        purpose. Creation races resolve on the fixed name: exists is success, as long as it is ours.
        """
        name = self.network_name
        if self.network != _ISOLATED or self._network_ready:
            return name
        code, out, _ = await self._docker("network", "inspect", name)
        if code:
            code, _, err = await self._docker(
                "network",
                "create",
                "--driver",
                "bridge",
                "--subnet",
                self.subnet,
                "--opt",
                _ICC_OPTION + "=false",
                "--label",
                _LABEL + "network=" + _ISOLATED,
                name,
            )
            if code and b"already exists" not in err:
                if b"overlaps" in err:
                    raise SandboxError(
                        f"Docker subnet {self.subnet} overlaps an existing network on this host; "
                        "set DockerSandbox(subnet=...) to a free range"
                    )
                raise SandboxError("Docker network creation failed: " + err.decode(errors="replace")[:500])
            code, out, err = await self._docker("network", "inspect", name)
            if code:
                raise SandboxError("Docker network is missing after creation: " + err.decode(errors="replace")[:500])
        try:
            record = json.loads(out)[0]
        except (ValueError, IndexError, TypeError) as error:
            raise SandboxError("Docker returned an invalid network record") from error
        labels = record.get("Labels") or {}
        if labels.get(_LABEL + "network") != _ISOLATED or (record.get("Options") or {}).get(_ICC_OPTION) != "false":
            raise SandboxError(f"Docker network {name} exists but is not Agno's isolated bridge; rename or remove it")
        subnets = [entry.get("Subnet") for entry in ((record.get("IPAM") or {}).get("Config") or [])]
        if subnets and self.subnet not in subnets:
            raise SandboxError(
                f"Docker network {name} uses subnet {subnets[0]} but this provider is configured for {self.subnet}; "
                "use the same subnet on every replica, or remove the network while nothing is attached"
            )
        self._network_ready = True
        return name

    async def aremove_network(self) -> bool:
        """Remove the host's isolated bridge when nothing is attached. Returns False when it is
        still in use or absent; raises when the network with that name is not ours."""
        if self.network != _ISOLATED:
            return False
        name = self.network_name
        code, out, _ = await self._docker("network", "inspect", name)
        if code:
            return False
        try:
            labels = json.loads(out)[0].get("Labels") or {}
        except (ValueError, IndexError, TypeError, AttributeError):
            labels = {}
        if labels.get(_LABEL + "network") != _ISOLATED:
            raise SandboxError(f"Docker network {name} is not Agno's isolated bridge; refusing to remove it")
        code, _, err = await self._docker("network", "rm", name)
        self._network_ready = False
        if code:
            if b"active endpoints" in err or b"has active" in err:
                return False
            if b"not found" in err or b"No such network" in err:
                return False
            raise SandboxError("Docker network removal failed: " + err.decode(errors="replace")[:500])
        return True

    def remove_network(self) -> bool:
        return _sync(self.aremove_network())

    def _name(self, session_id: str, agent_id: Optional[str], generation: int) -> str:
        identity = json.dumps([self.namespace, agent_id, session_id, generation])
        return "agno-" + hashlib.sha256(identity.encode()).hexdigest()[:40]

    def _digest(self, session_id: str, agent_id: Optional[str], generation: int, env: Mapping[str, str]) -> str:
        data = {
            "image": self.image,
            "cpus": self.cpus,
            "memory_mb": self.memory_mb,
            "pids_limit": self.pids_limit,
            "workspace_mb": self.workspace_mb,
            "network": self.network,
            "runtime_port": self.runtime_port,
            "runtime_host": self.runtime_host if self.runtime_port is not None else None,
            "agent_id": agent_id,
            "session_id": session_id,
            "generation": generation,
            "env": dict(env),
            "storage": "managed-tmpfs-v1",
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _write_env_file(env: Mapping[str, str]) -> str:
        for key, value in env.items():
            if key[0] == "#" or any(char.isspace() for char in key) or "\n" in value or "\r" in value:
                raise ValueError(
                    "Docker sandbox env names cannot contain whitespace or start with '#'; values cannot contain newlines"
                )
        descriptor, path = tempfile.mkstemp(prefix="agno-sandbox-env-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.writelines(key + "=" + value + "\n" for key, value in env.items())
        return path

    async def _docker(
        self, *args: str, input_data: Optional[bytes] = None, timeout: float = 30
    ) -> tuple[int, bytes, bytes]:
        process = await asyncio.create_subprocess_exec(
            self.docker_binary,
            *args,
            stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read(stream: Any) -> bytes:
            chunks = []
            size = 0
            while chunk := await stream.read(65536):
                size += len(chunk)
                if size > 32 * 1024 * 1024:
                    raise SandboxError("Docker response exceeded the transport output limit")
                chunks.append(chunk)
            return b"".join(chunks)

        async def send() -> None:
            if process.stdin is not None:
                try:
                    process.stdin.write(input_data or b"")
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()

        tasks = [
            asyncio.create_task(read(process.stdout)),
            asyncio.create_task(read(process.stderr)),
            asyncio.create_task(send()),
        ]
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout)
            await asyncio.wait_for(process.wait(), 5)
            assert isinstance(results[0], bytes) and isinstance(results[1], bytes)
            return process.returncode or 0, results[0], results[1]
        except BaseException:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            await process.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]:
        if not provider_ref or provider_ref.startswith("-") or "\x00" in provider_ref:
            raise ValueError("Invalid Docker sandbox reference")
        code, out, err = await self._docker("container", "inspect", provider_ref)
        if code:
            if b"No such container" in err or b"No such object" in err:
                return None
            raise SandboxError("Docker inspection failed: " + err.decode(errors="replace")[:500])
        record = json.loads(out)[0]
        labels = record.get("Config", {}).get("Labels") or {}
        if labels.get(_LABEL + "namespace") != self.namespace:
            raise SandboxError("Container does not belong to this sandbox namespace")
        try:
            return SandboxHandle(
                provider_ref=record["Id"],
                name=record["Name"].lstrip("/"),
                agent_id=labels[_LABEL + "agent"] or None,
                session_id=labels[_LABEL + "session"],
                generation=int(labels[_LABEL + "generation"]),
                state=record["State"]["Status"],
                config_digest=labels[_LABEL + "config"],
                runtime_url=self._runtime_url(record, labels.get(_LABEL + "runtime")),
                runtime_token=self._runtime_token(record),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxError("Container has incomplete sandbox identity labels") from error

    def _runtime_url(self, record: Dict[str, Any], port: Optional[str]) -> Optional[str]:
        """The address of the container's runtime server, from its published port."""
        if not port:
            return None
        bindings = ((record.get("NetworkSettings") or {}).get("Ports") or {}).get(port + "/tcp") or []
        for binding in bindings:
            host_port = (binding or {}).get("HostPort")
            if host_port:
                return f"http://{self.runtime_host}:{host_port}"
        return None

    @staticmethod
    def _runtime_token(record: Dict[str, Any]) -> Optional[str]:
        """The container's runtime credential, read back from its environment. Reading a
        container's environment needs daemon access, which is trusted infrastructure here."""
        for item in (record.get("Config") or {}).get("Env") or []:
            if isinstance(item, str) and item.startswith(_TOKEN_ENV + "="):
                return item[len(_TOKEN_ENV) + 1 :] or None
        return None

    @staticmethod
    def _headers(handle: SandboxHandle) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if handle.runtime_token:
            headers["Authorization"] = "Bearer " + handle.runtime_token
        return headers

    def _http_client(self) -> Any:
        """One pooled client per event loop, closed when that loop shuts down."""
        import httpx

        loop = asyncio.get_running_loop()
        with self._http_lock:
            for stale in [item for item in self._http if item.is_closed()]:
                del self._http[stale]
            entry = self._http.get(loop)
            if entry is None:
                limits = httpx.Limits(max_connections=4096, max_keepalive_connections=1024)
                client = httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(15.0, read=60.0))
                # asyncio.run cancels pending tasks before closing its loop, so each sync call closes its client.
                closer = loop.create_task(_close_with_loop(weakref.ref(self), client))
                entry = self._http[loop] = (client, closer)
        return entry[0]

    async def _await_runtime(self, handle: SandboxHandle) -> None:
        """Wait for the in-container server to answer /health before handing the sandbox out."""
        assert handle.runtime_url is not None
        import httpx

        client = self._http_client()
        deadline = asyncio.get_running_loop().time() + _RUNTIME_READY_SECONDS
        while True:
            try:
                response = await client.get(handle.runtime_url + "/health", headers=self._headers(handle), timeout=2.0)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if asyncio.get_running_loop().time() >= deadline:
                raise SandboxError("Sandbox runtime server did not become ready")
            await asyncio.sleep(0.1)

    async def _owned(self, handle: SandboxHandle) -> Optional[SandboxHandle]:
        current = await self.aget(handle.provider_ref)
        if current is not None and (
            current.provider_ref != handle.provider_ref
            or current.name != handle.name
            or current.agent_id != handle.agent_id
            or current.session_id != handle.session_id
            or current.generation != handle.generation
            or current.config_digest != handle.config_digest
        ):
            raise SandboxError("Sandbox identity changed; refusing the operation")
        return current

    async def afind(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
        for_create: bool = False,
    ) -> Optional[SandboxHandle]:
        values = _identity(session_id, agent_id, generation, env)
        handle = await self.aget(self._name(session_id, agent_id, generation))
        if handle is not None and handle.config_digest != self._digest(session_id, agent_id, generation, values):
            raise SandboxError("Existing generation has different compute configuration")
        return handle

    async def acreate(
        self,
        session_id: str,
        *,
        agent_id: Optional[str] = None,
        generation: int = 1,
        env: Optional[Mapping[str, str]] = None,
    ) -> SandboxHandle:
        values = _identity(session_id, agent_id, generation, env)
        name = self._name(session_id, agent_id, generation)
        digest = self._digest(session_id, agent_id, generation, values)
        current = await self.aget(name)
        if current is None:
            network = await self._anetwork()
            labels = {
                "namespace": self.namespace,
                "agent": agent_id or "",
                "session": session_id,
                "generation": str(generation),
                "config": digest,
            }
            if self.runtime_port is not None:
                labels["runtime"] = str(self.runtime_port)
            args = [
                "container",
                "create",
                "--init",
                "--name",
                name,
                "--user",
                "1000:1000",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--network",
                network,
                "--memory",
                f"{self.memory_mb}m",
                "--memory-swap",
                f"{self.memory_mb}m",
                "--cpus",
                str(self.cpus),
                "--pids-limit",
                str(self.pids_limit),
                "--mount",
                f"type=volume,source={name}-workspace,target=/workspace,volume-nocopy",
                "--mount",
                f"type=volume,source={name}-runtime,target=/runtime,volume-nocopy",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,uid=1000,gid=1000,mode=1777,size=128m",
                "--workdir",
                "/workspace",
            ]
            for key, value in labels.items():
                args.extend(["--label", _LABEL + key + "=" + value])
            # Env values go through a private file so they never appear in the host process list.
            runtime_env: Dict[str, str] = {}
            if self.runtime_port is not None:
                if _TOKEN_ENV in values:
                    raise ValueError("The runtime token is generated per container; do not set it in env")
                runtime_env[_TOKEN_ENV] = secrets.token_urlsafe(32)
            env_file = self._write_env_file({"HOME": "/runtime", **runtime_env, **values})
            args.extend(["--env-file", env_file])
            if self.runtime_port is not None:
                # Published on runtime_host only; loopback by default, so only this host reaches it.
                args.extend(["--publish", f"{self.runtime_host}::{self.runtime_port}"])
                args.extend(["--entrypoint", "python", self.image, "-I", "-m", "agno.sandbox.runtime", "supervise"])
                args.extend(["--port", str(self.runtime_port)])
            else:
                args.extend(["--entrypoint", "python", self.image, "-I", "-c", "import time; time.sleep(2147483647)"])
            try:
                await self._ensure_volume(
                    name + "-workspace",
                    self._volume_labels(session_id, agent_id, generation, digest, "workspace"),
                    self.workspace_mb,
                )
                await self._ensure_volume(
                    name + "-runtime", self._volume_labels(session_id, agent_id, generation, digest, "runtime"), 256
                )
                try:
                    code, _, err = await self._docker(*args, timeout=120)
                    if code and self.network == _ISOLATED and b"network" in err and b"not found" in err:
                        # The bridge was removed outside this provider; recreate it and try once more.
                        self._network_ready = False
                        await self._anetwork()
                        code, _, err = await self._docker(*args, timeout=120)
                except asyncio.TimeoutError:
                    code, err = 1, b"Creation response timed out"
                # A concurrent creator or lost response is resolved by the deterministic name.
                current = await self.aget(name)
                if current is None:
                    raise SandboxError("Docker creation failed: " + err.decode(errors="replace")[:500])
            except Exception:
                # Unmounted volumes would block a corrected configuration for this generation; Docker keeps in-use ones.
                with suppress(Exception):
                    await self._delete_volumes(name, session_id, agent_id, generation, digest)
                raise
            finally:
                # The env file holds credentials, so remove it however volume setup or creation ends.
                with suppress(FileNotFoundError):
                    os.unlink(env_file)
        if current.config_digest != digest:
            raise SandboxError("Sandbox generation already exists with different configuration")
        if current.state == "paused":
            # Only the owner knows whether this is a warm pause or a restore that died halfway,
            # so create never revives it: the owner calls resume, anyone else destroys.
            raise SandboxError("Sandbox generation is paused; resume it or destroy it")
        if current.state == "created":
            code, _, err = await self._docker("container", "start", current.provider_ref)
            current = await self.aget(current.provider_ref)
            if code and (current is None or current.state != "running"):
                # A container that never ran holds no files; remove it so the caller is not left an orphan.
                if current is not None and current.state == "created":
                    await self._docker("container", "rm", current.provider_ref)
                    with suppress(Exception):
                        await self._delete_volumes(name, session_id, agent_id, generation, digest)
                raise SandboxError("Docker start failed: " + err.decode(errors="replace")[:500])
        if current is None or current.state != "running":
            raise SandboxError("Sandbox generation is not running; recovery requires a new generation")
        if self.runtime_port is not None:
            if current.runtime_url is None:
                raise SandboxError("Sandbox generation does not publish its runtime port")
            await self._await_runtime(current)
        return current

    async def arpc(self, handle: SandboxHandle, operation: str, payload: bytes) -> ExecResult:
        """Runtime start/poll over the container's HTTP server when it has one, else over exec.

        A failed or lost reply never touches compute: the coordinator reconciles.
        """
        if operation not in ("start", "poll") or not isinstance(payload, bytes) or len(payload) > 1024 * 1024:
            raise ValueError("Runtime RPC requires start/poll and a payload no larger than 1 MiB")
        if handle.runtime_url is None:
            # Exec fallback: fixed runtime argv, bounded, and never stopping compute on a failed or
            # lost reply. A control request is not a command that could run forever.
            try:
                wait = float(json.loads(payload).get("wait", 0) or 0)
            except (ValueError, AttributeError):
                wait = 0.0
            return await self._aexec(
                handle,
                ["python", "-I", "-m", "agno.sandbox.runtime", operation],
                timeout=15 + min(max(wait, 0.0), 30.0),
                max_output_bytes=4 * 1024 * 1024,
                stdin=payload,
                stop_on_failure=False,
            )
        import httpx

        # No daemon call on this path: the published port belongs to this container alone, so a
        # destroyed or replaced generation refuses the connection, and the caller that paused a
        # generation does not poll it. That keeps dockerd out of the per-request hot path.
        try:
            response = await self._http_client().post(
                handle.runtime_url + "/" + operation, content=payload, headers=self._headers(handle)
            )
        except httpx.HTTPError as error:
            # httpx connection errors often carry no text; name the error class so the message says something.
            raise SandboxError(f"Sandbox runtime request failed: {str(error) or type(error).__name__}") from error
        body = response.text[: 4 * 1024 * 1024]
        if response.status_code != 200:
            return ExecResult(exit_code=1, stdout="", stderr=body)
        return ExecResult(exit_code=0, stdout=body, stderr="")

    async def aexec(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        max_output_bytes: int = 1_048_576,
        stdin: bytes = b"",
    ) -> ExecResult:
        return await self._aexec(handle, argv, timeout=timeout, max_output_bytes=max_output_bytes, stdin=stdin)

    async def _aexec(
        self,
        handle: SandboxHandle,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        max_output_bytes: int = 1_048_576,
        stdin: bytes = b"",
        stop_on_failure: bool = True,
    ) -> ExecResult:
        """Run a command. With ``stop_on_failure`` an uncertain transport outcome stops the
        container, since killing the Docker client does not kill the remote command; runtime
        control requests pass False because they exit on their own and leaving compute alone is
        the safe outcome for them."""
        if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ValueError("Commands must be a nonempty sequence of strings")
        if not math.isfinite(timeout) or timeout <= 0 or not 1 <= max_output_bytes <= 4 * 1024 * 1024:
            raise ValueError("Timeout must be positive and output limit must be between 1 byte and 4 MiB")
        if not isinstance(stdin, bytes) or len(stdin) > 8 * 1024 * 1024:
            raise ValueError("Command stdin must be bytes no larger than 8 MiB")
        current = await self._owned(handle)
        if current is not None and current.state == "paused":
            raise SandboxError("Sandbox is paused; resume it before running commands")
        if current is None or current.state != "running":
            raise SandboxError("Sandbox is not running")
        request = json.dumps(
            {
                "argv": list(argv),
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
                "stdin": base64.b64encode(stdin).decode("ascii"),
            }
        ).encode()
        # docker exec inherits the container's environment, token included; blank it for every
        # command run from the host. Docker cannot unset a variable, so it becomes empty.
        scrub = ["--env", _TOKEN_ENV + "="] if self.runtime_port is not None else []
        try:
            code, out, err = await self._docker(
                "container",
                "exec",
                "-i",
                *scrub,
                handle.provider_ref,
                "python",
                "-I",
                "-c",
                _RUNNER,
                input_data=request,
                timeout=timeout + 15,
            )
        except (asyncio.CancelledError, asyncio.TimeoutError, SandboxError):
            # Killing the Docker client does not kill its remote command. Stop compute
            # to bound cancellation; checkpoint recovery belongs to the coordinator.
            if stop_on_failure:
                await asyncio.shield(self.astop(handle))
            raise
        if code:
            if stop_on_failure:
                await self.astop(handle)
            raise SandboxError("Sandbox command transport failed: " + err.decode(errors="replace")[:500])
        try:
            result = ExecResult(**json.loads(out))
            if stop_on_failure and (result.timed_out or result.output_limited):
                await self.astop(handle)
            return result
        except (TypeError, ValueError) as error:
            if stop_on_failure:
                await self.astop(handle)
            raise SandboxError("Sandbox returned an invalid command result") from error

    async def apause(self, handle: SandboxHandle) -> None:
        current = await self._owned(handle)
        if current is not None and current.state == "paused":
            return
        if current is None or current.state != "running":
            raise SandboxError("Only a running sandbox can be paused")
        # The cgroup freezer keeps memory, processes and tmpfs exactly as they are.
        code, _, err = await self._docker("container", "pause", handle.provider_ref, timeout=15)
        if code:
            raise SandboxError("Docker pause failed: " + err.decode(errors="replace")[:500])

    async def aresume(self, handle: SandboxHandle) -> SandboxHandle:
        current = await self._owned(handle)
        if current is not None and current.state == "running":
            return current
        if current is None or current.state != "paused":
            raise SandboxError("Sandbox is not paused; recovery requires a new generation")
        code, _, err = await self._docker("container", "unpause", handle.provider_ref, timeout=15)
        current = await self._owned(handle)
        if code or current is None or current.state != "running":
            raise SandboxError("Docker unpause failed: " + err.decode(errors="replace")[:500])
        return current

    async def astop(self, handle: SandboxHandle) -> None:
        current = await self._owned(handle)
        if current is None or current.state in ("exited", "dead", "created"):
            return
        if current.state == "paused":
            code, _, err = await self._docker("container", "unpause", handle.provider_ref)
            if code:
                raise SandboxError("Docker could not unpause before stop: " + err.decode(errors="replace")[:500])
        code, _, err = await self._docker("container", "stop", "--time", "2", handle.provider_ref, timeout=15)
        if code:
            raise SandboxError("Docker stop failed: " + err.decode(errors="replace")[:500])

    async def _volume(self, name: str) -> Optional[Any]:
        code, out, err = await self._docker("volume", "inspect", name)
        if code:
            if b"no such volume" in err.lower():
                return None
            raise SandboxError("Docker volume inspection failed: " + err.decode(errors="replace")[:500])
        return json.loads(out)[0]

    def _volume_labels(
        self, session_id: str, agent_id: Optional[str], generation: int, config: str, role: str
    ) -> Dict[str, str]:
        labels = {
            "namespace": self.namespace,
            "agent": agent_id or "",
            "session": session_id,
            "generation": str(generation),
            "config": config,
            "role": role,
        }
        return {_LABEL + key: value for key, value in labels.items()}

    async def _ensure_volume(self, name: str, expected: Dict[str, str], size_mb: int) -> None:
        options = {
            "type": "tmpfs",
            "device": "tmpfs",
            "o": f"rw,nosuid,nodev,size={size_mb}m,uid=1000,gid=1000,mode=0700",
        }
        current = await self._volume(name)
        if current is None:
            args = ["volume", "create", "--driver", "local"]
            for key, value in options.items():
                args.extend(["--opt", key + "=" + value])
            for key, value in expected.items():
                args.extend(["--label", key + "=" + value])
            args.append(name)
            try:
                await self._docker(*args)
            except asyncio.TimeoutError:
                pass  # Resolve a lost create response through the deterministic name.
            current = await self._volume(name)
        if (
            current is None
            or current.get("Driver") != "local"
            or current.get("Options") != options
            or any((current.get("Labels") or {}).get(key) != value for key, value in expected.items())
        ):
            raise SandboxError("Docker volume identity or storage configuration mismatch")

    async def _delete_volumes(
        self, prefix: str, session_id: str, agent_id: Optional[str], generation: int, config: str
    ) -> None:
        for role in ("workspace", "runtime"):
            name = prefix + "-" + role
            current = await self._volume(name)
            if current is None:
                continue
            labels = current.get("Labels") or {}
            expected = self._volume_labels(session_id, agent_id, generation, config, role)
            if any(labels.get(key) != value for key, value in expected.items()):
                raise SandboxError("Refusing to remove a volume with a different sandbox identity")
            code, _, err = await self._docker("volume", "rm", name)
            if code and await self._volume(name) is not None:
                raise SandboxError("Docker volume removal failed: " + err.decode(errors="replace")[:500])

    async def adestroy(self, handle: SandboxHandle) -> None:
        if await self._owned(handle) is not None:
            code, _, err = await self._docker("container", "rm", "--force", handle.provider_ref)
            if code and b"already in progress" in err:
                for _ in range(50):
                    if await self._owned(handle) is None:
                        break
                    await asyncio.sleep(0.1)
            if code and await self._owned(handle) is not None:
                raise SandboxError("Docker removal failed: " + err.decode(errors="replace")[:500])
        # Also reconcile a lost removal response after the container is already gone.
        await self._delete_volumes(
            handle.name, handle.session_id, handle.agent_id, handle.generation, handle.config_digest
        )
