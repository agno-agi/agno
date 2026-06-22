import json
from os import getenv
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union

import httpx

from agno.agent import Agent
from agno.team import Team
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
INLINE_SOURCE_MAX_BYTES = 75 * 1024  # API limit for inline source content per file

DEFAULT_INSTRUCTIONS = dedent(
    """\
    You have access to Google's Gemini Agents API (Antigravity) for delegating
    complex sub-tasks to an autonomous, sandboxed agent.

    Use `run_antigravity_task` when the user asks for something that benefits from
    a fresh sandboxed Linux environment with web search, file I/O, and code execution
    available — e.g. multi-step research, analysing a repo, generating files, or
    running code you cannot run locally.

    The sandbox persists across calls within the same Agno session, so subsequent
    `run_antigravity_task` calls can build on prior files and state.

    Use `create_custom_antigravity_agent` / `list_antigravity_agents` /
    `delete_antigravity_agent` only for admin tasks the user has explicitly requested.
    """
)


class AntigravityTools(Toolkit):
    """Toolkit that lets an Agno agent delegate sub-tasks to Google's Gemini Agents API.

    An Antigravity sandbox is provisioned lazily on the first `run_antigravity_task` call
    and its environment_id is cached in the agent's session_state so subsequent calls
    in the same session reuse the same environment (and prior files).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        agent: str = "antigravity-preview-05-2026",
        default_sources: Optional[List[Dict[str, Any]]] = None,
        persistent: bool = True,
        timeout: int = 600,
        instructions: Optional[str] = None,
        add_instructions: bool = False,
        agent_directory: Optional[str] = None,
        register: bool = True,
        **kwargs,
    ):
        """
        Args:
            agent_directory: Optional path to an agent directory (per the Managed
                Agents docs: agent.yaml + AGENTS.md + workspace/ + skills/). When
                set, the toolkit parses the folder, sets `agent` to the yaml's
                `id`, and seeds `default_sources` from workspace/ + skills/.
            register: When `agent_directory` is set and `register=True` (default),
                POST the agent definition to /v1beta/agents on construction.
                Treats 409/already-exists as success. Set False to defer.
        """
        self.api_key = api_key or getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set. Pass api_key= or set the GEMINI_API_KEY environment variable.")
        self.base_url = base_url
        self.agent = agent
        self.default_sources = default_sources
        self.persistent = persistent
        self.timeout = timeout
        self.instructions = instructions or DEFAULT_INSTRUCTIONS

        if agent_directory:
            # Validate conflicting args before touching the filesystem.
            if agent != "antigravity-preview-05-2026":
                raise ValueError("agent_directory conflicts with explicit `agent=` argument")
            if default_sources:
                raise ValueError("agent_directory conflicts with explicit `default_sources=` argument")
            self._load_agent_directory(agent_directory, register=register)

        tools: List[Any] = [
            self.run_antigravity_task,
            self.run_custom_antigravity_agent,
            self.create_custom_antigravity_agent,
            self.update_custom_antigravity_agent,
            self.get_custom_antigravity_agent,
            self.list_antigravity_agents,
            self.list_antigravity_agent_versions,
            self.delete_antigravity_agent,
            self.download_antigravity_environment_snapshot,
        ]
        super().__init__(
            name="antigravity_tools",
            tools=tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    # ---------------------------------------------------------------------------
    # Internal HTTP helpers
    # ---------------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "x-goog-api-key": self.api_key or ""}

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}{path}", json=body, headers=self._headers())
            if response.status_code >= 400:
                raise RuntimeError(f"Antigravity {path} returned {response.status_code}: {response.text}")
            return response.json()

    def _get(self, path: str) -> Dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(f"{self.base_url}{path}", headers=self._headers())
            if response.status_code >= 400:
                raise RuntimeError(f"Antigravity {path} returned {response.status_code}: {response.text}")
            return response.json()

    def _delete(self, path: str) -> None:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.delete(f"{self.base_url}{path}", headers=self._headers())
            if response.status_code >= 400:
                raise RuntimeError(f"Antigravity {path} returned {response.status_code}: {response.text}")

    def _patch(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.patch(f"{self.base_url}{path}", json=body, headers=self._headers())
            if response.status_code >= 400:
                raise RuntimeError(f"Antigravity {path} returned {response.status_code}: {response.text}")
            return response.json()

    def _load_agent_directory(self, directory: str, *, register: bool) -> None:
        """Parse an Antigravity agent directory and apply it to this toolkit.

        Expected layout (per the Managed Agents docs):

            my-agent/
            ├── agent.yaml       # id, base_agent, description, system_instruction
            ├── AGENTS.md        # Overrides agent.yaml.system_instruction if present
            ├── skills/          # SKILL.md files → /.agents/skills/<name>/
            └── workspace/       # Files seeded into the remote environment at root

        Required keys in agent.yaml: `id`, `base_agent`. Other keys are optional.

        Sets `self.agent` to the yaml `id` so subsequent tool calls invoke that
        named agent, and seeds `self.default_sources` from workspace/ + skills/.
        When `register=True`, POSTs the definition to /agents (409 = success).
        """
        from pathlib import Path

        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise ImportError("agent_directory requires PyYAML. Install with: pip install pyyaml") from e

        path = Path(directory)
        if not path.is_dir():
            raise FileNotFoundError(f"agent directory not found: {directory}")
        config_path = path / "agent.yaml"
        if not config_path.is_file():
            raise FileNotFoundError(f"agent.yaml not found in {directory}")
        config = yaml.safe_load(config_path.read_text()) or {}

        agent_id = config.get("id")
        base_agent = config.get("base_agent")
        if not agent_id or not base_agent:
            raise ValueError("agent.yaml must contain both `id` and `base_agent`")

        instructions = config.get("system_instruction")
        agents_md = path / "AGENTS.md"
        if agents_md.is_file():
            instructions = agents_md.read_text()

        sources = self._build_sources_from_directory(path)

        # Apply to this toolkit so all subsequent run_antigravity_task calls
        # invoke the named agent with the right env sources.
        self.agent = str(agent_id)
        self.default_sources = sources or None

        if register:
            body: Dict[str, Any] = {"name": agent_id, "base_agent": str(base_agent)}
            if instructions:
                body["instructions"] = instructions
            if config.get("description"):
                body["description"] = config["description"]
            if sources:
                body["base_environment"] = {"type": "remote", "sources": sources}
            log_debug(f"Antigravity: registering agent {agent_id!r} from {directory}")
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}/agents", json=body, headers=self._headers())
            if response.status_code == 409:
                log_debug(f"Antigravity: agent {agent_id!r} already exists, reusing")
            elif response.status_code >= 400:
                raise RuntimeError(f"Antigravity POST /agents returned {response.status_code}: {response.text}")

    @staticmethod
    def _build_sources_from_directory(path: Any) -> List[Dict[str, Any]]:
        """Walk workspace/ and skills/ and turn them into inline source dicts.

        - workspace/<rel> → target /<rel>
        - skills/<name>/<rel> → target /.agents/skills/<name>/<rel>

        Files larger than 75 KB are skipped with a warning (API inline-source limit).
        Binary files are skipped (the API supports text files only).
        """
        from pathlib import Path

        if not isinstance(path, Path):
            path = Path(path)

        sources: List[Dict[str, Any]] = []

        def add(file_path: Any, target: str) -> None:
            try:
                size = file_path.stat().st_size
            except OSError as e:
                log_warning(f"agent_directory: cannot stat {file_path}: {e}; skipping")
                return
            if size > INLINE_SOURCE_MAX_BYTES:
                log_warning(
                    f"agent_directory: {file_path} is {size} bytes > {INLINE_SOURCE_MAX_BYTES} "
                    "inline limit; skipping. Move to GCS or a Git repo source instead."
                )
                return
            try:
                content = file_path.read_text()
            except UnicodeDecodeError:
                log_warning(f"agent_directory: {file_path} is not UTF-8 text; skipping (binary not supported)")
                return
            sources.append({"type": "inline", "content": content, "target": target})

        workspace = path / "workspace"
        if workspace.is_dir():
            for f in workspace.rglob("*"):
                if f.is_file():
                    add(f, "/" + f.relative_to(workspace).as_posix())

        skills = path / "skills"
        if skills.is_dir():
            for f in skills.rglob("*"):
                if f.is_file():
                    add(f, "/.agents/skills/" + f.relative_to(skills).as_posix())

        return sources

    @staticmethod
    def _session_state(agent: Optional[Union[Agent, Team]]) -> Optional[Dict[str, Any]]:
        if agent is None or not hasattr(agent, "session_state"):
            return None
        if agent.session_state is None:
            agent.session_state = {}
        return agent.session_state

    @staticmethod
    def _extract_final_text(response_json: Dict[str, Any]) -> str:
        """Real response shape: top-level `outputs` is a list of text blocks.
        Docs also mention `steps[].content[]`; handle both for forward-compat."""
        parts: List[str] = []
        for block in response_json.get("outputs", []) or []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
        if parts:
            return "".join(parts)
        for step in response_json.get("steps", []) or []:
            if step.get("type") != "model_output":
                continue
            for block in step.get("content", []) or []:
                if block.get("type") == "text" and block.get("text"):
                    parts.append(str(block["text"]))
        return "".join(parts)

    # ---------------------------------------------------------------------------
    # Agent-callable tools
    # ---------------------------------------------------------------------------

    def run_antigravity_task(self, agent: Union[Agent, Team], task: str) -> str:
        """Delegate a task to an Antigravity sandbox and return its final response.

        The sandbox is created on first use and reused across calls within the
        same session. State (files, installed packages) persists.

        Args:
            agent: Calling Agno agent (injected automatically by the toolkit).
            task: Natural-language task description for the Antigravity agent.

        Returns:
            The final text response from the Antigravity agent.
        """
        try:
            state = self._session_state(agent) if self.persistent else None
            environment_value: Any
            if state and state.get("antigravity_env_id"):
                environment_value = state["antigravity_env_id"]
            elif self.default_sources:
                environment_value = {"type": "remote", "sources": self.default_sources}
            else:
                environment_value = "remote"

            body: Dict[str, Any] = {
                "agent": self.agent,
                "input": [{"type": "text", "text": task}],
                "environment": environment_value,
                "stream": False,
            }
            if state and state.get("antigravity_previous_interaction_id"):
                body["previous_interaction_id"] = state["antigravity_previous_interaction_id"]

            log_debug(f"Antigravity: dispatching task (env reused={bool(state and state.get('antigravity_env_id'))})")
            data = self._post("/interactions", body)
            log_debug(f"Antigravity response keys: {list(data.keys())}, status={data.get('status')}")

            if state is not None:
                if data.get("environment_id"):
                    state["antigravity_env_id"] = data["environment_id"]
                if data.get("id"):
                    state["antigravity_previous_interaction_id"] = data["id"]

            text = self._extract_final_text(data)
            if text:
                return text
            # No model_output text block found. Surface the raw payload so the
            # calling model has something to work with rather than retrying blindly.
            return json.dumps(data)
        except Exception as e:
            log_error(f"Antigravity run_antigravity_task failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def run_custom_antigravity_agent(self, agent: Union[Agent, Team], custom_agent_name: str, task: str) -> str:
        """Invoke a named custom Antigravity agent (created via /agents) and return its response.

        Use this when the user has already registered a custom agent definition and wants
        to invoke it by name. The sandbox environment is per-session (cached in
        agent.session_state under a key scoped to the custom agent name).

        Args:
            agent: Calling Agno agent (injected automatically).
            custom_agent_name: Name of the previously-created custom agent.
            task: Natural-language task for the custom agent.

        Returns:
            The final text response, or a JSON error string.
        """
        try:
            state = self._session_state(agent) if self.persistent else None
            env_key = f"antigravity_env_id__{custom_agent_name}"
            prev_key = f"antigravity_previous_interaction_id__{custom_agent_name}"

            environment_value: Any = state.get(env_key) if state and state.get(env_key) else "remote"

            body: Dict[str, Any] = {
                "agent": custom_agent_name,
                "input": [{"type": "text", "text": task}],
                "environment": environment_value,
                "stream": False,
            }
            if state and state.get(prev_key):
                body["previous_interaction_id"] = state[prev_key]

            log_debug(f"Antigravity: invoking custom agent {custom_agent_name!r}")
            data = self._post("/interactions", body)

            if state is not None:
                if data.get("environment_id"):
                    state[env_key] = data["environment_id"]
                if data.get("id"):
                    state[prev_key] = data["id"]

            return self._extract_final_text(data) or json.dumps(data)
        except Exception as e:
            log_error(f"Antigravity run_custom_antigravity_agent failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def create_custom_antigravity_agent(
        self,
        name: str,
        instructions: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        base_env_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        """Create a named, reusable Antigravity agent via POST /agents.

        Two ways to seed the agent's base environment (mutually exclusive):
          - `sources`: fresh environment built from inline/GCS/repository sources.
          - `base_env_id`: fork an existing successful environment by id.

        Args:
            name: Identifier for the custom agent.
            instructions: System instructions for the agent.
            sources: Optional list of source dicts for a fresh base environment.
            base_env_id: Optional env id to fork from (alternative to `sources`).
            description: Optional human-readable description.

        Returns:
            JSON string with the created agent's metadata, or an error.
        """
        try:
            body: Dict[str, Any] = {
                "name": name,
                "base_agent": self.agent,
                "instructions": instructions,
            }
            if description:
                body["description"] = description
            if base_env_id:
                body["base_environment"] = {"env_id": base_env_id}
            elif sources:
                body["base_environment"] = {"type": "remote", "sources": sources}
            data = self._post("/agents", body)
            return json.dumps(data)
        except Exception as e:
            log_error(f"Antigravity create_custom_antigravity_agent failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def update_custom_antigravity_agent(
        self,
        name: str,
        instructions: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        """Update mutable fields on a custom Antigravity agent via PATCH /agents/{name}.

        Args:
            name: Identifier of the agent to update.
            instructions: New system instructions (if changing).
            description: New human-readable description (if changing).

        Returns:
            JSON string with the updated agent's metadata, or an error.
        """
        try:
            body: Dict[str, Any] = {}
            if instructions is not None:
                body["instructions"] = instructions
            if description is not None:
                body["description"] = description
            if not body:
                return json.dumps({"status": "error", "message": "no fields to update"})
            return json.dumps(self._patch(f"/agents/{name}", body))
        except Exception as e:
            log_error(f"Antigravity update_custom_antigravity_agent failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def get_custom_antigravity_agent(self, name: str) -> str:
        """Fetch a single custom Antigravity agent by name via GET /agents/{name}."""
        try:
            return json.dumps(self._get(f"/agents/{name}"))
        except Exception as e:
            log_error(f"Antigravity get_custom_antigravity_agent failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def list_antigravity_agents(self) -> str:
        """List all custom Antigravity agents owned by the API key."""
        try:
            return json.dumps(self._get("/agents"))
        except Exception as e:
            log_error(f"Antigravity list_antigravity_agents failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def list_antigravity_agent_versions(self, name: str) -> str:
        """List versions of a custom Antigravity agent via GET /agents/{name}/versions."""
        try:
            return json.dumps(self._get(f"/agents/{name}/versions"))
        except Exception as e:
            log_error(f"Antigravity list_antigravity_agent_versions failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def delete_antigravity_agent(self, name: str) -> str:
        """Delete a custom Antigravity agent by name."""
        try:
            self._delete(f"/agents/{name}")
            return json.dumps({"status": "ok", "deleted": name})
        except Exception as e:
            log_error(f"Antigravity delete_antigravity_agent failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def download_antigravity_environment_snapshot(
        self, environment_id: str, output_path: str, agent: Optional[Union[Agent, Team]] = None
    ) -> str:
        """Download a sandbox environment snapshot as a tar file.

        Hits GET /v1beta/files/environment-{environment_id}:download?alt=media. The
        endpoint redirects to the actual content host, so we follow redirects.

        Args:
            environment_id: The env id to snapshot. Pass "current" to use the env id
                cached in the calling agent's session_state (from a prior
                run_antigravity_task call).
            output_path: Local filesystem path to write the tar file to.
            agent: Calling Agno agent (injected automatically); used only when
                environment_id == "current".

        Returns:
            JSON status string with `path` and `bytes` on success.
        """
        try:
            env_id = environment_id
            if env_id == "current":
                state = self._session_state(agent)
                if not state or not state.get("antigravity_env_id"):
                    return json.dumps(
                        {"status": "error", "message": "no cached env id; run a task first or pass an explicit id"}
                    )
                env_id = state["antigravity_env_id"]

            url = f"{self.base_url}/files/environment-{env_id}:download?alt=media"
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                with client.stream("GET", url, headers=self._headers()) as response:
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", errors="replace")
                        raise RuntimeError(f"Antigravity snapshot download returned {response.status_code}: {body}")
                    written = 0
                    with open(output_path, "wb") as fh:
                        for chunk in response.iter_bytes():
                            fh.write(chunk)
                            written += len(chunk)
            log_debug(f"Antigravity: wrote snapshot ({written} bytes) for env {env_id} to {output_path}")
            return json.dumps({"status": "ok", "path": output_path, "bytes": written, "environment_id": env_id})
        except Exception as e:
            log_error(f"Antigravity download_antigravity_environment_snapshot failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})
