import json
from typing import TYPE_CHECKING, Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

from agno.tools.xpoz._client import get_client

if TYPE_CHECKING:
    from xpoz import XpozClient


class XpozTrackingTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional["XpozClient"] = None,
        enable_get_tracked_items: bool = True,
        enable_add_tracked_items: bool = True,
        enable_remove_tracked_items: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self._client = get_client(api_key, client=client)

        tools: List[Any] = []
        if all or enable_get_tracked_items:
            tools.append(self.tracking_get_tracked_items)
        if all or enable_add_tracked_items:
            tools.append(self.tracking_add_tracked_items)
        if all or enable_remove_tracked_items:
            tools.append(self.tracking_remove_tracked_items)

        super().__init__(name="xpoz_tracking", tools=tools, **kwargs)

    def tracking_get_tracked_items(self) -> str:
        """Get all currently tracked keywords, phrases, and users across platforms.

        Returns:
            str: JSON string with list of tracked items, each containing phrase, type, and platform.
        """
        try:
            result = self._client.tracking.get_tracked_items()
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute tracking_get_tracked_items")
            return json.dumps({"error": str(e)})

    def tracking_add_tracked_items(self, items: list[dict]) -> str:
        """Start tracking new keywords, phrases, or users across social media platforms.

        Args:
            items (list[dict]): List of items to track. Each item should have:
                - 'phrase' (str): The keyword, phrase, or username to track.
                - 'type' (str): Type of tracking - 'keyword', 'user', 'subreddit', or 'hashtag'.
                - 'platform' (str): Platform - 'twitter', 'instagram', 'reddit', or 'tiktok'.

        Returns:
            str: JSON string with the result of the tracking operation.
        """
        try:
            from xpoz.types.tracking import TrackedItem

            tracked_items = [TrackedItem(**item) for item in items]
            result = self._client.tracking.add_tracked_items(tracked_items)
            return json.dumps(result.model_dump())
        except Exception as e:
            logger.exception("Failed to execute tracking_add_tracked_items")
            return json.dumps({"error": str(e)})

    def tracking_remove_tracked_items(self, items: list[dict]) -> str:
        """Stop tracking keywords, phrases, or users.

        Args:
            items (list[dict]): List of items to stop tracking. Each item should have:
                - 'phrase' (str): The keyword, phrase, or username to stop tracking.
                - 'type' (str): Type of tracking - 'keyword', 'user', 'subreddit', or 'hashtag'.
                - 'platform' (str): Platform - 'twitter', 'instagram', 'reddit', or 'tiktok'.

        Returns:
            str: JSON string with the result of the removal operation.
        """
        try:
            from xpoz.types.tracking import TrackedItem

            tracked_items = [TrackedItem(**item) for item in items]
            result = self._client.tracking.remove_tracked_items(tracked_items)
            return json.dumps(result.model_dump())
        except Exception as e:
            logger.exception("Failed to execute tracking_remove_tracked_items")
            return json.dumps({"error": str(e)})
