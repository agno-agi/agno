import json
from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.agents.base import BaseExternalAgent
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.utils.log import log_debug, log_warning

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
INLINE_SOURCE_MAX_BYTES = 75 * 1024  # API limit for inline source content per file


@dataclass
class AntigravityAgent(BaseExternalAgent):
    """Adapter for Google's Gemini Agents API (Antigravity).

    Wraps the managed Gemini Agents API so an Antigravity-backed agent can be used
    with AgentOS endpoints or standalone via .run() / .print_response().

    Antigravity runs a full agent loop server-side inside a sandboxed Linux
    environment. The environment persists across turns via an environment_id,
    which this adapter caches per Agno session_id so multi-turn conversations
    keep state.

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        api_key: Gemini API key. Falls back to GEMINI_API_KEY env var.
        base_url: API base URL.
        agent: Base agent name (default "antigravity-preview-05-2026") or a custom agent id.
        sources: Optional list of source dicts (gcs/repository/inline) to seed
            the environment on the first turn of each session.
        timeout: Per-request timeout in seconds.

    Example:
        from agno.agents.antigravity import AntigravityAgent

        agent = AntigravityAgent(name="Antigravity")
        agent.print_response("What is 2 + 2?", stream=True)

        # Or deploy with AgentOS:
        from agno.os import AgentOS
        AgentOS(agents=[agent])
    """

    api_key: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    agent: str = "antigravity-preview-05-2026"
    sources: Optional[List[Dict[str, Any]]] = None
    timeout: int = 600
    framework: str = "antigravity"

    # Custom-agent definition (Agents API). When `custom_agent_name` is set, the
    # adapter sends `agent: <name>` on /interactions. Call `ensure_custom_agent()`
    # once to register the definition on the API before invoking.
    custom_agent_name: Optional[str] = None
    custom_agent_instructions: Optional[str] = None
    custom_agent_description: Optional[str] = None

    # Per-session env/interaction state lives in the persisted session's
    # session_data, not on this instance (thread-safe, survives restarts).
    _ENV_KEY = "antigravity_env_id"
    _PREV_KEY = "antigravity_previous_interaction_id"

    def _resolved_api_key(self) -> str:
        key = self.api_key or getenv("GEMINI_API_KEY")
        if not key:
            raise ValueError("GEMINI_API_KEY not set. Pass api_key= or set the GEMINI_API_KEY environment variable.")
        return key

    def _resolved_agent(self) -> str:
        """Which agent name to send in the /interactions body."""
        if self.custom_agent_name:
            return self.custom_agent_name
        return self.agent

    def ensure_custom_agent(self) -> Dict[str, Any]:
        """Create (or confirm existence of) the custom agent definition on the API.

        Idempotent: a 409/conflict is treated as 'already exists'. Returns the
        agent metadata from the API on create, or {} if it already existed.

        Raises ValueError if custom_agent_name is not set on this adapter.
        """
        import httpx

        if not self.custom_agent_name:
            raise ValueError("ensure_custom_agent requires custom_agent_name to be set on the adapter")
        body: Dict[str, Any] = {
            "name": self.custom_agent_name,
            "base_agent": self.agent,
        }
        if self.custom_agent_instructions:
            body["instructions"] = self.custom_agent_instructions
        if self.custom_agent_description:
            body["description"] = self.custom_agent_description
        if self.sources:
            body["base_environment"] = {"type": "remote", "sources": self.sources}

        headers = {"Content-Type": "application/json", "x-goog-api-key": self._resolved_api_key()}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}/agents", json=body, headers=headers)

        if response.status_code == 409:
            log_debug(f"Antigravity: custom agent {self.custom_agent_name!r} already exists, reusing")
            return {}
        if response.status_code >= 400:
            raise RuntimeError(f"Antigravity POST /agents returned {response.status_code}: {response.text}")
        return response.json()

    def download_environment_snapshot(
        self, output_path: str, *, environment_id: Optional[str] = None, session_id: Optional[str] = None
    ) -> int:
        """Download an environment snapshot tar to `output_path`. Returns bytes written.

        Resolution order for which env to snapshot:
          1. Explicit `environment_id` arg.
          2. The env id persisted in `session_id`'s session_data (from a prior
             turn in that session; requires a db to be configured).
          3. Raises ValueError if neither is available.
        """
        import httpx

        env_id = environment_id
        if not env_id and session_id and self.db is not None:
            session = self.read_or_create_session(session_id)
            env_id = (session.session_data or {}).get(self._ENV_KEY)
        if not env_id:
            raise ValueError(
                "download_environment_snapshot needs an environment_id, or a session_id "
                "(with a db configured) whose prior turn captured an env id"
            )

        url = f"{self.base_url}/files/environment-{env_id}:download?alt=media"
        headers = {"x-goog-api-key": self._resolved_api_key()}
        written = 0
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code >= 400:
                    body = response.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"Antigravity snapshot download returned {response.status_code}: {body}")
                with open(output_path, "wb") as fh:
                    for chunk in response.iter_bytes():
                        fh.write(chunk)
                        written += len(chunk)
        log_debug(f"Antigravity: wrote snapshot ({written} bytes) for env {env_id} to {output_path}")
        return written

    @classmethod
    def from_agent_directory(
        cls,
        directory: str,
        *,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        register: bool = True,
        timeout: int = 600,
        db: Any = None,
    ) -> "AntigravityAgent":
        """Build a `AntigravityAgent` from a local agent directory.

        Expected layout (per the Managed Agents docs):

            my-agent/
            ├── agent.yaml       # id, base_agent, description, system_instruction
            ├── AGENTS.md        # System instructions (overrides agent.yaml.system_instruction)
            ├── skills/          # SKILL.md files mounted under /.agents/skills/<name>/
            └── workspace/       # Files seeded into the remote environment at root

        Required keys in `agent.yaml`: `id`, `base_agent`. Other keys are optional.

        Files larger than 75 KB are skipped with a warning (API inline-source limit).
        Binary files are skipped (the API currently supports text files only).

        If `register` is True (default), the agent definition is registered with
        the API via POST /agents before returning. 409 / already-exists is treated
        as success. Pass `register=False` to defer registration (caller must invoke
        `agent.ensure_custom_agent()` before the first run).
        """
        from pathlib import Path

        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise ImportError("from_agent_directory requires PyYAML. Install with: pip install pyyaml") from e

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

        # AGENTS.md takes precedence over system_instruction in the yaml
        instructions: Optional[str] = config.get("system_instruction")
        agents_md = path / "AGENTS.md"
        if agents_md.is_file():
            instructions = agents_md.read_text()

        sources = cls._build_sources_from_directory(path)

        agent = cls(
            name=agent_id,
            api_key=api_key,
            base_url=base_url,
            agent=str(base_agent),
            custom_agent_name=str(agent_id),
            custom_agent_instructions=instructions,
            custom_agent_description=config.get("description"),
            sources=sources or None,
            timeout=timeout,
            db=db,
        )
        if register:
            agent.ensure_custom_agent()
        return agent

    @staticmethod
    def _build_sources_from_directory(path: Any) -> List[Dict[str, Any]]:
        """Walk workspace/ and skills/ and turn them into inline source dicts.

        - workspace/<rel> → target /<rel>
        - skills/<name>/<rel> → target /.agents/skills/<name>/<rel>
        """
        from pathlib import Path

        if not isinstance(path, Path):
            path = Path(path)

        sources: List[Dict[str, Any]] = []

        def add(file_path: Any, target: str) -> None:
            try:
                size = file_path.stat().st_size
            except OSError as e:
                log_warning(f"from_agent_directory: cannot stat {file_path}: {e}; skipping")
                return
            if size > INLINE_SOURCE_MAX_BYTES:
                log_warning(
                    f"from_agent_directory: {file_path} is {size} bytes > {INLINE_SOURCE_MAX_BYTES} "
                    "inline limit; skipping. Move to GCS or a Git repo source instead."
                )
                return
            try:
                content = file_path.read_text()
            except UnicodeDecodeError:
                log_warning(f"from_agent_directory: {file_path} is not UTF-8 text; skipping (binary not supported)")
                return
            sources.append({"type": "inline", "content": content, "target": target})

        workspace = path / "workspace"
        if workspace.is_dir():
            for f in workspace.rglob("*"):
                if f.is_file():
                    add(f, "/" + str(f.relative_to(workspace)))

        skills = path / "skills"
        if skills.is_dir():
            for f in skills.rglob("*"):
                if f.is_file():
                    add(f, "/.agents/skills/" + str(f.relative_to(skills)))

        return sources

    def _read_session_env(self, session: Any) -> tuple:
        """Return (env_id, previous_interaction_id) from the given session.

        `session` is the AgentSession the base class loaded for this turn, or
        None when no db is configured — in which case there's no cross-turn
        persistence and each turn provisions a fresh sandbox.
        """
        if session is None:
            return None, None
        data = session.session_data or {}
        return data.get(self._ENV_KEY), data.get(self._PREV_KEY)

    def _write_session_env(
        self,
        session: Any,
        environment_id: Optional[str],
        interaction_id: Optional[str],
    ) -> None:
        """Stash env/interaction ids on the session's session_data in place.

        The base class upserts this session after the adapter returns, so no
        DB write happens here. No-op without a session (no-db graceful degrade).
        """
        if session is None or (not environment_id and not interaction_id):
            return
        if session.session_data is None:
            session.session_data = {}
        if environment_id:
            session.session_data[self._ENV_KEY] = environment_id
        if interaction_id:
            session.session_data[self._PREV_KEY] = interaction_id

    def _environment_field(self, cached_env_id: Optional[str]) -> Any:
        """Pick the `environment` value for the request body.

        Reuse a cached env id for subsequent turns; seed sources on the first
        turn. When `custom_agent_name` is set, sources belong to the agent
        definition (sent via POST /agents), so they are NOT sent here.
        """
        if cached_env_id:
            return cached_env_id
        if self.sources and not self.custom_agent_name:
            return {"type": "remote", "sources": self.sources}
        return "remote"

    def _build_request_body(self, input: Any, session: Any, stream: bool) -> Dict[str, Any]:
        cached_env_id, prev_id = self._read_session_env(session)
        body: Dict[str, Any] = {
            "agent": self._resolved_agent(),
            "input": [{"type": "text", "text": str(input)}],
            "environment": self._environment_field(cached_env_id),
            "stream": stream,
        }
        if prev_id:
            body["previous_interaction_id"] = prev_id
        return body

    @staticmethod
    def _extract_final_text(response_json: Dict[str, Any]) -> str:
        """Pull the assistant text out of a non-streaming /interactions response.

        Real response shape (observed): top-level `outputs` is a list of
        {"type": "text", "text": "..."} blocks. The docs also mention a
        `steps[].content[]` shape; we handle both for forward-compat.
        """
        text_parts: List[str] = []

        for block in response_json.get("outputs", []) or []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                text_parts.append(str(block["text"]))
        if text_parts:
            return "".join(text_parts)

        for step in response_json.get("steps", []) or []:
            if step.get("type") != "model_output":
                continue
            for block in step.get("content", []) or []:
                if block.get("type") == "text" and block.get("text"):
                    text_parts.append(str(block["text"]))
        return "".join(text_parts)

    async def _arun_adapter(self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> str:
        """Non-streaming POST /interactions, return the final text."""
        import httpx

        session = kwargs.get("session")
        session_id = kwargs.get("session_id")
        body = self._build_request_body(input, session, stream=False)
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._resolved_api_key()}

        log_debug(
            f"Antigravity request: session_id={session_id}, environment={body['environment']!r}, "
            f"previous_interaction_id={body.get('previous_interaction_id')!r}"
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/interactions",
                json=body,
                headers=headers,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Antigravity /interactions returned {response.status_code}: {response.text}")
            data = response.json()

        self._write_session_env(
            session,
            environment_id=data.get("environment_id"),
            interaction_id=data.get("id"),
        )
        return self._extract_final_text(data)

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming POST /interactions, translate SSE events to Agno events."""
        import httpx

        run_id = kwargs.get("run_id", str(uuid4()))
        session = kwargs.get("session")
        session_id = kwargs.get("session_id")
        body = self._build_request_body(input, session, stream=True)
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._resolved_api_key()}

        # Track tool calls so Started/Completed pair up by tool_call_id.
        tool_info_map: Dict[str, Dict[str, Any]] = {}
        final_env_id: Optional[str] = None
        final_interaction_id: Optional[str] = None

        log_debug(
            f"Antigravity stream request: session_id={session_id}, environment={body['environment']!r}, "
            f"previous_interaction_id={body.get('previous_interaction_id')!r}"
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/interactions",
                json=body,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    error_text = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"Antigravity /interactions returned {response.status_code}: {error_text}")

                async for raw_line in response.aiter_lines():
                    if not raw_line or not raw_line.startswith("data:"):
                        continue
                    payload = raw_line[len("data:") :].strip()
                    if not payload:
                        continue
                    if payload == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError as e:
                        log_debug(f"Antigravity: skipping non-JSON SSE payload: {e}")
                        continue

                    async for translated in self._translate_sse_event(
                        event=event,
                        run_id=run_id,
                        tool_info_map=tool_info_map,
                    ):
                        yield translated

                    # Capture ids from wherever they appear. Real API shape (observed):
                    #   {"interaction": {...}, "event_type": "interaction.status_update", "interaction_id": "v1_..."}
                    # so try multiple known locations.
                    final_interaction_id = (
                        event.get("interaction_id")
                        or event.get("id")
                        or (event.get("interaction") or {}).get("id")
                        or final_interaction_id
                    )
                    interaction_obj = event.get("interaction") or {}
                    env_obj = interaction_obj.get("environment")
                    final_env_id = (
                        event.get("environment_id")
                        or interaction_obj.get("environment_id")
                        or (env_obj.get("id") if isinstance(env_obj, dict) else None)
                        or final_env_id
                    )

        log_debug(
            f"Antigravity stream complete: environment_id={final_env_id!r}, interaction_id={final_interaction_id!r}"
        )
        self._write_session_env(session, final_env_id, final_interaction_id)

    async def _translate_sse_event(
        self,
        *,
        event: Dict[str, Any],
        run_id: str,
        tool_info_map: Dict[str, Dict[str, Any]],
    ) -> AsyncIterator[RunOutputEvent]:
        """Translate a single Antigravity SSE event into zero or more Agno events.

        Async generator because SSE shape may produce multiple Agno events per
        frame (e.g. concurrent content + tool_call).

        Per the API docs, content shape varies by event type and is accessed via
        `event.delta`. We handle text deltas, tool calls, and tool results; other
        events (thoughts, status frames) are surfaced as content where possible
        and otherwise dropped.
        """
        event_type = event.get("type") or ""
        delta = event.get("delta") or {}

        # Plain text delta (final user-facing output stream)
        if isinstance(delta, dict):
            text = delta.get("text")
            if text:
                yield RunContentEvent(
                    run_id=run_id,
                    agent_id=self.get_id(),
                    agent_name=self.name or "",
                    content=str(text),
                )

            # Thought stream (model's internal reasoning) — exposed as reasoning_content
            content_block = delta.get("content")
            if isinstance(content_block, dict):
                thought_text = content_block.get("text")
                if thought_text:
                    yield RunContentEvent(
                        run_id=run_id,
                        agent_id=self.get_id(),
                        agent_name=self.name or "",
                        content="",
                        reasoning_content=str(thought_text),
                    )

        # Function call start. The exact discriminator field is `type` either on the
        # event or on `delta`; we accept both.
        is_function_call = event_type in ("function_call", "tool_call", "tool_call_started") or (
            isinstance(delta, dict) and delta.get("type") in ("function_call", "tool_call")
        )
        if is_function_call:
            tool_name = event.get("name") or (isinstance(delta, dict) and delta.get("name")) or "unknown"
            raw_args = (
                event.get("arguments")
                if event.get("arguments") is not None
                else (delta.get("arguments") if isinstance(delta, dict) else None)
            )
            tool_args = self._coerce_tool_args(raw_args)
            tool_call_id = (
                event.get("tool_call_id")
                or event.get("id")
                or (isinstance(delta, dict) and (delta.get("tool_call_id") or delta.get("id")))
                or str(uuid4())
            )
            tool_info_map[tool_call_id] = {"name": tool_name, "args": tool_args}
            yield ToolCallStartedEvent(
                run_id=run_id,
                agent_id=self.get_id(),
                agent_name=self.name or "",
                tool=ToolExecution(
                    tool_call_id=tool_call_id,
                    tool_name=str(tool_name),
                    tool_args=tool_args,
                ),
            )

        # Function/tool result
        is_function_result = event_type in ("function_result", "tool_result", "tool_call_completed") or (
            isinstance(delta, dict) and delta.get("type") in ("function_result", "tool_result")
        )
        if is_function_result:
            tool_call_id = (
                event.get("tool_call_id")
                or event.get("id")
                or (isinstance(delta, dict) and (delta.get("tool_call_id") or delta.get("id")))
                or ""
            )
            result_value = (
                event.get("result")
                if event.get("result") is not None
                else (delta.get("result") if isinstance(delta, dict) else None)
            )
            info = tool_info_map.get(tool_call_id, {})
            yield ToolCallCompletedEvent(
                run_id=run_id,
                agent_id=self.get_id(),
                agent_name=self.name or "",
                tool=ToolExecution(
                    tool_call_id=tool_call_id,
                    tool_name=str(info.get("name", "")),
                    tool_args=info.get("args"),
                    result=str(result_value) if result_value is not None else None,
                ),
            )

    @staticmethod
    def _coerce_tool_args(raw: Any) -> Optional[Dict[str, Any]]:
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {"input": parsed}
            except json.JSONDecodeError:
                return {"input": raw}
        return {"input": raw}
