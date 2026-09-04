"""Schemas related to the AgentOS configuration"""

from typing import Any, Callable, Dict, Generic, List, Literal, Optional, Set, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Tags carried by the built-in MCP tools, exposed here so callers (and the IDE) can see
# the valid values for ``MCPConfig.include_tags`` / ``exclude_tags`` without reading
# ``agno/os/mcp.py``. Keep in sync with the ``tags={...}`` argument on each
# ``@register_builtin_tool(...)`` in that module.
MCP_BUILTIN_TAGS: frozenset = frozenset({"core", "session", "lifecycle"})

# Type alias for ``include_tags`` / ``exclude_tags`` -- gives IDE autocomplete on the
# string values while keeping the API stringly-typed (callers still pass ``{"core"}``).
MCPBuiltinTag = Literal["core", "session", "lifecycle"]

# Where the MCP server publishes its Server Card: the MCP endpoint path plus ``/server-card``.
MCP_SERVER_CARD_PATH = "/mcp/server-card"


def _apply_legacy_enable_builtin_tools(data: Dict[str, Any]) -> Dict[str, Any]:
    """Map the deprecated ``enable_builtin_tools`` key onto ``default_tools`` in a dict
    copy (the caller's mapping is never mutated).
    """
    data = dict(data)
    legacy = data.pop("enable_builtin_tools")
    if "default_tools" in data and data["default_tools"] != legacy:
        raise ValueError(
            "MCPConfig got both default_tools and its deprecated alias enable_builtin_tools "
            f"with different values ({data['default_tools']!r} vs {legacy!r}); pass only default_tools."
        )
    data.setdefault("default_tools", legacy)
    return data


