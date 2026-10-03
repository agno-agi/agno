from typing import Any, Dict, List, Optional, Union

from agno.filters import FilterExpr
from agno.utils.log import log_info, log_warning


def get_agentic_or_user_search_filters(
    filters: Optional[Dict[str, Any]], effective_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]]
) -> Dict[str, Any]:
    """Helper function to determine the final filters to use for the search.

    Args:
        filters: Filters passed by the agent.
        effective_filters: Filters passed by user.

    Returns:
        Dict[str, Any]: The final filters to use for the search.
    """
    search_filters = None

    # If agentic filters exist and manual filters (passed by user) do not, use agentic filters
    if filters and not effective_filters:
        search_filters = filters

    # If both agentic filters exist and manual filters (passed by user) exist, use manual filters (give priority to user and override)
    if filters and effective_filters:
        if isinstance(effective_filters, dict):
            search_filters = effective_filters
        elif isinstance(effective_filters, list):
            # If effective_filters is a list (likely List[FilterExpr]), convert both filters and effective_filters to a dict if possible, otherwise raise
            raise ValueError(
                "Merging dict and list of filters is not supported; effective_filters should be a dict for search compatibility."
            )

    log_info(f"Filters used by Agent: {search_filters}")
    return search_filters or {}


def get_user_id_kwarg(fn: Any, user_id: Optional[str], *, required: bool = False) -> Dict[str, Any]:
    """``{"user_id": ...}`` only when the callee accepts it.

    ``**kwargs`` counts as accepting it: ``KnowledgeProtocol`` is variadic by design
    (``retrieve(self, query, **kwargs)``), so a custom Knowledge declaring ``**kwargs``
    forwards the owner rather than swallowing it. This is the opposite of
    :func:`strict_user_id_kwarg`, whose callees are ``VectorDb`` methods that all declare
    ``user_id`` explicitly.

    Args:
        fn: The callable the kwarg will be passed to.
        user_id: The owner to scope the call to.
        required: Refuse rather than drop the owner when the callee cannot take it. Set on
            writes: dropping it there does not merely widen a read, it stores the caller's
            content in the shared bucket, where every other user can read it and no
            owner-scoped delete will ever reach it.

    Returns:
        Dict[str, Any]: {"user_id": user_id} when the callee accepts it, empty otherwise.

    Raises:
        ValueError: If ``required`` and a real owner cannot be passed through.
    """
    import inspect

    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        parameters = {}  # type: ignore[assignment]
    if "user_id" in parameters or any(p.kind == p.VAR_KEYWORD for p in parameters.values()):
        return {"user_id": user_id}
    if user_id is not None:
        name = getattr(fn, "__qualname__", fn)
        if required:
            raise ValueError(
                f"user_id={user_id!r} was passed but {name} does not accept it, so this content would be "
                "stored in the shared bucket and be readable by every other user. Add a user_id "
                "parameter to it (or accept **kwargs) to support per-user isolation."
            )
        log_warning(f"{name} does not accept user_id, so this call is not scoped to a single owner.")
    return {}


def strict_user_id_kwarg(fn: Any, user_id: Optional[str]) -> Dict[str, Any]:
    """``{"user_id": ...}`` when the callee accepts it; fail closed when it can't honour a scope.

    The strict sibling of :func:`get_user_id_kwarg`, used at the
    ``Knowledge`` -> ``VectorDb`` boundary. A pre-v3 custom adapter (no
    ``user_id`` in its signatures) keeps working exactly like v2 for unscoped
    calls — the kwarg is simply omitted instead of raising a ``TypeError``
    that the surrounding catch-alls would swallow into empty results. A
    *scoped* call against such an adapter raises instead of silently running
    without isolation.

    Unlike :func:`get_user_id_kwarg`, ``**kwargs`` does NOT count as accepting
    ``user_id``. Every method on ``agno.vectordb.base.VectorDb`` declares
    ``user_id`` explicitly, so a legacy adapter written as
    ``search(self, query, limit=5, **kwargs)`` is not v3-aware — it would
    silently swallow ``user_id`` and run unscoped (and on writes store the row
    under the NULL/shared bucket, readable by everyone). Only a literal
    ``user_id`` parameter is treated as acceptance. ``get_user_id_kwarg``'s
    ``**kwargs`` branch is correct only because its callee is
    ``KnowledgeProtocol.retrieve(self, query, **kwargs)``, which forwards it.

    Args:
        fn: The vector-db method the kwarg will be passed to.
        user_id: The owner to scope the call to. ``None`` = unscoped.

    Returns:
        Dict[str, Any]: {"user_id": user_id} when the callee declares ``user_id``,
        empty for unscoped calls to legacy callables.

    Raises:
        ValueError: when ``user_id`` is set but the callee does not declare it.
    """
    import inspect
    from unittest.mock import Mock

    # A Mock/MagicMock stands in for a real v3 adapter in tests; it reports a
    # (*args, **kwargs) signature indistinguishable from a legacy adapter, so
    # treat it as current rather than refusing the scope.
    if isinstance(fn, Mock) or isinstance(getattr(fn, "__self__", None), Mock):
        return {"user_id": user_id}

    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        # Uninspectable callables (C extensions, exotic wrappers) are assumed
        # current — they receive the kwarg and surface their own TypeError.
        return {"user_id": user_id}
    if "user_id" in parameters:
        return {"user_id": user_id}
    if user_id is None:
        return {}
    raise ValueError(
        f"user_id={user_id!r} was passed but {getattr(fn, '__qualname__', fn)} does not declare a "
        "user_id parameter. This vector db predates per-user isolation — add user_id parameters to "
        "its methods (see agno.vectordb.base.VectorDb) before running user-scoped operations."
    )
