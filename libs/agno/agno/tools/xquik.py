import json
import urllib.parse
import urllib.request
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

_BASE = "https://xquik.com/api/v1"


class XquikTools(Toolkit):
    """
    XquikTools provides read-only access to X (Twitter) via the Xquik REST API.

    Requires only XQUIK_API_KEY (1 env var) vs XTools which requires 5 Twitter credentials.
    No external dependencies — uses stdlib urllib.

    For write operations (posting, replying, DMs), use XTools instead.

    Args:
        api_key: Xquik API key. Retrieved from XQUIK_API_KEY env variable if not provided.
        include_post_metrics: Whether to include engagement metrics in search results.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        include_post_metrics: bool = True,
        **kwargs,
    ):
        self.api_key = api_key or getenv("XQUIK_API_KEY")
        if not self.api_key:
            logger.error("XQUIK_API_KEY not set. Get a key at https://xquik.com")

        self.include_post_metrics = include_post_metrics

        tools: List[Any] = [
            self.search_posts,
            self.get_user_info,
            self.get_tweet,
            self.get_trends,
        ]

        super().__init__(name="xquik", tools=tools, **kwargs)

    def _api_get(self, path: str, params: Optional[dict] = None) -> Any:
        """Make a GET request to the Xquik API."""
        url = f"{_BASE}{path}"
        if params:
            qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{qs}"

        req = urllib.request.Request(
            url,
            headers={
                "X-API-Key": self.api_key or "",
                "Accept": "application/json",
                "User-Agent": "agno/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search_posts(self, query: str, max_results: int = 10) -> str:
        """
        Search for tweets on X (Twitter).

        Supports X search operators: from:user, #hashtag, "exact phrase",
        since:YYYY-MM-DD, until:YYYY-MM-DD, -is:retweet, -is:reply, has:media.

        Args:
            query (str): The search query.
            max_results (int): The maximum number of posts to retrieve (10-200).

        Returns:
            A JSON string with matching posts including author, text, URL, and engagement metrics.
        """
        try:
            max_results = max(10, min(max_results, 200))
            log_debug(f"Searching X via Xquik for: {query}, max results: {max_results}")

            data = self._api_get("/x/tweets/search", {
                "q": query,
                "limit": max_results,
                "queryType": "Top",
            })

            tweets = data.get("tweets", [])
            posts = []

            for tweet in tweets:
                author = tweet.get("author", {})
                post_data = {
                    "id": tweet.get("id", ""),
                    "text": tweet.get("text", ""),
                    "created_at": tweet.get("createdAt", ""),
                    "author": {
                        "id": author.get("id", ""),
                        "name": author.get("name", ""),
                        "username": author.get("username", ""),
                        "verified": author.get("verified", False),
                    },
                    "url": f"https://x.com/{author.get('username', 'unknown')}/status/{tweet.get('id', '')}",
                }
                if self.include_post_metrics:
                    post_data["metrics"] = {
                        "like_count": tweet.get("likeCount", 0),
                        "retweet_count": tweet.get("retweetCount", 0),
                        "reply_count": tweet.get("replyCount", 0),
                        "quote_count": tweet.get("quoteCount", 0),
                        "view_count": tweet.get("viewCount", 0),
                        "bookmark_count": tweet.get("bookmarkCount", 0),
                    }
                posts.append(post_data)

            log_info(f"Xquik: found {len(posts)} posts for query: {query}")
            result = {"query": query, "count": len(posts), "posts": posts}
            return json.dumps(result, indent=2)

        except Exception as e:
            logger.exception("Error searching posts via Xquik")
            return json.dumps({"error": str(e), "query": query})

    def get_user_info(self, username: str) -> str:
        """
        Retrieve information about a specific X (Twitter) user.

        Args:
            username (str): The username of the user to fetch information about (without @).

        Returns:
            A JSON string with the user's profile information including name,
            bio, follower/following counts, and verification status.
        """
        log_debug(f"Fetching user info for @{username} via Xquik")
        try:
            data = self._api_get(f"/x/users/{username.lstrip('@')}")
            result = {
                "id": data.get("id", ""),
                "name": data.get("name", ""),
                "username": data.get("username", ""),
                "description": data.get("description", ""),
                "followers_count": data.get("followers", 0),
                "following_count": data.get("following", 0),
                "tweet_count": data.get("statusesCount", 0),
                "verified": data.get("verified", False),
                "url": f"https://x.com/{data.get('username', username)}",
            }
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error fetching user info via Xquik")
            return json.dumps({"error": str(e)})

    def get_tweet(self, tweet_id: str) -> str:
        """
        Retrieve a single tweet by ID with full engagement metrics.

        Args:
            tweet_id (str): The tweet ID to look up.

        Returns:
            A JSON string with the tweet text, author info, and engagement metrics.
        """
        log_debug(f"Fetching tweet {tweet_id} via Xquik")
        try:
            data = self._api_get(f"/x/tweets/{tweet_id}")
            author = data.get("author", {})
            result = {
                "id": data.get("id", ""),
                "text": data.get("text", ""),
                "created_at": data.get("createdAt", ""),
                "author": {
                    "id": author.get("id", ""),
                    "name": author.get("name", ""),
                    "username": author.get("username", ""),
                    "verified": author.get("verified", False),
                },
                "metrics": {
                    "like_count": data.get("likeCount", 0),
                    "retweet_count": data.get("retweetCount", 0),
                    "reply_count": data.get("replyCount", 0),
                    "quote_count": data.get("quoteCount", 0),
                    "view_count": data.get("viewCount", 0),
                    "bookmark_count": data.get("bookmarkCount", 0),
                },
                "url": f"https://x.com/{author.get('username', 'unknown')}/status/{data.get('id', '')}",
            }
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error fetching tweet via Xquik")
            return json.dumps({"error": str(e)})

    def get_trends(self, woeid: int = 1, count: int = 20) -> str:
        """
        Get trending topics on X (Twitter).

        Args:
            woeid (int): WOEID for region. 1=Global, 23424977=US, 23424975=UK.
            count (int): Number of trends to return (1-50).

        Returns:
            A JSON string with a list of trending topics.
        """
        log_debug(f"Fetching trends (woeid={woeid}) via Xquik")
        try:
            data = self._api_get("/trends", {
                "woeid": woeid,
                "count": min(count, 50),
            })
            trends = data.get("trends", [])
            log_info(f"Xquik: found {len(trends)} trends")
            return json.dumps({"trends": trends}, indent=2)
        except Exception as e:
            logger.exception("Error fetching trends via Xquik")
            return json.dumps({"error": str(e)})
