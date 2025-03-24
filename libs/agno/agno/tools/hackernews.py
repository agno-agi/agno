import json
from typing import Optional

import httpx

from agno.tools import Toolkit
from agno.utils.functions import cache_result
from agno.utils.log import log_debug, logger


class HackerNewsTools(Toolkit):
    """
    HackerNews is a tool for getting top stories from Hacker News.
    Args:
        get_top_stories (bool): Whether to get top stories from Hacker News.
        get_user_details (bool): Whether to get user details from Hacker News.
        cache_results (bool): Whether to enable caching of search results.
        cache_ttl (int): Time-to-live for cached results in seconds.
        cache_dir (Optional[str]): Directory to store cache files.
    """

    def __init__(
        self,
        get_top_stories: bool = True,
        get_user_details: bool = True,
        cache_results: bool = False,
        cache_ttl: int = 3600,
        cache_dir: Optional[str] = None,
    ):
        super().__init__(name="hackers_news")

        # Register functions in the toolkit
        if get_top_stories:
            self.register(self.get_top_hackernews_stories)
        if get_user_details:
            self.register(self.get_user_details)

        self.cache_results = cache_results
        self.cache_ttl = cache_ttl
        self.cache_dir = cache_dir

    @cache_result()
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

    @cache_result()
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
