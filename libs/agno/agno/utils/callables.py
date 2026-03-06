"""Callable factory resolution utilities for Agent and Team.

Provides shared logic for resolving callable factories for tools, knowledge,
and members at runtime, with caching support.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
)

if TYPE_CHECKING:
    from agno.run import RunContext

from agno.utils.log import log_debug, log_warning


def _get_or_create_cache(entity: Any, attr: str) -> Dict[str, Any]:
    """Get or create a cache dict on the entity, ensuring it persists across calls."""
    cache = getattr(entity, attr, None)
    if cache is None:
        cache = {}
        try:
            object.__setattr__(entity, attr, cache)
        except (AttributeError, TypeError):
            pass  # Entity doesn't support attribute setting; cache will be per-call
    return cache


def is_callable_factory(value: Any, excluded_types: Tuple[type, ...] = ()) -> bool:
    """Check if a value is a callable factory (not a tool/knowledge instance).

    Args:
        value: The value to check.
        excluded_types: Types that are callable but should NOT be treated as factories.

    Returns:
        True if value is a callable factory.
    """
    if not callable(value):
        return False
    if isinstance(value, excluded_types):
        return False
    # Classes themselves are callable but shouldn't be treated as factories
    if isinstance(value, type):
        return False
    return True


def invoke_callable_factory(
    factory: Callable,
    entity: Any,
    run_context: "RunContext",
) -> Any:
    """Invoke a callable factory with signature-based parameter injection (sync).

    Inspects the factory's signature and injects matching parameters:
    - agent/team: the entity (Agent or Team)
    - run_context: the current RunContext
    - session_state: the current session state dict

    Raises RuntimeError if the factory is async (use ainvoke_callable_factory instead).
    """
    if asyncio.iscoroutinefunction(factory):
        raise RuntimeError(
            f"Async callable factory {factory!r} cannot be used in sync mode. Use arun() or aprint_response() instead."
        )

    sig = inspect.signature(factory)
    kwargs: Dict[str, Any] = {}

    if "agent" in sig.parameters:
        kwargs["agent"] = entity
    if "team" in sig.parameters:
        kwargs["team"] = entity
    if "run_context" in sig.parameters:
        kwargs["run_context"] = run_context
    if "session_state" in sig.parameters:
        kwargs["session_state"] = run_context.session_state if run_context.session_state is not None else {}

    result = factory(**kwargs)

    if asyncio.isfuture(result) or asyncio.iscoroutine(result):
        # Cleanup the coroutine to prevent warnings
        if asyncio.iscoroutine(result):
            result.close()
        raise RuntimeError(
            f"Callable factory {factory!r} returned an awaitable in sync mode. Use arun() or aprint_response() instead."
        )

    return result


async def ainvoke_callable_factory(
    factory: Callable,
    entity: Any,
    run_context: "RunContext",
) -> Any:
    """Invoke a callable factory with signature-based parameter injection (async).

    Supports both sync and async factories. Async results are awaited automatically.
    """
    sig = inspect.signature(factory)
    kwargs: Dict[str, Any] = {}

    if "agent" in sig.parameters:
        kwargs["agent"] = entity
    if "team" in sig.parameters:
        kwargs["team"] = entity
    if "run_context" in sig.parameters:
        kwargs["run_context"] = run_context
    if "session_state" in sig.parameters:
        kwargs["session_state"] = run_context.session_state if run_context.session_state is not None else {}

    result = factory(**kwargs)

    if asyncio.iscoroutine(result):
        result = await result

    return result


def _compute_cache_key(
    entity: Any,
    run_context: "RunContext",
    custom_key_fn: Optional[Callable] = None,
) -> Optional[str]:
    """Compute cache key for a callable factory (sync).

    Priority: custom_key_fn > user_id > session_id > None (skip caching).

    Raises RuntimeError if custom_key_fn is async.
    """
    if custom_key_fn is not None:
        if asyncio.iscoroutinefunction(custom_key_fn):
            raise RuntimeError(
                f"Async cache key function {custom_key_fn!r} cannot be used in sync mode. "
                "Use arun() or aprint_response() instead."
            )

        sig = inspect.signature(custom_key_fn)
        kwargs: Dict[str, Any] = {}
        if "run_context" in sig.parameters:
            kwargs["run_context"] = run_context
        if "agent" in sig.parameters:
            kwargs["agent"] = entity
        if "team" in sig.parameters:
            kwargs["team"] = entity

        result = custom_key_fn(**kwargs)
        if asyncio.iscoroutine(result):
            result.close()
            raise RuntimeError(
                f"Cache key function {custom_key_fn!r} returned an awaitable in sync mode. "
                "Use arun() or aprint_response() instead."
            )
        return result

    if run_context.user_id is not None:
        return run_context.user_id
    if run_context.session_id is not None:
        return run_context.session_id
    return None


async def _acompute_cache_key(
    entity: Any,
    run_context: "RunContext",
    custom_key_fn: Optional[Callable] = None,
) -> Optional[str]:
    """Compute cache key for a callable factory (async).

    Supports both sync and async custom key functions.
    Priority: custom_key_fn > user_id > session_id > None (skip caching).
    """
    if custom_key_fn is not None:
        sig = inspect.signature(custom_key_fn)
        kwargs: Dict[str, Any] = {}
        if "run_context" in sig.parameters:
            kwargs["run_context"] = run_context
        if "agent" in sig.parameters:
            kwargs["agent"] = entity
        if "team" in sig.parameters:
            kwargs["team"] = entity

        result = custom_key_fn(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    if run_context.user_id is not None:
        return run_context.user_id
    if run_context.session_id is not None:
        return run_context.session_id
    return None


# ---------------------------------------------------------------------------
# Tools resolution
# ---------------------------------------------------------------------------


def resolve_callable_tools(entity: Any, run_context: "RunContext") -> None:
    """Resolve callable tools factory and populate run_context.tools (sync)."""
    from agno.tools import Toolkit
    from agno.tools.function import Function

    if not is_callable_factory(entity.tools, excluded_types=(Toolkit, Function)):
        return

    custom_key_fn = getattr(entity, "callable_tools_cache_key", None)
    cache_enabled = getattr(entity, "cache_callables", True)
    cache = _get_or_create_cache(entity, "_callable_tools_cache")

    cache_key = _compute_cache_key(entity, run_context, custom_key_fn)

    # Check cache
    if cache_enabled and cache_key is not None and cache_key in cache:
        log_debug(f"Using cached tools for key: {cache_key}")
        run_context.tools = cache[cache_key]
        return

    # Invoke factory
    result = invoke_callable_factory(entity.tools, entity, run_context)

    if result is None:
        result = []
    elif not isinstance(result, (list, tuple)):
        raise TypeError(f"Callable tools factory must return a list or tuple, got {type(result).__name__}")
    else:
        result = list(result)

    # Store in cache
    if cache_enabled and cache_key is not None:
        cache[cache_key] = result
        log_debug(f"Cached tools for key: {cache_key}")

    run_context.tools = result


async def aresolve_callable_tools(entity: Any, run_context: "RunContext") -> None:
    """Resolve callable tools factory and populate run_context.tools (async)."""
    from agno.tools import Toolkit
    from agno.tools.function import Function

    if not is_callable_factory(entity.tools, excluded_types=(Toolkit, Function)):
        return

    custom_key_fn = getattr(entity, "callable_tools_cache_key", None)
    cache_enabled = getattr(entity, "cache_callables", True)
    cache = _get_or_create_cache(entity, "_callable_tools_cache")

    cache_key = await _acompute_cache_key(entity, run_context, custom_key_fn)

    # Check cache
    if cache_enabled and cache_key is not None and cache_key in cache:
        log_debug(f"Using cached tools for key: {cache_key}")
        run_context.tools = cache[cache_key]
        return

    # Invoke factory
    result = await ainvoke_callable_factory(entity.tools, entity, run_context)

    if result is None:
        result = []
    elif not isinstance(result, (list, tuple)):
        raise TypeError(f"Callable tools factory must return a list or tuple, got {type(result).__name__}")
    else:
        result = list(result)

    # Store in cache
    if cache_enabled and cache_key is not None:
        cache[cache_key] = result
        log_debug(f"Cached tools for key: {cache_key}")

    run_context.tools = result


# ---------------------------------------------------------------------------
# Knowledge resolution
# ---------------------------------------------------------------------------


def resolve_callable_knowledge(entity: Any, run_context: "RunContext") -> None:
    """Resolve callable knowledge factory and populate run_context.knowledge (sync)."""
    from agno.knowledge.protocol import KnowledgeProtocol

    knowledge = entity.knowledge
    if not is_callable_factory(knowledge, excluded_types=(KnowledgeProtocol,)):
        return

    custom_key_fn = getattr(entity, "callable_knowledge_cache_key", None)
    cache_enabled = getattr(entity, "cache_callables", True)
    cache = _get_or_create_cache(entity, "_callable_knowledge_cache")

    cache_key = _compute_cache_key(entity, run_context, custom_key_fn)

    # Check cache
    if cache_enabled and cache_key is not None and cache_key in cache:
        log_debug(f"Using cached knowledge for key: {cache_key}")
        run_context.knowledge = cache[cache_key]
        return

    # Invoke factory
    result = invoke_callable_factory(knowledge, entity, run_context)

    if result is not None:
        # Validate that the result satisfies KnowledgeProtocol
        if not isinstance(result, KnowledgeProtocol):
            raise TypeError(
                f"Callable knowledge factory must return a KnowledgeProtocol instance, got {type(result).__name__}"
            )

    # Store in cache
    if cache_enabled and cache_key is not None and result is not None:
        cache[cache_key] = result
        log_debug(f"Cached knowledge for key: {cache_key}")

    run_context.knowledge = result


async def aresolve_callable_knowledge(entity: Any, run_context: "RunContext") -> None:
    """Resolve callable knowledge factory and populate run_context.knowledge (async)."""
    from agno.knowledge.protocol import KnowledgeProtocol

    knowledge = entity.knowledge
    if not is_callable_factory(knowledge, excluded_types=(KnowledgeProtocol,)):
        return

    custom_key_fn = getattr(entity, "callable_knowledge_cache_key", None)
    cache_enabled = getattr(entity, "cache_callables", True)
    cache = _get_or_create_cache(entity, "_callable_knowledge_cache")

    cache_key = await _acompute_cache_key(entity, run_context, custom_key_fn)

    # Check cache
    if cache_enabled and cache_key is not None and cache_key in cache:
        log_debug(f"Using cached knowledge for key: {cache_key}")
        run_context.knowledge = cache[cache_key]
        return

    # Invoke factory
    result = await ainvoke_callable_factory(knowledge, entity, run_context)

    if result is not None:
        if not isinstance(result, KnowledgeProtocol):
            raise TypeError(
                f"Callable knowledge factory must return a KnowledgeProtocol instance, got {type(result).__name__}"
            )

    # Store in cache
    if cache_enabled and cache_key is not None and result is not None:
        cache[cache_key] = result
        log_debug(f"Cached knowledge for key: {cache_key}")

    run_context.knowledge = result


# ---------------------------------------------------------------------------
# Members resolution (Team only)
# ---------------------------------------------------------------------------


def resolve_callable_members(entity: Any, run_context: "RunContext") -> None:
    """Resolve callable members factory and populate run_context.members (sync)."""
    members = getattr(entity, "members", None)
    if not is_callable_factory(members):
        return
    assert callable(members)

    custom_key_fn = getattr(entity, "callable_members_cache_key", None)
    cache_enabled = getattr(entity, "cache_callables", True)
    cache = _get_or_create_cache(entity, "_callable_members_cache")

    cache_key = _compute_cache_key(entity, run_context, custom_key_fn)

    # Check cache
    if cache_enabled and cache_key is not None and cache_key in cache:
        log_debug(f"Using cached members for key: {cache_key}")
        run_context.members = cache[cache_key]
        return

    # Invoke factory
    result = invoke_callable_factory(members, entity, run_context)

    if result is None:
        result = []
    elif not isinstance(result, (list, tuple)):
        raise TypeError(f"Callable members factory must return a list or tuple, got {type(result).__name__}")
    else:
        result = list(result)

    # Store in cache
    if cache_enabled and cache_key is not None:
        cache[cache_key] = result
        log_debug(f"Cached members for key: {cache_key}")

    run_context.members = result


async def aresolve_callable_members(entity: Any, run_context: "RunContext") -> None:
    """Resolve callable members factory and populate run_context.members (async)."""
    members = getattr(entity, "members", None)
    if not is_callable_factory(members):
        return
    assert callable(members)

    custom_key_fn = getattr(entity, "callable_members_cache_key", None)
    cache_enabled = getattr(entity, "cache_callables", True)
    cache = _get_or_create_cache(entity, "_callable_members_cache")

    cache_key = await _acompute_cache_key(entity, run_context, custom_key_fn)

    # Check cache
    if cache_enabled and cache_key is not None and cache_key in cache:
        log_debug(f"Using cached members for key: {cache_key}")
        run_context.members = cache[cache_key]
        return

    # Invoke factory
    result = await ainvoke_callable_factory(members, entity, run_context)

    if result is None:
        result = []
    elif not isinstance(result, (list, tuple)):
        raise TypeError(f"Callable members factory must return a list or tuple, got {type(result).__name__}")
    else:
        result = list(result)

    # Store in cache
    if cache_enabled and cache_key is not None:
        cache[cache_key] = result
        log_debug(f"Cached members for key: {cache_key}")

    run_context.members = result


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


def clear_callable_cache(
    entity: Any,
    kind: Optional[Literal["tools", "knowledge", "members"]] = None,
    close: bool = False,
) -> None:
    """Clear callable factory caches (sync).

    Args:
        entity: The Agent or Team whose caches to clear.
        kind: Which cache to clear. None clears all.
        close: If True, call .close() on cached tools before clearing.
    """
    caches_to_clear: List[str] = []
    if kind is None:
        caches_to_clear = ["_callable_tools_cache", "_callable_knowledge_cache", "_callable_members_cache"]
    elif kind == "tools":
        caches_to_clear = ["_callable_tools_cache"]
    elif kind == "knowledge":
        caches_to_clear = ["_callable_knowledge_cache"]
    elif kind == "members":
        caches_to_clear = ["_callable_members_cache"]
    else:
        raise ValueError(f"Invalid kind: {kind!r}. Expected 'tools', 'knowledge', 'members', or None.")

    if close:
        _close_cached_resources_sync(entity, caches_to_clear)

    for cache_name in caches_to_clear:
        cache = getattr(entity, cache_name, None)
        if cache is not None:
            cache.clear()


async def aclear_callable_cache(
    entity: Any,
    kind: Optional[Literal["tools", "knowledge", "members"]] = None,
    close: bool = False,
) -> None:
    """Clear callable factory caches (async).

    Args:
        entity: The Agent or Team whose caches to clear.
        kind: Which cache to clear. None clears all.
        close: If True, call .aclose()/.close() on cached tools before clearing.
    """
    caches_to_clear: List[str] = []
    if kind is None:
        caches_to_clear = ["_callable_tools_cache", "_callable_knowledge_cache", "_callable_members_cache"]
    elif kind == "tools":
        caches_to_clear = ["_callable_tools_cache"]
    elif kind == "knowledge":
        caches_to_clear = ["_callable_knowledge_cache"]
    elif kind == "members":
        caches_to_clear = ["_callable_members_cache"]
    else:
        raise ValueError(f"Invalid kind: {kind!r}. Expected 'tools', 'knowledge', 'members', or None.")

    if close:
        await _aclose_cached_resources(entity, caches_to_clear)

    for cache_name in caches_to_clear:
        cache = getattr(entity, cache_name, None)
        if cache is not None:
            cache.clear()


def _close_cached_resources_sync(entity: Any, cache_names: List[str]) -> None:
    """Close cached resources, deduplicating by identity."""
    seen_ids: set = set()

    for cache_name in cache_names:
        cache = getattr(entity, cache_name, None)
        if not cache:
            continue

        for cached_value in cache.values():
            items = cached_value if isinstance(cached_value, (list, tuple)) else [cached_value]
            for item in items:
                item_id = id(item)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                close_fn = getattr(item, "close", None)
                if close_fn is not None and callable(close_fn):
                    result = close_fn()
                    if asyncio.iscoroutine(result):
                        result.close()  # Prevent RuntimeWarning
                        log_warning(
                            f"Sync close() on {item!r} returned a coroutine. "
                            "Use aclear_callable_cache() for async cleanup."
                        )


async def _aclose_cached_resources(entity: Any, cache_names: List[str]) -> None:
    """Close cached resources async, deduplicating by identity. Prefers aclose() over close()."""
    seen_ids: set = set()

    for cache_name in cache_names:
        cache = getattr(entity, cache_name, None)
        if not cache:
            continue

        for cached_value in cache.values():
            items = cached_value if isinstance(cached_value, (list, tuple)) else [cached_value]
            for item in items:
                item_id = id(item)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                aclose_fn = getattr(item, "aclose", None)
                if aclose_fn is not None and callable(aclose_fn):
                    result = aclose_fn()
                    if asyncio.iscoroutine(result):
                        await result
                    continue

                close_fn = getattr(item, "close", None)
                if close_fn is not None and callable(close_fn):
                    result = close_fn()
                    if asyncio.iscoroutine(result):
                        await result


# ---------------------------------------------------------------------------
# Helper to get resolved resource, falling back to static
# ---------------------------------------------------------------------------


def get_resolved_knowledge(entity: Any, run_context: Optional["RunContext"] = None) -> Any:
    """Get the resolved knowledge: run_context.knowledge > entity.knowledge (if static)."""
    from agno.knowledge.protocol import KnowledgeProtocol

    if run_context is not None and run_context.knowledge is not None:
        return run_context.knowledge
    knowledge = getattr(entity, "knowledge", None)
    if knowledge is not None and not is_callable_factory(knowledge, excluded_types=(KnowledgeProtocol,)):
        return knowledge
    return None


def get_resolved_tools(entity: Any, run_context: Optional["RunContext"] = None) -> Optional[list]:
    """Get the resolved tools: run_context.tools > entity.tools (if list)."""
    if run_context is not None and run_context.tools is not None:
        return run_context.tools
    tools = getattr(entity, "tools", None)
    if tools is not None and isinstance(tools, list):
        return tools
    return None


def get_resolved_members(entity: Any, run_context: Optional["RunContext"] = None) -> Optional[list]:
    """Get the resolved members: run_context.members > entity.members (if list)."""
    if run_context is not None and run_context.members is not None:
        return run_context.members
    members = getattr(entity, "members", None)
    if members is not None and isinstance(members, list):
        return members
    return None
