"""Docker provider. No Docker socket or host workspace is mounted in a sandbox."""

import asyncio
import json
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional

from agno.sandbox.base import ExecResult, SandboxHandle, SandboxProvider, SandboxSpec


@dataclass
class DockerSandboxProvider(SandboxProvider):
    network: str = "agno-sandbox"
    # False when AgentOS itself runs on the Docker network. True for host development.
    publish_localhost: bool = False
    name: str = "docker"

    async def _command(self, args: List[str], timeout: float = 60) -> subprocess.CompletedProcess:
        return await asyncio.to_thread(
            subprocess.run, ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
        )

    async def acreate(self, spec: SandboxSpec) -> SandboxHandle:
        existing = await self.aget(spec.name)
        if existing is not None:
            return existing
        if spec.cpus <= 0 or spec.pids_limit <= 0:
            raise ValueError("Sandbox CPU and PID limits must be positive")
        with tempfile.NamedTemporaryFile(mode="w", prefix="agno-runtime-", suffix=".env") as env_file:
            for key, value in spec.env.items():
                if not key or "=" in key or any(c in key + value for c in "\r\n\x00"):
                    raise ValueError("Runtime environment requires single-line keys and values")
                env_file.write(f"{key}={value}\n")
            env_file.flush()
            args = [
                "run",
                "--detach",
                "--name",
                spec.name,
                "--label",
                "agno.sandbox=true",
                "--network",
                self.network,
                "--memory",
                spec.memory,
                "--cpus",
                str(spec.cpus),
                "--pids-limit",
                str(spec.pids_limit),
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--env-file",
                env_file.name,
            ]
            if self.publish_localhost:
                args.extend(["--publish", "127.0.0.1::7777"])
            result = await self._command([*args, spec.image, *spec.command], timeout=120)
        # Creation is idempotent by deterministic name, including an ambiguous response.
        handle = await self.aget(spec.name)
        if handle is None:
            # Docker stderr may contain environment or registry credentials.
            raise RuntimeError(f"Docker sandbox creation failed (exit {result.returncode})")
        return handle

    async def aget(self, provider_ref: str) -> Optional[SandboxHandle]:
        if not provider_ref.startswith("agno-sandbox-"):
            raise ValueError("Invalid Agno sandbox reference")
        result = await self._command(["container", "inspect", provider_ref])
        if result.returncode:
            # Only absence is a gone container. A daemon/network failure must not trigger recreation.
            if "No such container" in result.stderr or "No such object" in result.stderr:
                return None
            raise RuntimeError("Could not inspect Docker sandbox")
        data = json.loads(result.stdout)[0]
        if data.get("Config", {}).get("Labels", {}).get("agno.sandbox") != "true":
            raise ValueError("Container is not managed by Agno sandboxes")
        state = data["State"]
        if self.publish_localhost:
            ports = data.get("NetworkSettings", {}).get("Ports", {}).get("7777/tcp") or []
            url = f"http://127.0.0.1:{ports[0]['HostPort']}" if ports else ""
        else:
            url = f"http://{provider_ref}:7777"
        running = state.get("Running", False)
        reason = (
            None
            if running
            else f"Docker container stopped (exit {state.get('ExitCode')}, OOM={state.get('OOMKilled')})"
        )
        return SandboxHandle(provider_ref, url, "running" if running else "stopped", reason)

    async def adestroy(self, handle: SandboxHandle) -> None:
        if await self.aget(handle.provider_ref) is None:
            return
        result = await self._command(["rm", "--force", handle.provider_ref])
        if result.returncode and await self.aget(handle.provider_ref) is not None:
            raise RuntimeError("Could not destroy Docker sandbox")

    async def aexec(self, handle: SandboxHandle, cmd: List[str], timeout: float = 60) -> ExecResult:
        if await self.aget(handle.provider_ref) is None:
            raise RuntimeError("Sandbox no longer exists")
        result = await self._command(["exec", handle.provider_ref, *cmd], timeout)
        return ExecResult(result.returncode, result.stdout, result.stderr)
