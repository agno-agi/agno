"""Nimble Agent API V2 toolkit for Agno.

Exposes Nimble's Web Search Agent lifecycle (Agent API V2) as three separate,
poll-driven tools plus read-only discovery:

- ``start_agent_run`` starts an asynchronous run and returns immediately.
- ``get_agent_run_status`` reports the run's lifecycle state without waiting.
- ``get_agent_run_result`` is non-blocking: it returns a ``not_ready`` state while
  the run is active and returns the grounded, cited output only once the run has
  completed.
- ``list_agents`` / ``list_agent_templates`` are read-only discovery helpers.

The agent (the LLM) drives the poll loop: start a run, poll status until it is
terminal, then fetch the result. Each tool also has an async variant used
automatically by ``agent.arun()``.

Design and safety notes:

- Three identity modes are supported: an explicit existing ``agent_id``; an
  ``agent_name`` that Nimble creates or reuses server-side; or neither, which
  auto-provisions an agent for a one-off run and returns its id.
- Un-idempotent writes are never retried. The public API exposes no idempotency
  key, so ``start_agent_run`` uses a client built with ``max_retries=0``; safe
  reads get a bounded retry budget per call via ``with_options``.
- Effort is optional. When omitted, Nimble applies the selected agent or template
  default (the product default is ``high``); callers may override it with
  ``low``, ``medium``, ``high``, ``x-high``, or the promotional ``max`` tier.
  ``max`` stops before create with custom-budget contact guidance.
- Every output is bounded and scrubbed of credential shapes before it is returned.
- Every request carries ``X-Client-Source: agno``.
"""

import json
import os
import re
from typing import Any, Dict, List, Literal, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from nimble_python import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        AsyncNimble,
        AuthenticationError,
        ConflictError,
        Nimble,
        NotFoundError,
        PermissionDeniedError,
        RateLimitError,
        UnprocessableEntityError,
    )
except ImportError:
    raise ImportError("`nimble-python` not installed. Please install using `pip install nimble-python`")

CLIENT_SOURCE = "agno"
ACTIVE_STATES = frozenset({"queued", "running"})
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
MAX_EFFORT_CONTACT = "https://www.nimbleway.com/contact"
# Mirrors the effort tiers nimble-python accepts. A unit test asserts this stays
# equal to the SDK's own Literal, so a tier added or renamed upstream fails loudly.
SUPPORTED_EFFORTS = frozenset({"low", "medium", "high", "x-high", "max"})

_SECRET_PATTERNS = (
    re.compile(r"nvapi-[A-Za-z0-9_-]+"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]+"),
    re.compile(r"sk-or-v1-[A-Za-z0-9]+"),
    re.compile(r"tvly-[A-Za-z0-9_-]+"),
    # Swallow an entire bearer token so no tail is left next to the marker.
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    # Nimble-style opaque hex credentials.
    re.compile(r"\b[0-9a-f]{40,}\b"),
)
_CREDENTIAL_ENV_VARS = ("NIMBLE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY")


def _redact_text(value: str) -> str:
    """Scrub credential shapes and any live key value present in the environment."""
    for name in _CREDENTIAL_ENV_VARS:
        secret = os.environ.get(name)
        # A short/placeholder value must not scrub ordinary prose.
        if secret and len(secret) >= 12:
            value = value.replace(secret, "<redacted>")
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("<redacted>", value)
    return value


def _model_to_dict(model: Any) -> Dict[str, Any]:
    """Convert a Nimble SDK (Stainless/Pydantic) model to a plain dict."""
    if hasattr(model, "to_dict"):
        value = model.to_dict()
    elif hasattr(model, "model_dump"):
        value = model.model_dump(mode="json")
    elif hasattr(model, "dict"):
        value = model.dict()
    else:
        raise TypeError("Nimble SDK response does not expose a supported dict conversion")
    if not isinstance(value, dict):
        raise TypeError("Nimble SDK response conversion did not return a dict")
    return value


