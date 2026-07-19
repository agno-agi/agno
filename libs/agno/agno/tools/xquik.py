"""Read-only X (Twitter) tools backed by the Xquik API."""

import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

_BASE_URL = "https://xquik.com/api/v1"
_MAX_SEARCH_RESULTS = 200
_MAX_TIMELINE_RESULTS = 100
_MAX_TRENDS = 50


class XquikTools(Toolkit):
    """Provide read-only access to X posts, profiles, timelines, and trends.

    Xquik is an independent third-party service. Use ``XTools`` for write
    operations such as posting, replying, or sending direct messages.

    Args:
        api_key: Xquik API key. Falls back to ``XQUIK_API_KEY``.
        include_post_metrics: Include engagement metrics in post results.
        timeout: Request timeout in seconds.
        enable_search_posts: Enable advanced X post search.
        enable_get_user_info: Enable user profile lookup.
        enable_get_tweet: Enable single-post lookup.
        enable_get_user_posts: Enable user timeline lookup.
        enable_get_trends: Enable regional trend lookup.
        all: Enable every tool regardless of individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        include_post_metrics: bool = True,
        timeout: float = 15.0,
        enable_search_posts: bool = True,
        enable_get_user_info: bool = True,
        enable_get_tweet: bool = True,
        enable_get_user_posts: bool = True,
        enable_get_trends: bool = True,
        all: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or getenv("XQUIK_API_KEY")
        if not self.api_key:
            logger.error(
                "XQUIK_API_KEY not set. Get a key at https://dashboard.xquik.com/dashboard/account?tab=api-keys"
            )
        self.include_post_metrics = include_post_metrics
        self.timeout = timeout

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []
        registrations = [
            (all or enable_search_posts, self.search_posts, self.asearch_posts, "search_posts"),
            (all or enable_get_user_info, self.get_user_info, self.aget_user_info, "get_user_info"),
            (all or enable_get_tweet, self.get_tweet, self.aget_tweet, "get_tweet"),
            (all or enable_get_user_posts, self.get_user_posts, self.aget_user_posts, "get_user_posts"),
            (all or enable_get_trends, self.get_trends, self.aget_trends, "get_trends"),
        ]
        for is_enabled, sync_tool, async_tool, name in registrations:
            if is_enabled:
                tools.append(sync_tool)
                async_tools.append((async_tool, name))

        super().__init__(name="xquik", tools=tools, async_tools=async_tools, **kwargs)

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ValueError("XQUIK_API_KEY not set. Set the environment variable or pass api_key.")
        return {
            "Accept": "application/json",
            "User-Agent": "agno-xquik",
            "x-api-key": self.api_key,
        }

    @staticmethod
    def _params(params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: str(value).lower() if isinstance(value, bool) else value
            for key, value in params.items()
            if value is not None
        }

    @staticmethod
    def _decode(response: httpx.Response) -> Dict[str, Any]:
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Xquik returned an invalid JSON response.")
        return data

    def _api_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with httpx.Client(headers=self._headers(), timeout=self.timeout, follow_redirects=False) as client:
            response = client.get(f"{_BASE_URL}{path}", params=self._params(params or {}))
        return self._decode(response)

    async def _api_get_async(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        async with httpx.AsyncClient(headers=self._headers(), timeout=self.timeout, follow_redirects=False) as client:
            response = await client.get(f"{_BASE_URL}{path}", params=self._params(params or {}))
        return self._decode(response)

    def _format_tweet(self, tweet: Dict[str, Any]) -> Dict[str, Any]:
        author = tweet.get("author") or {}
        if not isinstance(author, dict):
            raise ValueError("Xquik returned an invalid tweet author.")
        tweet_id = tweet.get("id", "")
        username = author.get("username") or "unknown"
        provided_url = tweet.get("url")
        url = (
            provided_url
            if isinstance(provided_url, str) and provided_url.startswith("https://x.com/")
            else f"https://x.com/{username}/status/{tweet_id}"
        )
        post_data = {
            "id": tweet_id,
            "text": tweet.get("text", ""),
            "created_at": tweet.get("createdAt", ""),
            "author": {
                "id": author.get("id", ""),
                "name": author.get("name", ""),
                "username": author.get("username", ""),
                "verified": author.get("verified", False),
            },
            "url": url,
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
        return post_data

    def _format_posts(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        tweets = data.get("tweets", [])
        if not isinstance(tweets, list) or any(not isinstance(tweet, dict) for tweet in tweets):
            raise ValueError("Xquik returned an invalid tweets response.")
        return [self._format_tweet(tweet) for tweet in tweets]

    @staticmethod
    def _bounded_count(value: int, name: str, maximum: int) -> int:
        if value <= 0:
            raise ValueError(f"{name} must be greater than 0.")
        return min(value, maximum)

    @staticmethod
    def _identifier(value: str, name: str) -> str:
        normalized = value.lstrip("@").strip()
        if not normalized:
            raise ValueError(f"Please provide a {name}.")
        return quote(normalized, safe="")

    @staticmethod
    def _error(message: str, error: Exception, **context: Any) -> str:
        logger.exception(message)
        return json.dumps({"error": str(error), **context})

    def _search_result(self, query: str, data: Dict[str, Any]) -> str:
        posts = self._format_posts(data)
        log_info(f"Xquik: found {len(posts)} posts for query: {query}")
        return json.dumps(
            {
                "query": query,
                "count": len(posts),
                "posts": posts,
                "has_next_page": data.get("has_next_page", False),
                "next_cursor": data.get("next_cursor"),
            },
            indent=2,
        )

    def search_posts(
        self,
        query: str,
        max_results: int = 20,
        cursor: Optional[str] = None,
        query_type: Literal["Latest", "Top"] = "Top",
    ) -> str:
        """Run an advanced X (Twitter) search.

        Args:
            query: Keywords or X search operators such as ``from:user``.
            max_results: Result cap for this agent response (1-200).
            cursor: Cursor returned by the previous response.
            query_type: ``Latest`` for chronology or ``Top`` for engagement.

        Returns:
            JSON with posts, metrics, and pagination cursors.
        """
        try:
            normalized_query = query.strip()
            if not normalized_query:
                return json.dumps({"error": "Please provide a query to search for."})
            limit = self._bounded_count(max_results, "max_results", _MAX_SEARCH_RESULTS)
            log_debug(f"Searching X via Xquik for: {normalized_query}, max results: {limit}")
            data = self._api_get(
                "/x/tweets/search",
                {"q": normalized_query, "limit": limit, "queryType": query_type, "cursor": cursor},
            )
            return self._search_result(normalized_query, data)
        except Exception as error:
            return self._error("Error searching posts via Xquik", error, query=query)

    async def asearch_posts(
        self,
        query: str,
        max_results: int = 20,
        cursor: Optional[str] = None,
        query_type: Literal["Latest", "Top"] = "Top",
    ) -> str:
        """Run an advanced X (Twitter) search asynchronously.

        Args:
            query: Keywords or X search operators such as ``from:user``.
            max_results: Result cap for this agent response (1-200).
            cursor: Cursor returned by the previous response.
            query_type: ``Latest`` for chronology or ``Top`` for engagement.

        Returns:
            JSON with posts, metrics, and pagination cursors.
        """
        try:
            normalized_query = query.strip()
            if not normalized_query:
                return json.dumps({"error": "Please provide a query to search for."})
            limit = self._bounded_count(max_results, "max_results", _MAX_SEARCH_RESULTS)
            data = await self._api_get_async(
                "/x/tweets/search",
                {"q": normalized_query, "limit": limit, "queryType": query_type, "cursor": cursor},
            )
            return self._search_result(normalized_query, data)
        except Exception as error:
            return self._error("Error searching posts via Xquik", error, query=query)

    @staticmethod
    def _user_result(username: str, data: Dict[str, Any]) -> str:
        return json.dumps(
            {
                "id": data.get("id", ""),
                "name": data.get("name", ""),
                "username": data.get("username", ""),
                "description": data.get("description", ""),
                "followers_count": data.get("followers", 0),
                "following_count": data.get("following", 0),
                "tweet_count": data.get("statusesCount", 0),
                "verified": data.get("verified", False),
                "url": f"https://x.com/{data.get('username') or username.lstrip('@')}",
            },
            indent=2,
        )

    def get_user_info(self, username: str) -> str:
        """Retrieve an X user profile by username or ID.

        Args:
            username: X username, with or without ``@``, or a user ID.

        Returns:
            JSON with profile details, counts, verification, and profile URL.
        """
        try:
            user_id = self._identifier(username, "username or user ID")
            return self._user_result(username, self._api_get(f"/x/users/{user_id}"))
        except Exception as error:
            return self._error("Error fetching user info via Xquik", error)

    async def aget_user_info(self, username: str) -> str:
        """Retrieve an X user profile asynchronously.

        Args:
            username: X username, with or without ``@``, or a user ID.

        Returns:
            JSON with profile details, counts, verification, and profile URL.
        """
        try:
            user_id = self._identifier(username, "username or user ID")
            return self._user_result(username, await self._api_get_async(f"/x/users/{user_id}"))
        except Exception as error:
            return self._error("Error fetching user info via Xquik", error)

    def _tweet_result(self, data: Dict[str, Any]) -> str:
        tweet = data.get("tweet")
        if not isinstance(tweet, dict):
            return json.dumps({"error": "Xquik returned an invalid tweet response."})
        return json.dumps(self._format_tweet({**tweet, "author": data.get("author")}), indent=2)

    def get_tweet(self, tweet_id: str) -> str:
        """Retrieve one X post by ID.

        Args:
            tweet_id: X post ID.

        Returns:
            JSON with the post, author, engagement metrics, and URL.
        """
        try:
            encoded_id = self._identifier(tweet_id, "tweet ID")
            return self._tweet_result(self._api_get(f"/x/tweets/{encoded_id}"))
        except Exception as error:
            return self._error("Error fetching tweet via Xquik", error)

    async def aget_tweet(self, tweet_id: str) -> str:
        """Retrieve one X post by ID asynchronously.

        Args:
            tweet_id: X post ID.

        Returns:
            JSON with the post, author, engagement metrics, and URL.
        """
        try:
            encoded_id = self._identifier(tweet_id, "tweet ID")
            return self._tweet_result(await self._api_get_async(f"/x/tweets/{encoded_id}"))
        except Exception as error:
            return self._error("Error fetching tweet via Xquik", error)

    def _user_posts_result(self, username: str, data: Dict[str, Any]) -> str:
        posts = self._format_posts(data)
        return json.dumps(
            {
                "username": username.lstrip("@"),
                "count": len(posts),
                "posts": posts,
                "has_next_page": data.get("has_next_page", False),
                "next_cursor": data.get("next_cursor"),
            },
            indent=2,
        )

    @staticmethod
    def _user_posts_params(
        cursor: Optional[str], include_replies: bool, include_parent_tweet: bool, max_results: int
    ) -> Dict[str, Any]:
        return {
            "cursor": cursor,
            "includeReplies": include_replies,
            "includeParentTweet": include_parent_tweet,
            "pageSize": XquikTools._bounded_count(max_results, "max_results", _MAX_TIMELINE_RESULTS),
        }

    def get_user_posts(
        self,
        username: str,
        cursor: Optional[str] = None,
        include_replies: bool = False,
        include_parent_tweet: bool = False,
        max_results: int = 20,
    ) -> str:
        """Retrieve a user's recent X posts with pagination.

        Args:
            username: X username, with or without ``@``, or a user ID.
            cursor: Cursor returned by the previous response.
            include_replies: Include the user's replies.
            include_parent_tweet: Include parent posts for replies.
            max_results: Result cap for this agent response (1-100).

        Returns:
            JSON with posts, metrics, and pagination cursors.
        """
        try:
            user_id = self._identifier(username, "username or user ID")
            data = self._api_get(
                f"/x/users/{user_id}/tweets",
                self._user_posts_params(cursor, include_replies, include_parent_tweet, max_results),
            )
            return self._user_posts_result(username, data)
        except Exception as error:
            return self._error("Error fetching user posts via Xquik", error)

    async def aget_user_posts(
        self,
        username: str,
        cursor: Optional[str] = None,
        include_replies: bool = False,
        include_parent_tweet: bool = False,
        max_results: int = 20,
    ) -> str:
        """Retrieve a user's recent X posts asynchronously.

        Args:
            username: X username, with or without ``@``, or a user ID.
            cursor: Cursor returned by the previous response.
            include_replies: Include the user's replies.
            include_parent_tweet: Include parent posts for replies.
            max_results: Result cap for this agent response (1-100).

        Returns:
            JSON with posts, metrics, and pagination cursors.
        """
        try:
            user_id = self._identifier(username, "username or user ID")
            data = await self._api_get_async(
                f"/x/users/{user_id}/tweets",
                self._user_posts_params(cursor, include_replies, include_parent_tweet, max_results),
            )
            return self._user_posts_result(username, data)
        except Exception as error:
            return self._error("Error fetching user posts via Xquik", error)

    @staticmethod
    def _trends_result(data: Dict[str, Any]) -> str:
        trends = data.get("trends", [])
        total = data.get("total")
        woeid = data.get("woeid")
        if (
            not isinstance(trends, list)
            or any(not isinstance(trend, dict) for trend in trends)
            or not isinstance(total, int)
            or not isinstance(woeid, int)
        ):
            raise ValueError("Xquik returned an invalid trends response.")
        return json.dumps({"trends": trends, "total": total, "woeid": woeid}, indent=2)

    def get_trends(self, woeid: int = 1, count: int = 20) -> str:
        """Retrieve trending X topics for a Yahoo WOEID region.

        Args:
            woeid: Region code. Use 1 for worldwide trends.
            count: Number of trends to return (1-50).

        Returns:
            JSON with the region's trending topics.
        """
        try:
            limit = self._bounded_count(count, "count", _MAX_TRENDS)
            return self._trends_result(self._api_get("/trends", {"woeid": woeid, "count": limit}))
        except Exception as error:
            return self._error("Error fetching trends via Xquik", error)

    async def aget_trends(self, woeid: int = 1, count: int = 20) -> str:
        """Retrieve trending X topics asynchronously.

        Args:
            woeid: Region code. Use 1 for worldwide trends.
            count: Number of trends to return (1-50).

        Returns:
            JSON with the region's trending topics.
        """
        try:
            limit = self._bounded_count(count, "count", _MAX_TRENDS)
            return self._trends_result(await self._api_get_async("/trends", {"woeid": woeid, "count": limit}))
        except Exception as error:
            return self._error("Error fetching trends via Xquik", error)