class MCPConfig(BaseModel):
    """Configuration for the AgentOS MCP server (served at ``/mcp``).

    Pass this as ``AgentOS(mcp=MCPConfig(...))`` to expose agents/teams/workflows as
    individual MCP tools, register your own tools, scope the default tools, gate the
    server, and add middleware. With plain ``mcp=True``, all default tools are
    registered and no extra gate or middleware is added.

    The default tools are tagged so they can be scoped as a group. See
    ``MCP_BUILTIN_TAGS`` for the canonical set; current values:
      - ``"core"``      -> ``get_agentos_config``, ``run_agent``, ``run_team``, ``run_workflow``,
        ``continue_run``, ``cancel_run``
      - ``"session"``   -> read-only session tools (``get_sessions``, ``get_session_runs``)
      - ``"lifecycle"`` -> ``continue_run``, ``cancel_run`` (dual-tagged with ``core``);
        registered automatically alongside exposed components -- see ``lifecycle_tools``

    The default surface is deliberately small (8 tools): it is an operator surface for
    LLM frontends, not a database console. Session writes and memory CRUD live on the
    REST surface; anything else can be registered as a custom tool via ``tools``.
    """

    # extra="forbid": a typo like ``tool=`` (for ``tools=``) must fail at construction,
    # not silently serve a different tool surface.
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    # Sent in the initialize response. ``name`` defaults to the AgentOS name and
    # ``version`` to ``AgentOS(version=...)``. ``instructions`` tells the calling
    # model what the tools are for and how to use them.
    name: Optional[str] = None
    version: Optional[str] = None
    instructions: Optional[str] = None

    # Publish a Server Card at ``/mcp/server-card`` (name, version, description, the endpoint
    # URL, and the served tools by name and description) and send a browser that opens ``/mcp``
    # to it. The card is public even when the server is gated; it carries nothing secret --
    # the tool names it lists are the same ones ``tools/list`` returns to any caller.
    server_card: bool = True

    # The public URL of the MCP endpoint, e.g. ``https://docs.agno.com/mcp``. Set this when the
    # deployment sits behind a proxy or load balancer: it is what the card advertises, verbatim.
    # Without it the card derives the URL from the request, and ``X-Forwarded-Host`` is honoured
    # only when that hostname is itself listed in ``allowed_hosts`` -- an unvalidated forwarded
    # host would otherwise be echoed into a publicly cacheable document.
    server_card_url: Optional[str] = None

    # The tool surface of this MCP server. Each entry may be:
    #
    #   - a plain callable or an Agno ``@tool``/``Function`` -- a custom tool
    #     (name/description inferred from the function or taken from the tool);
    #   - a ``Toolkit`` -- flattened into one MCP tool per method, the way an agent
    #     takes it apart. Narrow the published set with the toolkit's own
    #     ``include_tools``/``exclude_tools``; each flattened name goes through the
    #     same collision check as a hand-written custom tool. This server runs each call
    #     directly, so a toolkit's ``connect()``/``close()`` never fire: the shipped
    #     ``_requires_connect`` toolkits (``PostgresTools``, ``RedshiftTools``) connect
    #     themselves on use and are unaffected, but one whose state is keyed on the run
    #     (``CodeMode``, whose kernel is keyed by ``session_id``) gets a fresh identity
    #     every call and will not accumulate anything -- serve those over REST instead;
    #   - an ``Agent`` / ``Team`` / ``Workflow`` instance -- exposed as a tool named
    #     after its id, described by the component's own description;
    #   - ``component.as_tool(name=..., description=...)`` -- the same exposure with a
    #     model-facing name and description of your choosing, decoupled from the
    #     component (a tool description is a prompt for the CALLING model; the
    #     component's description is written for humans).
    #
    # Exposure rules (violations fail fast when the server is built):
    #   - every exposed component must be part of the AgentOS roster
    #   - tool names (the id, or the ``as_tool`` override) must start with a letter or
    #     underscore, then contain only letters/digits/hyphens/underscores, at most 128
    #     chars -- what OpenAI, Anthropic, and Gemini accept
    #   - names must not collide across default tools, custom tools, and exposures
    #
    # The tool list is fixed when the app is built: components added to a live
    # deployment (resync) are immediately runnable through the generic run tools where
    # those are served, but appear as named tools only after a restart (with
    # ``default_tools=False`` a post-boot component is unreachable over MCP until
    # then -- the riding lifecycle pair is bounded to the components published at
    # build time). Listing here is publishing: every
    # caller who can reach tools/list sees the names and descriptions (invocation is
    # still gated by scopes at call time). HITL works out of the box: whenever
    # components are exposed, ``continue_run`` and ``cancel_run`` register alongside
    # them (see ``lifecycle_tools``), and the exposed result's structuredContent
    # carries the component id a resume needs. Factories whose input_schema has
    # required fields cannot be invoked over MCP yet (true for run_agent too); invoke
    # those over REST.
    #
    # Identity: a custom tool may declare a ``user_id`` parameter. AgentOS fills it with
    # the authenticated caller's id (the JWT subject) and hides it from the client-facing
    # schema, so clients cannot spoof it. A parameter typed ``RunContext``, ``Agent`` or
    # ``Team`` is hidden and filled the same way, whatever it is called -- pydantic cannot
    # build a tool schema for those types, so a visible one would stop the server from
    # starting; the RunContext a tool receives carries the authenticated caller but no run
    # (an MCP call has none), and Agent/Team arrive as None. Media parameters stay visible:
    # nothing here has run media to inject. Tools that need the full request can declare a
    # FastMCP ``Context`` parameter, which FastMCP injects natively.
    #
    # An MCP call runs the tool directly, so the approval step a Function can declare
    # (``requires_confirmation``, ``requires_user_input``, ``external_execution``) would be
    # skipped. Such a tool is refused when the server is built rather than published
    # without its gate. The rest of ``FunctionCall``'s machinery is inert here for the same
    # reason and is NOT refused: tool hooks, pre/post hooks, and result caching
    # (``cache_results``) simply do not run on this surface.
    #
    # A tool returning an Agno ``ToolResult`` has it rendered as MCP content -- the answer
    # as text, images and audio as their own block types, videos and files as embedded
    # blob resources, and media the tool produced elsewhere as a resource link -- rather
    # than JSON-serialized, which loses the answer in a dump of the model and fails
    # outright on raw bytes.
    tools: Optional[List[Any]] = None

    # Master switch for the 8 default tools. Set to False to ship only your own
    # ``tools`` surface. ``enable_builtin_tools`` is the deprecated spelling, still
    # accepted at construction.
    default_tools: bool = True

    # Whether ``continue_run``/``cancel_run`` ride along whenever components are
    # exposed via ``tools`` -- even with ``default_tools=False``. Default True: an
    # exposed component can pause on a confirmation-required (HITL) tool, and without
    # continue_run the pause would be a dead end over MCP. The riding pair is bounded
    # to the publication list: when it registered only because exposures exist (not
    # via ``core`` or an explicit include), it refuses runs of unpublished roster
    # components, and it is scope-gated per component like the tool that produced the
    # run.
    lifecycle_tools: bool = True

    # Finer scoping over the default tools via their tags (see ``MCP_BUILTIN_TAGS``).
    # When ``include_tags`` is set, only default tools carrying one of those tags are
    # registered (name ``lifecycle`` explicitly to serve just the run-resumption pair).
    # ``exclude_tags`` is then subtracted. With ``default_tools=False`` there are no
    # default tools to scope, but ``exclude_tags={"lifecycle"}`` still disables the
    # exposure ride-along (see ``lifecycle_tools``).
    include_tags: Optional[Set[MCPBuiltinTag]] = None
    exclude_tags: Optional[Set[MCPBuiltinTag]] = None

    # How the run tools (run_agent / run_team / run_workflow and the exposed component
    # tools) serialize their results.
    #   "trimmed" (default) -> answer text + generated media as MCP content blocks;
    #     structuredContent carries run_id / session_id / status, the answer mirrored
    #     under "content", the owning component id (the continue_run handle), and the
    #     unresolved requirements when paused. MCP tool results land directly in the
    #     consuming model's context window, so the transcript, system prompt, and
    #     metrics are deliberately not included.
    #   "full" -> structuredContent is the run's complete ``to_dict()`` (media base64-
    #     encoded), for programmatic MCP clients that want the whole run.
    result_mode: Literal["trimmed", "full"] = "trimmed"

    # Per-call gate for the MCP server. Given the authenticated caller's user_id, return True
    # to allow the request and False to reject it with 401 -- before any tool or model runs.
    # Runs after JWT verification.
    #
    # ``user_id`` is the verified JWT subject when ``AgentOS(authorization=True, ...)`` is set,
    # and ``None`` otherwise -- including local dev where no JWT layer is configured. ``authorize``
    # is therefore the only thing standing between an unauthenticated caller and the MCP surface
    # in that mode; you MUST decide what ``None`` means for your app. Common choices: ``return
    # False`` (refuse anonymous), or ``return not is_prd()`` (allow only in dev). A bare
    # ``user_id in OWNER_IDS`` returns False on None, which is also fine. Pair this with
    # ``allowed_hosts`` to keep an always-on local server from being driven by a web page.
    #
    # Example: ``authorize=lambda user_id: user_id in OWNER_IDS`` for an owner-only server.
    authorize: Optional[Callable[[Optional[str]], bool]] = None

    # Built-in DNS-rebinding protection. When ``allowed_hosts`` is set (even to an empty list),
    # AgentOS validates the request Host -- and the Origin when one is present -- against these
    # values plus localhost defaults, rejecting anything else with 400. This is what an always-on
    # local MCP server needs so a malicious web page can't drive it via a rebound DNS name; you
    # list only your deploy/tunnel host, localhost works out of the box. Left as None (default),
    # no host validation is added -- unchanged behavior.
    allowed_hosts: Optional[List[str]] = None
    # Extra exact origins to allow (advanced). An Origin whose host is already in ``allowed_hosts``
    # (or a localhost default) is allowed without listing it here; use this only to allow an Origin
    # served from a different host.
    allowed_origins: Optional[List[str]] = None

    # Extra ASGI/Starlette middleware to add to the MCP app, for anything not covered above.
    # Provide ``starlette.middleware.Middleware`` instances; they run ahead of the JWT and
    # ``authorize`` layers, in the order listed.
    middleware: Optional[List[Any]] = None

    # Serve the MCP endpoint without session tracking: every request gets a fresh transport
    # and nothing is kept between requests. Lets any replica answer any request, so a
    # multi-instance deployment needs no session affinity. Costs the features that require a
    # retained session -- server-initiated notifications and SSE resumability -- so it stays
    # off by default.
    stateless: bool = False

    @model_validator(mode="before")
    @classmethod
    def _map_deprecated_enable_builtin_tools(cls, data: Any) -> Any:
        """Accept ``enable_builtin_tools`` as a deprecated alias for ``default_tools``.

        Silent by design: a working config must not warn.
        """
        import collections.abc

        # Mapping, not just dict: pydantic accepts any mapping (UserDict etc.), and a
        # missed match here would silently drop the key and serve all default tools.
        if isinstance(data, collections.abc.Mapping) and "enable_builtin_tools" in data:
            data = _apply_legacy_enable_builtin_tools(dict(data))
        return data

    @property
    def enable_builtin_tools(self) -> bool:
        """Deprecated alias for ``default_tools``."""
        return self.default_tools

    @enable_builtin_tools.setter
    def enable_builtin_tools(self, value: bool) -> None:
        # Pre-rename this was a plain field, so post-construction assignment worked;
        # the alias keeps that path working too.
        self.default_tools = bool(value)

    def model_copy(self, *, update: Optional[Dict[str, Any]] = None, deep: bool = False) -> "MCPConfig":
        # model_copy bypasses validators and writes ``update`` straight into the copy's
        # __dict__, where the class-level ``enable_builtin_tools`` property would shadow
        # the entry -- silently dropping the update (it was a real field pre-rename, so
        # ``model_copy(update={"enable_builtin_tools": False})`` used to work). Route the
        # legacy key through the same mapping the constructor uses.
        if update and "enable_builtin_tools" in update:
            update = _apply_legacy_enable_builtin_tools(update)
        return super().model_copy(update=update, deep=deep)

    @model_validator(mode="after")
    def _check_server_card_url(self) -> "MCPConfig":
        """Refuse a card URL that is not a well-formed absolute http(s) URL.

        The value is published verbatim as the endpoint clients connect to, so a relative path,
        a non-transport scheme, or a malformed host would produce a card that no client can use
        (and that the Server Card schema rejects). Fail at construction rather than at request
        time. Whitespace is rejected outright rather than left to the URL parser, which silently
        strips it -- this value lands in a publicly cacheable response, so a newline must never
        be quietly accepted and reshaped.
        """
        if self.server_card_url is None:
            return self

        from pydantic import AnyHttpUrl, TypeAdapter
        from pydantic import ValidationError as _ValidationError

        invalid = f"MCPConfig(server_card_url={self.server_card_url!r}) must be an absolute http(s) URL "
        if any(character.isspace() for character in self.server_card_url):
            raise ValueError(invalid + "with no whitespace, e.g. 'https://docs.agno.com/mcp'.")
        try:
            parsed = TypeAdapter(AnyHttpUrl).validate_python(self.server_card_url)
        except _ValidationError as exc:
            raise ValueError(invalid + "including the host, e.g. 'https://docs.agno.com/mcp'.") from exc
        if parsed.username or parsed.password:
            # The card is public and cacheable; anything in a userinfo segment would be published.
            raise ValueError(
                f"MCPConfig(server_card_url={self.server_card_url!r}) must not contain credentials: "
                "the Server Card is published publicly. Use 'https://docs.agno.com/mcp' and let "
                "clients authenticate with the Authorization header the card declares."
            )
        # Structure, not canonical form: the parser also normalises (``https:///mcp`` becomes host
        # ``mcp``), and the card publishes the original string, so the scheme and host it resolved
        # to must be the ones actually written. A default port or uppercase host is fine.
        if parsed.scheme not in ("http", "https"):
            raise ValueError(invalid + "including the host, e.g. 'https://docs.agno.com/mcp'.")
        written = self.server_card_url.split("//", 1)[-1].split("/", 1)[0].rsplit("@", 1)[-1]
        # Drop the port, but not the colons inside an ipv6 literal.
        written = written[: written.index("]") + 1] if written.startswith("[") else written.rsplit(":", 1)[0]
        if not parsed.host or parsed.host.strip("[]").lower() != written.strip("[]").lower():
            raise ValueError(invalid + "including the host, e.g. 'https://docs.agno.com/mcp'.")
        # The card's URL pattern matches lowercase ``http(s)://`` only, so a scheme written in any
        # other case is lowercased here rather than published as an invalid card.
        scheme_written = self.server_card_url.split("://", 1)[0]
        if scheme_written != scheme_written.lower():
            self.server_card_url = parsed.scheme + self.server_card_url[len(scheme_written) :]
        return self

    @model_validator(mode="after")
    def _check_has_tools(self) -> "MCPConfig":
        """Refuse a config that would mount an MCP server with zero tools.

        ``default_tools=False`` plus no ``tools`` is almost always a mistake -- the user
        disabled the default tools intending to ship their own surface and forgot to
        register it, and ends up with a working ``/mcp`` endpoint that lists nothing. Fail fast at construction with an actionable
        message instead of booting a useless server.

        The tags reach the same dead end without tripping that check: an explicitly empty
        ``include_tags``, or an ``exclude_tags`` covering every remaining tag, scopes out
        all the default tools while ``default_tools`` is still True. That case only
        warns -- see below.
        """
        if not self.default_tools and not self.tools:
            raise ValueError(
                "MCPConfig would register zero tools: default_tools=False and tools is empty. "
                "Pass tools=[...] -- components (chief), wrapped components "
                "(chief.as_tool(name=..., description=...)), and custom callables all go there -- "
                "or leave default_tools=True (the default) to ship the default tools."
            )

        # Warn rather than raise: unlike the branch above, this configuration is accepted
        # today and callers may be relying on it, so the surface stays exactly as it is.
        # Resolution mirrors ``_enabled_builtin_tags`` in ``agno/os/mcp.py``; it is inlined
        # here so this module keeps its typing+pydantic-only imports (``mcp.py`` pulls in
        # FastMCP, an optional extra).
        if self.default_tools and not self.tools:
            # ``lifecycle`` never enters the enabled set implicitly (the pair are core
            # tools; the tag exists for explicit include_tags and the exposure
            # ride-along, and there are no exposures on this branch).
            enabled = set(self.include_tags) if self.include_tags is not None else set(MCP_BUILTIN_TAGS) - {"lifecycle"}
            if self.exclude_tags:
                enabled -= set(self.exclude_tags)
            if not enabled:
                from agno.utils.log import log_warning

                log_warning(
                    "MCPConfig resolves to zero tools: include_tags/exclude_tags scope out every "
                    "default-tool tag and no custom tools were passed, so /mcp will list nothing. "
                    f"Default-tool tags are {sorted(MCP_BUILTIN_TAGS)}; got include_tags="
                    f"{sorted(self.include_tags) if self.include_tags is not None else None}, "
                    f"exclude_tags={sorted(self.exclude_tags) if self.exclude_tags else None}. "
                    "Pass tools=[...] if this is intentional."
                )
        return self


