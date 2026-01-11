from typing import Any, Dict, List, Optional, Union

from agno.filters import FilterExpr
from agno.utils.log import log_info


def get_agentic_or_user_search_filters(
    filters: Optional[Dict[str, Any]], effective_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]]
) -> Dict[str, Any]:
    """Helper function to determine the final filters to use for the search.

    Args:
        filters: Filters passed by the agent.
        effective_filters: Filters passed by user/team.

    Returns:
        Dict[str, Any]: The final filters to use for the search.

    Priority: user/team filters (effective_filters) > agent filters
    """
    search_filters = None

    # Priority: user/team filters take precedence over agent filters
    if effective_filters:
        if isinstance(effective_filters, dict):
            search_filters = effective_filters
        elif isinstance(effective_filters, list):
            # If effective_filters is a list (likely List[FilterExpr]), we can't use it directly as dict
            raise ValueError(
                "Merging dict and list of filters is not supported; effective_filters should be a dict for search compatibility."
            )
    elif filters:
        # Fall back to agent filters only if no user/team filters provided
        search_filters = filters

    log_info(f"Filters used by Agent: {search_filters}")
    return search_filters or {}
