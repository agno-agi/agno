from typing import Any, Dict, Optional

from agno.utils.log import log_info


def get_agentic_or_user_search_filters(
    filters: Optional[Dict[str, Any]], effective_filters: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Helper function to determine the final filters to use for the search.

    Args:
        filters: Filters passed by the agent.
        effective_filters: Filters passed by user.

    Returns:
        Dict[str, Any]: The final filters to use for the search.
    """
    search_filters = {}

    # If agentic filters exist and manual filters (passed by user) do not, use agentic filters
    if filters and not effective_filters:
        search_filters = filters

    # If both agentic filters exist and manual filters (passed by user) exist, use manual filters (give priority to user and override)
    if filters and effective_filters:
        search_filters = effective_filters

    log_info(f"Filters used by Agent: {search_filters}")
    return search_filters
