import json
from typing import Any, List

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class HackerNewsTools(Toolkit):
    """
    HackerNews is a tool for getting top stories from Hacker News.

    Args:
        enable_get_top_stories (bool): Enable getting top stories from Hacker News. Default is True.
        enable_get_user_details (bool): Enable getting user details from Hacker News. Default is True.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
    """

    def __init__(
        self, enable_get_top_stories: bool = True, enable_get_user_details: bool = True, all: bool = False, **kwargs
    ):
        tools: List[Any] = []
        if all or enable_get_top_stories:
            tools.append(self.get_top_hackernews_stories)
        if all or enable_get_user_details:
            tools.append(self.get_user_details)

        super().__init__(name="hackers_news", tools=tools, **kwargs)

    def get_top_hackernews_stories(self, num_stories: int = 10) -> str:
        """Use this function to get top stories from Hacker News.

        Args:
            num_stories (int): Number of stories to return. Defaults to 10.

        Returns:
            str: JSON string of top stories.
        """

        log_debug(f"Getting top {num_stories} stories from Hacker News")
        # Fetch top story IDs
        response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
        story_ids = response.json()

        # Fetch story details
        stories = []
        for story_id in story_ids[:num_stories]:
            story_response = httpx.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
            story = story_response.json()
            story["username"] = story["by"]
            stories.append(story)
        return json.dumps(stories)

    def get_user_details(self, username: str) -> str:
        """Use this function to get the details of a Hacker News user using their username.

        Args:
            username (str): Username of the user to get details for.

        Returns:
            str: JSON string of the user details.
        """

        try:
            log_debug(f"Getting details for user: {username}")
            user = httpx.get(f"https://hacker-news.firebaseio.com/v0/user/{username}.json").json()
            user_details = {
                "id": user.get("user_id"),
                "karma": user.get("karma"),
                "about": user.get("about"),
                "total_items_submitted": len(user.get("submitted", [])),
            }
            return json.dumps(user_details)
        except Exception as e:
            logger.exception(e)
            return f"Error getting user details: {e}"
