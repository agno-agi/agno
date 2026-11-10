"""Utility functions for the in-memory database class."""

from typing import Any, Dict, List, Optional

from agno.db.utils import get_sort_value
from agno.utils.log import log_debug


def apply_sorting(
    data: List[Dict[str, Any]], sort_by: Optional[str] = None, sort_order: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Apply sorting to the given data list.

    Args:
        data: The list of dictionaries to sort
        sort_by: The field to sort by
        sort_order: The sort order ('asc' or 'desc')

    Returns:
        The sorted list

    Note:
        If sorting by "updated_at", will fallback to "created_at" in case of None.
    """
    if sort_by is None or not data:
        return data

    # Check if the sort field exists in the first item
    if sort_by not in data[0]:
        log_debug(f"Invalid sort field: '{sort_by}'. Will not apply any sorting.")
        return data

    try:
        is_descending = sort_order != "asc" if sort_order else True

        # Sort using the helper function that handles updated_at -> created_at fallback
        sorted_records = sorted(
            data,
            key=lambda x: (get_sort_value(x, sort_by) is None, get_sort_value(x, sort_by)),
            reverse=is_descending,
        )

        return sorted_records
    except Exception as e:
        log_debug(f"Error sorting data by '{sort_by}': {e}")
        return data