def _bounded_content(content: Any, limit: int) -> Any:
    """Bound and scrub output content for both ``text`` and ``json`` result types."""
    if content is None:
        return None
    if isinstance(content, str):
        return _redact_text(content)[:limit]
    # A small ``type: "json"`` result keeps its public JSON shape after bounded
    # serialization; a large one degrades to bounded text.
    rendered = _redact_text(json.dumps(content, sort_keys=True, default=str))
    if len(rendered) > limit:
        return rendered[:limit] + "...[truncated]"
    return json.loads(rendered)


def _public_claims(value: Any) -> List[Dict[str, Any]]:
    """Keep bounded per-claim citation evidence for text and JSON trust."""
    if not isinstance(value, list):
        return []
    claims: List[Dict[str, Any]] = []
    for item in value[:10]:
        if not isinstance(item, dict):
            continue
        citations = item.get("citations")
        excerpts = item.get("excerpts")
        claims.append(
            {
                # ``callout`` for text output; ``path`` for JSON output.
                "callout": item.get("callout"),
                "path": item.get("path"),
                "confidence": item.get("confidence"),
                "reasoning": _redact_text(str(item.get("reasoning", "")))[:500],
                "excerpts": [
                    _redact_text(str(excerpt))[:500] for excerpt in (excerpts[:5] if isinstance(excerpts, list) else [])
                ],
                "citation_urls": [
                    _redact_text(str(citation.get("url", "")))[:500]
                    for citation in (citations if isinstance(citations, list) else [])[:10]
                    if isinstance(citation, dict)
                ],
            }
        )
    return claims


def _usability(trust: Optional[Dict[str, Any]]) -> str:
    """Separate a grounded completion from a degraded, uncited one.

    A run can ``complete`` with no sources; ``completed`` is not the same as
    grounded. Report ``grounded`` only when at least one claim is cited and the
    confidence is neither missing nor ``low``.
    """
    if not trust:
        return "degraded"
    claims = trust.get("claims")
    cited = any(
        isinstance(claim, dict) and bool(claim.get("citation_urls"))
        for claim in (claims if isinstance(claims, list) else [])
    )
    confidence = trust.get("confidence")
    return "grounded" if cited and confidence not in {None, "low"} else "degraded"


