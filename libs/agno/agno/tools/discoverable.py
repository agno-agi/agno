import json
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Union

from agno.media import Audio, File, Image, Video
from agno.run import RunContext
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_warning


class DiscoverableTools(Toolkit):
    """Pool of tools withheld from the model's context until discovered via search.

    Registers a single ``search_tools`` meta-Function. When called, matching tools
    are appended to the live tools list and become callable as regular Functions
    on subsequent iterations of the model loop.

    Usage:
        discoverable = DiscoverableTools(tools=[tool_a, tool_b, ...])
        agent = Agent(tools=[always_visible_tool, discoverable])
    """

    def __init__(
        self,
        tools: List[Union[Toolkit, Callable, Function]],
        max_results: int = 5,
        search_tool_name: str = "search_tools",
    ):
        self._max_results = max_results
        self._search_tool_name = search_tool_name
        # Separate sync/async registries so Toolkits with dual implementations
        # dispatch the right variant based on the caller's run mode.
        self._sync_registry: Dict[str, Function] = {}
        self._async_registry: Dict[str, Function] = {}
        # Pre-tokenized haystacks for cheap repeated search (names shared across registries)
        self._haystack_tokens: Dict[str, Set[str]] = {}
        self._haystack_text: Dict[str, str] = {}
        self._active_names: Set[str] = set()
        self._tools_list_ref: Optional[List[Any]] = None
        self._agent: Optional[Any] = None
        self._team: Optional[Any] = None
        self._strict: bool = False
        self._tool_hooks: Optional[List[Callable]] = None
        self._run_context: Optional[RunContext] = None
        self._images: Optional[Sequence[Image]] = None
        self._files: Optional[Sequence[File]] = None
        self._audios: Optional[Sequence[Audio]] = None
        self._videos: Optional[Sequence[Video]] = None
        self._async_mode: bool = False

        self._build_registry(tools)

        search_fn = Function(
            name=self._search_tool_name,
            description=(
                "Search for additional tools by keyword query. "
                "Returns matching tool names + descriptions and makes them "
                "callable directly on subsequent turns. "
                f"Returns up to {self._max_results} tools per call."
            ),
            entrypoint=self._search,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords describing the tool capability you need.",
                    }
                },
                "required": ["query"],
            },
        )

        super().__init__(
            name="discoverable_tools",
            tools=[search_fn],
            instructions=self._build_instructions(),
            add_instructions=True,
        )

    @property
    def _registry(self) -> Dict[str, Function]:
        return self._async_registry if self._async_mode else self._sync_registry

    # ------------------------------------------------------------------ public
    def bind(
        self,
        tools_list: List[Any],
        agent: Optional[Any] = None,
        team: Optional[Any] = None,
        strict: bool = False,
        tool_hooks: Optional[List[Callable]] = None,
        run_context: Optional[RunContext] = None,
        images: Optional[Sequence[Image]] = None,
        files: Optional[Sequence[File]] = None,
        audios: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        async_mode: bool = False,
    ) -> None:
        """Wire DiscoverableTools to the live tools list + agent/team context."""
        self._tools_list_ref = tools_list
        self._agent = agent
        self._team = team
        self._strict = strict
        self._tool_hooks = tool_hooks
        self._run_context = run_context
        self._images = images
        self._files = files
        self._audios = audios
        self._videos = videos
        self._async_mode = async_mode
        # Defensive: ensure a fresh run never inherits previous activations
        self._active_names.clear()

    # ----------------------------------------------------------------- private
    def _build_instructions(self) -> str:
        count = len(self._sync_registry) or len(self._async_registry)
        if not count:
            return ""
        return (
            f"You have access to {count} additional tools not shown by default. "
            f"Use `{self._search_tool_name}(query)` to find relevant ones by keyword. "
            "Discovered tools become directly callable on the next turn — do not wrap them."
        )

    def _hydrate(self, func: Function) -> None:
        """Populate Function.description from the entrypoint docstring when empty.

        Agno's Agent._process_tools normally fills this during agent setup, but
        _build_registry runs earlier — before agent build — so we extract the
        docstring ourselves. Description is everything before 'Args:' (Agno's
        convention; matches Function.process_entrypoint's split).
        """
        if (func.description or "").strip():
            return
        doc = getattr(func.entrypoint, "__doc__", "") or ""
        func.description = doc.split("Args:")[0].strip()

    def _build_registry(self, tools: List[Union[Toolkit, Callable, Function]]) -> None:
        for tool in tools:
            if isinstance(tool, Toolkit):
                sync_fns = tool.get_functions()
                async_fns = tool.get_async_functions()
                for name, func in sync_fns.items():
                    self._hydrate(func)
                    self._register_sync(name, func)
                for name, func in async_fns.items():
                    self._hydrate(func)
                    self._register_async(name, func)
            elif isinstance(tool, Function):
                self._hydrate(tool)
                self._register_both(tool.name, tool)
            elif callable(tool):
                func = Function.from_callable(tool)
                # Preserve @approval decorator metadata on raw callables
                approval_type = getattr(tool, "_agno_approval_type", None)
                if approval_type is not None:
                    func.approval_type = approval_type
                    has_hitl = any(
                        [
                            func.requires_user_input,
                            func.requires_confirmation,
                            func.external_execution,
                        ]
                    )
                    if approval_type == "required" and not has_hitl:
                        func.requires_confirmation = True
                    elif approval_type == "audit" and not has_hitl:
                        raise ValueError(
                            "@approval(type='audit') requires at least one HITL flag "
                            "('requires_confirmation', 'requires_user_input', or 'external_execution') "
                            "to be set on @tool()."
                        )
                self._hydrate(func)
                self._register_both(func.name, func)
            else:
                log_warning(
                    f"DiscoverableTools: unsupported tool type {type(tool).__name__}"
                )

    def _register_sync(self, name: str, func: Function) -> None:
        self._sync_registry[name] = func
        self._index_haystack(name, func)

    def _register_async(self, name: str, func: Function) -> None:
        self._async_registry[name] = func
        self._index_haystack(name, func)

    def _register_both(self, name: str, func: Function) -> None:
        self._register_sync(name, func)
        self._register_async(name, func)

    def _index_haystack(self, name: str, func: Function) -> None:
        if name in self._haystack_tokens:
            return
        haystack = f"{name.replace('_', ' ')} {func.description or ''}".lower()
        self._haystack_text[name] = haystack
        self._haystack_tokens[name] = set(haystack.split())

    def _search(self, query: str) -> str:
        query_tokens = {t for t in query.lower().split() if t}
        scored: List[tuple] = []
        for name in self._registry:
            if name in self._active_names:
                continue
            score = len(query_tokens & self._haystack_tokens[name])
            if score == 0:
                # fallback: substring match on any token
                if any(qt in self._haystack_text[name] for qt in query_tokens):
                    score = 1
            if score > 0:
                scored.append((score, name))
        scored.sort(key=lambda x: -x[0])
        top = scored[: self._max_results]

        discovered = []
        for _, name in top:
            self._active_names.add(name)
            self._inject(self._registry[name])
            discovered.append(
                {"name": name, "description": self._registry[name].description or ""}
            )

        return json.dumps(
            {
                "discovered_tools": discovered,
                "remaining": len(self._registry) - len(self._active_names),
            }
        )

    def _inject(self, func: Function) -> None:
        if self._tools_list_ref is None:
            log_warning("DiscoverableTools: tools list not bound; cannot inject")
            return
        # Prevent name collisions with already-visible tools or prior injections
        existing_names = {
            t.name for t in self._tools_list_ref if isinstance(t, Function)
        }
        if func.name in existing_names:
            log_debug(
                f"DiscoverableTools: skipping {func.name} (name already in tools list)"
            )
            return
        copied = func.model_copy(deep=True)
        copied._agent = self._agent
        copied._team = self._team
        effective_strict = self._strict if copied.strict is None else copied.strict
        copied.process_entrypoint(strict=effective_strict)
        if self._strict and copied.strict is None:
            copied.strict = True
        if self._tool_hooks is not None:
            copied.tool_hooks = self._tool_hooks
        # Wire run context + media so the discovered tool sees the same state as
        # tools that went through determine_tools_for_model upfront
        copied._run_context = self._run_context
        copied._images = self._images
        copied._files = self._files
        copied._audios = self._audios
        copied._videos = self._videos
        self._tools_list_ref.append(copied)
        log_debug(f"DiscoverableTools: injected {copied.name}")
