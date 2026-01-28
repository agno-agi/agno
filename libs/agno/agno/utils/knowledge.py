from typing import Any, Dict, List, Optional, Union

from agno.filters import FilterExpr
from agno.utils.log import log_info


def convert_agentic_filters_to_dict(filters: List[Any]) -> Dict[str, Any]:
    """Helper function to convert a list of agentic filters to a dictionary.

    Args:
        filters: List of filter objects from the agent.

    Returns:
        Dict[str, Any]: Merged dictionary of all filters.
    """
    result: Dict[str, Any] = {}
    for filt in filters:
        if isinstance(filt, dict):
            result.update(filt)
        elif hasattr(filt, "key") and hasattr(filt, "value"):
            result[filt.key] = filt.value
    return result


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