# Deprecated spelling, kept as a plain assignment so imports and isinstance checks keep
# working unchanged. The documented name is MCPConfig; removal targeted for 3.1.
MCPServerConfig = MCPConfig


class AuthorizationConfig(BaseModel):
    """Configuration for the JWT middleware"""

    verification_keys: Optional[List[str]] = None
    jwks_file: Optional[str] = None
    algorithm: Optional[str] = None
    verify_audience: Optional[bool] = None
    audience: Optional[str] = None
    admin_scope: Optional[str] = None
    # Additional fnmatch path patterns that bypass all AgentOS authentication,
    # merged with the default public-route exclusions.
    excluded_route_paths: Optional[List[str]] = None
    # Opt-in per-user data isolation. When True, AgentOS:
    #   - threads the JWT sub as ``user_id`` on every user-scoped DB read
    #     (sessions, memory, traces) for non-admin callers
    #   - coerces ``user_id`` on writes (sessions / memories / traces) so a
    #     non-admin caller cannot persist rows attributed to another user
    #   - enforces session/run ownership on cancel/resume/continue routes
    #   - requires session_id (and workflow_id on WS reconnect) for non-admins
    # When False (default) JWT/RBAC still apply, but routes operate on the
    # unscoped DB and don't add per-user ownership gates on top of RBAC.
    user_isolation: bool = False


