from typing import Any, Dict, List, Optional, Union

from agno.filters import FilterExpr
from agno.utils.log import log_info


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


def accepts_user_id(retrieve_fn: Any) -> bool:
    """Whether ``retrieve_fn`` can receive the per-user isolation owner.

    True when the callable declares a literal ``user_id`` parameter OR accepts
    ``**kwargs``. The ``**kwargs`` case matters: ``KnowledgeProtocol`` documents
    retrieval as ``retrieve(self, query, **kwargs)``, so a protocol-conforming
    implementation never names ``user_id`` explicitly. Probing for the literal
    name alone would drop the owner for every such class, and because ``None``
    means "no owner filter" (the admin view), the drop is silent - retrieval
    widens to every owner's chunks instead of raising.

    Falls back to False when the signature can't be inspected (builtins and
    C-extensions raise here), which keeps the legacy no-``user_id`` contract
    working rather than crashing on an unexpected kwarg.
    """
    from inspect import Parameter, signature

    try:
        params = signature(retrieve_fn).parameters
    except (TypeError, ValueError):
        return False
    if "user_id" in params:
        return True
    return any(p.kind == Parameter.VAR_KEYWORD for p in params.values())