def _public_trust(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    sources = value.get("sources")
    claims = value.get("claims")
    return {
        "confidence": value.get("confidence"),
        "reasoning": _redact_text(str(value.get("reasoning", "")))[:500],
        "source_count": len(sources) if isinstance(sources, list) else 0,
        "claim_count": len(claims) if isinstance(claims, list) else 0,
        "sources": [
            {
                "url": _redact_text(str(item.get("url", "")))[:500],
                "title": _redact_text(str(item.get("title", "")))[:300],
                "type": item.get("type"),
                "source_category": item.get("source_category"),
                "extract_template_name": item.get("extract_template_name"),
            }
            for item in (sources if isinstance(sources, list) else [])[:10]
            if isinstance(item, dict)
        ],
        "claims": _public_claims(claims),
    }


def _public_result(result: Dict[str, Any], content_limit: int) -> Dict[str, Any]:
    """Render a completed run's result, bounding content and preserving trust.

    Defensive against the result being a success or a failure envelope (the
    Agent API V2 result operation returns a union on its success path).
    """
    run = result.get("run")
    output = result.get("output")
    rendered: Dict[str, Any] = {"state": "completed"}
    if isinstance(run, dict):
        rendered["run"] = {
            key: run.get(key) for key in ("id", "web_search_agent_id", "status", "effort", "interaction_id")
        }
    if isinstance(output, dict):
        trust = _public_trust(output.get("trust"))
        rendered["output"] = {
            "type": output.get("type"),
            "content": _bounded_content(output.get("content"), content_limit),
            "trust": trust,
            "usability": _usability(trust),
        }
    else:
        # Failure envelope on the success path: surface the error, not fake output.
        error = result.get("error")
        rendered["state"] = "failed"
        if isinstance(error, dict):
            rendered["error"] = _redact_text(str(error.get("message", "")))[:500]
    return rendered


def _bounded_limit(limit: int) -> int:
    """Clamp a model-supplied discovery limit so one tool call cannot flood the context."""
    try:
        return max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        return 20


def _summarize_agent(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "agent_name": item.get("agent_name"),
        "display_name": item.get("display_name"),
        "use_case": item.get("use_case"),
        "skill": item.get("skill"),
        "is_active": item.get("is_active"),
    }


def _summarize_template(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "template_name": item.get("template_name"),
        "display_name": item.get("display_name"),
        "use_case": item.get("use_case"),
        "skill": item.get("skill"),
        "description": _redact_text(str(item.get("description", "")))[:300] or None,
    }


class NimbleAgentTools(Toolkit):
    """Toolkit for Nimble's Agent API V2 (Web Search Agent) run lifecycle.

    Args:
        api_key (Optional[str]): Nimble API key. Falls back to the ``NIMBLE_API_KEY``
            environment variable.
        agent_id (Optional[str]): Default Nimble agent id (``wsa_...``) to run against.
            Falls back to the ``NIMBLE_AGENT_ID`` environment variable. When absent,
            start_agent_run can create or reuse by agent_name, or auto-provision.
        effort (Optional[str]): Optional run-level effort override: ``"low"``,
            ``"medium"``, ``"high"``, ``"x-high"``, or ``"max"``. When omitted,
            Nimble applies the selected agent/template default. ``"max"`` is a
            custom-budget tier and stops before create with contact guidance.
        timeout (int): Per-request timeout in seconds.
        max_read_retries (int): Bounded retry budget for safe, read-only calls.
            Writes (run creation) are never retried.
        poll_interval_seconds (float): Recommended delay between model-driven
            status checks. Defaults to 10 seconds and remains configurable.
            This toolkit does not sleep inside a tool call.
        max_content_chars (int): Upper bound on characters of result content returned.
        enable_run_lifecycle (bool): Register the ``start_agent_run`` /
            ``get_agent_run_status`` / ``get_agent_run_result`` tools. These are gated
            together because they are one workflow: starting a billable run without a
            way to poll and collect it is never useful. Default True.
        enable_discovery (bool): Register the read-only ``list_agents`` /
            ``list_agent_templates`` tools. Default True.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        effort: Optional[Literal["low", "medium", "high", "x-high", "max"]] = None,
        timeout: int = 30,
        max_read_retries: int = 2,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_content_chars: int = 4000,
        enable_run_lifecycle: bool = True,
        enable_discovery: bool = True,
        **kwargs: Any,
    ):
        self.api_key: Optional[str] = api_key or os.getenv("NIMBLE_API_KEY")
        if not self.api_key:
            log_error("NIMBLE_API_KEY not set. Set the NIMBLE_API_KEY environment variable or pass api_key.")

        self.agent_id: Optional[str] = agent_id or os.getenv("NIMBLE_AGENT_ID")

        if effort is not None and effort not in SUPPORTED_EFFORTS:
            raise ValueError(
                "effort must be one of 'low', 'medium', 'high', 'x-high', or 'max'; "
                "omit it to use the agent/template default"
            )
        self.effort: Optional[Literal["low", "medium", "high", "x-high", "max"]] = effort

        self._timeout: int = timeout
        self.max_read_retries: int = max_read_retries
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than zero")
        self.poll_interval_seconds: float = float(poll_interval_seconds)
        self.max_content_chars: int = max_content_chars

        self._sync_client: Optional[Nimble] = self._build_sync_client() if self.api_key else None
        self._async_client: Optional[AsyncNimble] = None  # built lazily on first async use

        tools: List[Any] = []
        async_tools: List[Any] = []
        if enable_run_lifecycle:
            tools += [
                self.start_agent_run,
                self.get_agent_run_status,
                self.get_agent_run_result,
            ]
            async_tools += [
                (self.astart_agent_run, "start_agent_run"),
                (self.aget_agent_run_status, "get_agent_run_status"),
                (self.aget_agent_run_result, "get_agent_run_result"),
            ]
        if enable_discovery:
            tools += [self.list_agents, self.list_agent_templates]
            async_tools += [
                (self.alist_agents, "list_agents"),
                (self.alist_agent_templates, "list_agent_templates"),
            ]

        super().__init__(
            name="nimble_agent_tools",
            tools=tools,
            async_tools=async_tools,
            timeout=timeout,
            **kwargs,
        )

    # -- client construction ------------------------------------------------

    def _build_sync_client(self) -> Nimble:
        # max_retries=0 protects the un-idempotent run write; reads restore a
        # budget per call via with_options().
        return Nimble(
            api_key=self.api_key,
            client_source=CLIENT_SOURCE,
            timeout=self._timeout,
            max_retries=0,
        )

    def _get_async_client(self) -> AsyncNimble:
        if self._async_client is None:
            self._async_client = AsyncNimble(
                api_key=self.api_key,
                client_source=CLIENT_SOURCE,
                timeout=self._timeout,
                max_retries=0,
            )
        return self._async_client

    # -- shared helpers -----------------------------------------------------

    def _resolve_agent_id(self, agent_id: Optional[str]) -> Optional[str]:
        return agent_id or self.agent_id

    @staticmethod
    def _run_options(
        *,
        agent_name: Optional[str],
        use_case: Optional[str],
        skill: Optional[str],
        input_data: Any,
        output_schema: Optional[Dict[str, Any]],
        sources: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build the typed per-run options supported by nimble-python 1.2.0."""
        typed = {
            "agent_name": agent_name,
            "use_case": use_case,
            "skill": skill,
            "input_data": input_data,
            "output_schema": output_schema,
            "sources": sources,
        }
        return {key: value for key, value in typed.items() if value is not None}

    @staticmethod
    def _error(message: str, **extra: Any) -> str:
        payload: Dict[str, Any] = {"error": _redact_text(message)}
        payload.update(extra)
        return json.dumps(payload, indent=2)

    def _map_exception(self, exc: Exception) -> str:
        """Map an SDK error to a redacted, actionable tool result. Never echo the key."""
        if isinstance(exc, AuthenticationError):
            return self._error("Authentication failed (401). Check NIMBLE_API_KEY.", code="unauthorized")
        if isinstance(exc, PermissionDeniedError):
            return self._error(
                "Permission denied (403). The account may lack access to this agent or feature.",
                code="forbidden",
            )
        if isinstance(exc, NotFoundError):
            return self._error("Not found (404). Verify the agent_id and run_id.", code="not_found")
        if isinstance(exc, RateLimitError):
            return self._error(
                "Rate limited (429). Stop and try again later; do not resubmit the run.",
                code="rate_limited",
                retry_after=_retry_after_of(exc),
            )
        if isinstance(exc, ConflictError):
            return self._error("Run is still active (409). Poll status and retry.", code="not_ready")
        if isinstance(exc, UnprocessableEntityError):
            return self._error("Invalid request or non-successful result (422).", code="unprocessable")
        if isinstance(exc, (APITimeoutError, APIConnectionError)):
            return self._error("Network error contacting Nimble. Try again.", code="connection_error")
        if isinstance(exc, APIStatusError):
            return self._error(f"Nimble API error (HTTP {getattr(exc, 'status_code', 'unknown')}).", code="api_error")
        return self._error(_redact_text(str(exc))[:300] or "Unexpected error", code="error")

    def _render_created(self, created: Any) -> str:
        return json.dumps(
            {
                "agent_id": created.web_search_agent_id,
                "run_id": created.id,
                "status": created.status,
                "is_active": created.is_active,
                "effort": created.effort,
                "poll_after_seconds": self.poll_interval_seconds,
            },
            indent=2,
        )

    def _render_status(self, run: Any) -> str:
        payload: Dict[str, Any] = {
            "run_id": run.id,
            "agent_id": run.web_search_agent_id,
            "status": run.status,
            "is_active": run.is_active,
        }
        if run.status in ACTIVE_STATES:
            payload["poll_after_seconds"] = self.poll_interval_seconds
        error = getattr(run, "error", None)
        if error is not None:
            payload["error"] = _redact_text(str(getattr(error, "message", error)))[:500]
        return json.dumps(payload, indent=2)

    def _render_result_from_run(self, run: Any, result: Any) -> str:
        """Render a terminal run into a tool result, branching on status and shape."""
        status = run.status
        if status in ACTIVE_STATES:
            return json.dumps(
                {
                    "state": "not_ready",
                    "status": status,
                    "run_id": run.id,
                    "agent_id": run.web_search_agent_id,
                    "message": "Run is still active. Poll get_agent_run_status and retry when completed.",
                    "poll_after_seconds": self.poll_interval_seconds,
                },
                indent=2,
            )
        if status in {"failed", "cancelled"}:
            error = getattr(run, "error", None)
            payload: Dict[str, Any] = {"state": status, "status": status, "run_id": run.id}
            if error is not None:
                payload["error"] = _redact_text(str(getattr(error, "message", error)))[:500]
            return json.dumps(payload, indent=2)
        if status != "completed":
            # Fail closed on an unknown status.
            return json.dumps({"state": "unknown", "status": status, "run_id": run.id}, indent=2)
        rendered = _public_result(_model_to_dict(result), self.max_content_chars)
        return json.dumps(rendered, indent=2)

    def _render_agents(self, response: Any) -> str:
        data = _model_to_dict(response)
        items = data.get("items") if isinstance(data, dict) else None
        agents = [_summarize_agent(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        return json.dumps({"agents": agents, "total": data.get("total")}, indent=2)

    def _render_templates(self, response: Any) -> str:
        data = _model_to_dict(response)
        items = data.get("items") if isinstance(data, dict) else None
        templates = (
            [_summarize_template(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        )
        return json.dumps({"templates": templates, "total": data.get("total")}, indent=2)

    # -- sync tools ---------------------------------------------------------

    def start_agent_run(
        self,
        query: str,
        agent_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        use_case: Optional[Literal["research", "enrichment", "dataset_building"]] = None,
        skill: Optional[str] = None,
        input_data: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        sources: Optional[Dict[str, Any]] = None,
        enable_events: bool = False,
    ) -> str:
        """Start a Nimble Agent API V2 run and return immediately without waiting.

        Pass an existing agent_id, pass agent_name to create or reuse an agent
        server-side, or omit both to auto-provision a one-off agent. Poll with
        get_agent_run_status, then fetch its output with get_agent_run_result.
        This creates a billable run and is never retried automatically.

        Args:
            query (str): The research question or task for the agent, in natural language.
            agent_id (Optional[str]): Existing Nimble agent id (wsa_...). Falls back
                to the configured default.
            agent_name (Optional[str]): Stable name to create or reuse server-side.
            use_case (Optional[str]): Creation-time mode: research, enrichment, or
                dataset_building. Existing agents reject a different locked value.
            skill (Optional[str]): One-time instructions overriding agent behavior.
            input_data (Optional[Union[List[Dict[str, Any]], Dict[str, Any]]]): Existing
                object or rows to enrich.
            output_schema (Optional[Dict[str, Any]]): JSON output contract.
            sources (Optional[Dict[str, Any]]): Source allow/block/avoid/prioritize guidance.
            enable_events (bool): Enable server-side run events.

        Returns:
            str: JSON with agent_id (wsa_...), run_id (task_run_...), status, is_active, and effort.
        """
        if self._sync_client is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        if self.effort == "max":
            return self._error(
                f"Nimble Max effort is available with a custom budget. Contact Nimble to enable it: {MAX_EFFORT_CONTACT}",
                code="effort_tier_coming_soon",
            )
        resolved = self._resolve_agent_id(agent_id)
        if resolved and agent_name:
            return self._error(
                "agent_name cannot be combined with an agent_id (passed or configured). Use one identity mode.",
                code="invalid_identity",
            )
        prompt = (query or "").strip()
        if not prompt:
            return self._error("query is required")
        run_kwargs = self._run_options(
            agent_name=agent_name,
            use_case=use_case,
            skill=skill,
            input_data=input_data,
            output_schema=output_schema,
            sources=sources,
        )
        # Both routes return the same run envelope shape; _render_created reads it structurally.
        created: Any
        request_options: Dict[str, Any] = {
            "input": prompt,
            "enable_events": enable_events,
            **run_kwargs,
        }
        if self.effort is not None:
            request_options["effort"] = self.effort
        try:
            if resolved:
                created = self._sync_client.agents.runs.create(
                    resolved,
                    **request_options,
                )
            else:
                # Generic route: Nimble provisions a minimal agent and returns its id.
                created = self._sync_client.agents.run(
                    **request_options,
                )
        except Exception as exc:  # surface a structured result rather than raising into the agent loop
            log_error(f"Nimble start_agent_run failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_created(created)

    def get_agent_run_status(self, run_id: str, agent_id: Optional[str] = None) -> str:
        """Check a Nimble run's lifecycle status without waiting for completion.

        Args:
            run_id (str): The run id (task_run_...) from start_agent_run.
            agent_id (Optional[str]): The owning agent id (wsa_...). Falls back to the
                configured default.

        Returns:
            str: JSON with run_id, agent_id, status (queued/running/completed/failed/cancelled),
                is_active, and error (when the run failed).
        """
        if self._sync_client is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        resolved = self._resolve_agent_id(agent_id)
        if not resolved:
            return self._error(
                "No Nimble agent configured. Pass agent_id or set NIMBLE_AGENT_ID.", code="no_agent_configured"
            )
        try:
            reader = self._sync_client.with_options(max_retries=self.max_read_retries)
            run = reader.agents.runs.get(run_id, agent_id=resolved)
        except Exception as exc:
            log_error(f"Nimble get_agent_run_status failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_status(run)

    def get_agent_run_result(self, run_id: str, agent_id: Optional[str] = None) -> str:
        """Retrieve a completed run's result. Non-blocking.

        Checks the run's status first. Returns a not_ready state while the run is still
        active (poll get_agent_run_status and retry), a failed/cancelled state for a
        terminal non-success, and the grounded output only once the run has completed.
        Completed output includes text or JSON content plus a trust envelope (confidence,
        sources, cited claims) and a grounded/degraded usability flag.

        Args:
            run_id (str): The run id (task_run_...) from start_agent_run.
            agent_id (Optional[str]): The owning agent id (wsa_...). Falls back to the
                configured default.

        Returns:
            str: JSON with a state field (completed/not_ready/failed/cancelled/unknown) and,
                when completed, the run envelope and the output with trust metadata.
        """
        if self._sync_client is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        resolved = self._resolve_agent_id(agent_id)
        if not resolved:
            return self._error(
                "No Nimble agent configured. Pass agent_id or set NIMBLE_AGENT_ID.", code="no_agent_configured"
            )
        try:
            reader = self._sync_client.with_options(max_retries=self.max_read_retries)
            run = reader.agents.runs.get(run_id, agent_id=resolved)
            if run.status != "completed":
                return self._render_result_from_run(run, None)
            result = reader.agents.runs.result(run_id, agent_id=resolved)
        except ConflictError:
            # Race: run reported completed but result endpoint says still active.
            return json.dumps({"state": "not_ready", "run_id": run_id, "message": "Result not ready yet."}, indent=2)
        except Exception as exc:
            log_error(f"Nimble get_agent_run_result failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_result_from_run(run, result)

    def list_agents(self, limit: int = 20) -> str:
        """List the account's existing Nimble agents (read-only discovery).

        Use this to find an agent id (wsa_...) to run against. This toolkit does not
        create agents.

        Args:
            limit (int): Maximum number of agents to return (default 20).

        Returns:
            str: JSON with a bounded list of agents (id, agent_name, display_name, use_case,
                skill, is_active) and the total count.
        """
        if self._sync_client is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        try:
            reader = self._sync_client.with_options(max_retries=self.max_read_retries)
            response = reader.agents.list(limit=_bounded_limit(limit))
        except Exception as exc:
            log_error(f"Nimble list_agents failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_agents(response)

    def list_agent_templates(self, limit: int = 20) -> str:
        """List the account's Nimble agent templates (read-only discovery).

        Args:
            limit (int): Maximum number of templates to return (default 20).

        Returns:
            str: JSON with a bounded list of templates (template_name, display_name,
                use_case, skill, description) and the total count.
        """
        if self._sync_client is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        try:
            reader = self._sync_client.with_options(max_retries=self.max_read_retries)
            response = reader.agents.templates.list(limit=_bounded_limit(limit))
        except Exception as exc:
            log_error(f"Nimble list_agent_templates failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_templates(response)

    # -- async tools --------------------------------------------------------

    async def astart_agent_run(
        self,
        query: str,
        agent_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        use_case: Optional[Literal["research", "enrichment", "dataset_building"]] = None,
        skill: Optional[str] = None,
        input_data: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        sources: Optional[Dict[str, Any]] = None,
        enable_events: bool = False,
    ) -> str:
        """Async variant of start_agent_run."""
        if self.api_key is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        if self.effort == "max":
            return self._error(
                f"Nimble Max effort is available with a custom budget. Contact Nimble to enable it: {MAX_EFFORT_CONTACT}",
                code="effort_tier_coming_soon",
            )
        resolved = self._resolve_agent_id(agent_id)
        if resolved and agent_name:
            return self._error(
                "agent_name cannot be combined with an agent_id (passed or configured). Use one identity mode.",
                code="invalid_identity",
            )
        prompt = (query or "").strip()
        if not prompt:
            return self._error("query is required")
        run_kwargs = self._run_options(
            agent_name=agent_name,
            use_case=use_case,
            skill=skill,
            input_data=input_data,
            output_schema=output_schema,
            sources=sources,
        )
        # Both routes return the same run envelope shape; _render_created reads it structurally.
        created: Any
        request_options: Dict[str, Any] = {
            "input": prompt,
            "enable_events": enable_events,
            **run_kwargs,
        }
        if self.effort is not None:
            request_options["effort"] = self.effort
        try:
            client = self._get_async_client()
            if resolved:
                created = await client.agents.runs.create(
                    resolved,
                    **request_options,
                )
            else:
                created = await client.agents.run(
                    **request_options,
                )
        except Exception as exc:
            log_error(f"Nimble astart_agent_run failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_created(created)

    async def aget_agent_run_status(self, run_id: str, agent_id: Optional[str] = None) -> str:
        """Async variant of get_agent_run_status."""
        if self.api_key is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        resolved = self._resolve_agent_id(agent_id)
        if not resolved:
            return self._error(
                "No Nimble agent configured. Pass agent_id or set NIMBLE_AGENT_ID.", code="no_agent_configured"
            )
        try:
            reader = self._get_async_client().with_options(max_retries=self.max_read_retries)
            run = await reader.agents.runs.get(run_id, agent_id=resolved)
        except Exception as exc:
            log_error(f"Nimble aget_agent_run_status failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_status(run)

    async def aget_agent_run_result(self, run_id: str, agent_id: Optional[str] = None) -> str:
        """Async variant of get_agent_run_result. Non-blocking."""
        if self.api_key is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        resolved = self._resolve_agent_id(agent_id)
        if not resolved:
            return self._error(
                "No Nimble agent configured. Pass agent_id or set NIMBLE_AGENT_ID.", code="no_agent_configured"
            )
        try:
            reader = self._get_async_client().with_options(max_retries=self.max_read_retries)
            run = await reader.agents.runs.get(run_id, agent_id=resolved)
            if run.status != "completed":
                return self._render_result_from_run(run, None)
            result = await reader.agents.runs.result(run_id, agent_id=resolved)
        except ConflictError:
            return json.dumps({"state": "not_ready", "run_id": run_id, "message": "Result not ready yet."}, indent=2)
        except Exception as exc:
            log_error(f"Nimble aget_agent_run_result failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_result_from_run(run, result)

    async def alist_agents(self, limit: int = 20) -> str:
        """Async variant of list_agents."""
        if self.api_key is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        try:
            reader = self._get_async_client().with_options(max_retries=self.max_read_retries)
            response = await reader.agents.list(limit=_bounded_limit(limit))
        except Exception as exc:
            log_error(f"Nimble alist_agents failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_agents(response)

    async def alist_agent_templates(self, limit: int = 20) -> str:
        """Async variant of list_agent_templates."""
        if self.api_key is None:
            return self._error("Nimble API key not configured. Set NIMBLE_API_KEY or pass api_key.")
        try:
            reader = self._get_async_client().with_options(max_retries=self.max_read_retries)
            response = await reader.agents.templates.list(limit=_bounded_limit(limit))
        except Exception as exc:
            log_error(f"Nimble alist_agent_templates failed: {type(exc).__name__}")
            return self._map_exception(exc)
        return self._render_templates(response)


def _retry_after_of(exc: Exception) -> Optional[str]:
    """Best-effort Retry-After header from an SDK error, for the caller to honor."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        return headers.get("retry-after")
    except Exception:
        return None