class EvalsDomainConfig(BaseModel):
    """Configuration for the Evals domain of the AgentOS"""

    display_name: Optional[str] = None


class SessionDomainConfig(BaseModel):
    """Configuration for the Session domain of the AgentOS"""

    display_name: Optional[str] = None


class KnowledgeDomainConfig(BaseModel):
    """Configuration for the Knowledge domain of the AgentOS"""

    display_name: Optional[str] = None


class KnowledgeInstanceConfig(BaseModel):
    """Configuration for a single knowledge instance"""

    id: str
    name: str
    description: Optional[str] = None
    db_id: str
    table: str


class MetricsDomainConfig(BaseModel):
    """Configuration for the Metrics domain of the AgentOS"""

    display_name: Optional[str] = None


class MemoryDomainConfig(BaseModel):
    """Configuration for the Memory domain of the AgentOS"""

    display_name: Optional[str] = None


class LearningDomainConfig(BaseModel):
    """Configuration for the Learning domain of the AgentOS"""

    display_name: Optional[str] = None


class TracesDomainConfig(BaseModel):
    """Configuration for the Traces domain of the AgentOS"""

    display_name: Optional[str] = None


DomainConfigType = TypeVar("DomainConfigType")


class DatabaseConfig(BaseModel, Generic[DomainConfigType]):
    """Configuration for a domain when used with the contextual database"""

    db_id: str
    domain_config: Optional[DomainConfigType] = None
    tables: Optional[List[str]] = None


class EvalsConfig(EvalsDomainConfig):
    """Configuration for the Evals domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[EvalsDomainConfig]]] = None


class SessionConfig(SessionDomainConfig):
    """Configuration for the Session domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[SessionDomainConfig]]] = None


class MemoryConfig(MemoryDomainConfig):
    """Configuration for the Memory domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[MemoryDomainConfig]]] = None


class LearningConfig(LearningDomainConfig):
    """Configuration for the Learning domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[LearningDomainConfig]]] = None


class KnowledgeDatabaseConfig(BaseModel):
    """Configuration for a knowledge database with its tables"""

    db_id: str
    domain_config: Optional[KnowledgeDomainConfig] = None
    tables: List[str] = []


class KnowledgeConfig(KnowledgeDomainConfig):
    """Configuration for the Knowledge domain of the AgentOS"""

    dbs: Optional[List[KnowledgeDatabaseConfig]] = None
    knowledge_instances: Optional[List[KnowledgeInstanceConfig]] = None


class MetricsConfig(MetricsDomainConfig):
    """Configuration for the Metrics domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[MetricsDomainConfig]]] = None


class TracesConfig(TracesDomainConfig):
    """Configuration for the Traces domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[TracesDomainConfig]]] = None


class ChatConfig(BaseModel):
    """Configuration for the Chat page of the AgentOS"""

    quick_prompts: dict[str, list[str]]


class Manifest(BaseModel):
    """OS-level UI metadata for an agent/team/workflow.

    Fields here are AgentOS UI metadata only. ``description`` is unrelated to
    ``Agent.description`` / ``Team.description`` / ``Workflow.description``,
    which are sent to the model.

    Rendering surfaces:
    - ``description``, ``labels``: home/landing card
    - ``quick_prompts``: chat page
    """

    description: Optional[str] = None
    labels: Optional[List[str]] = None
    quick_prompts: Optional[List[str]] = None


class AgentOSConfig(BaseModel):
    """General configuration for an AgentOS instance"""

    available_models: Optional[List[str]] = None
    chat: Optional[ChatConfig] = None
    manifest: Optional[Dict[str, Manifest]] = Field(
        default=None,
        description="Per-entity UI metadata keyed by agent/team/workflow id",
    )
    evals: Optional[EvalsConfig] = None
    knowledge: Optional[KnowledgeConfig] = None
    memory: Optional[MemoryConfig] = None
    learning: Optional[LearningConfig] = None
    session: Optional[SessionConfig] = None
    metrics: Optional[MetricsConfig] = None
    traces: Optional[TracesConfig] = None
