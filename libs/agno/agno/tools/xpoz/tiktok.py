import json
from typing import TYPE_CHECKING, Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

from agno.tools.xpoz._client import get_client

if TYPE_CHECKING:
    from xpoz import XpozClient


class XpozTiktokTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional["XpozClient"] = None,
        enable_search_posts: bool = True,
        enable_get_user: bool = True,
        enable_get_posts_by_user: bool = True,
        enable_get_comments: bool = True,
        enable_search_users: bool = True,
        enable_get_users_by_keywords: bool = True,
        enable_get_posts_by_ids: bool = True,
        enable_get_posts_by_hashtags: bool = True,
        enable_get_users_by_hashtags: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self._client = get_client(api_key, client=client)

        tools: List[Any] = []
        if all or enable_search_posts:
            tools.append(self.tiktok_search_posts)
        if all or enable_get_user:
            tools.append(self.tiktok_get_user)
        if all or enable_get_posts_by_user:
            tools.append(self.tiktok_get_posts_by_user)
        if all or enable_get_comments:
            tools.append(self.tiktok_get_comments)
        if all or enable_search_users:
            tools.append(self.tiktok_search_users)
        if all or enable_get_users_by_keywords:
            tools.append(self.tiktok_get_users_by_keywords)
        if all or enable_get_posts_by_ids:
            tools.append(self.tiktok_get_posts_by_ids)
        if all or enable_get_posts_by_hashtags:
            tools.append(self.tiktok_get_posts_by_hashtags)
        if all or enable_get_users_by_hashtags:
            tools.append(self.tiktok_get_users_by_hashtags)

        super().__init__(name="xpoz_tiktok", tools=tools, **kwargs)

    def tiktok_search_posts(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search TikTok videos by keywords.

        Args:
            query (str): Search query for finding videos.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter videos after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter videos before this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of videos) and 'total_results' count.
        """
        try:
            result = self._client.tiktok.search_posts(
                query, limit=max_results, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute tiktok_search_posts")
            return json.dumps({"error": str(e)})

    def tiktok_get_user(
        self,
        identifier: str,
        identifier_type: str = "username",
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get a TikTok user profile by username or user ID.

        Args:
            identifier (str): The username or user ID.
            identifier_type (str): Type of identifier - 'username' or 'id'. Defaults to 'username'.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with user profile data.
        """
        try:
            result = self._client.tiktok.get_user(
                identifier, identifier_type=identifier_type, fields=fields
            )
            return json.dumps(result.model_dump())
        except Exception as e:
            logger.exception("Failed to execute tiktok_get_user")
            return json.dumps({"error": str(e)})

    def tiktok_get_posts_by_user(
        self,
        identifier: str,
        identifier_type: str = "username",
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get videos posted by a specific TikTok user.

        Args:
            identifier (str): The username or user ID.
            identifier_type (str): Type of identifier - 'username' or 'id'. Defaults to 'username'.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter videos after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter videos before this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of videos) and 'total_results' count.
        """
        try:
            result = self._client.tiktok.get_posts_by_user(
                identifier, identifier_type=identifier_type, limit=max_results,
                start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute tiktok_get_posts_by_user")
            return json.dumps({"error": str(e)})

    def tiktok_get_comments(
        self,
        post_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get comments on a specific TikTok video.

        Args:
            post_id (str): The TikTok video ID to get comments for.
            start_date (str): Filter comments after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter comments before this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of comments) and 'total_results' count.
        """
        try:
            result = self._client.tiktok.get_comments(
                post_id, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute tiktok_get_comments")
            return json.dumps({"error": str(e)})

    def tiktok_search_users(
        self,
        name: str,
        max_results: Optional[int] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search for TikTok users by name.

        Args:
            name (str): The name or partial name to search for.
            max_results (int): Maximum number of results to return. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of matching user profiles.
        """
        try:
            result = self._client.tiktok.search_users(name, limit=max_results, fields=fields)
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute tiktok_search_users")
            return json.dumps({"error": str(e)})

    def tiktok_get_users_by_keywords(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Find TikTok users who have been discussing a specific topic.

        Args:
            query (str): The topic or keywords to search for.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter by activity after this date (YYYY-MM-DD). Optional.
            end_date (str): Filter by activity before this date (YYYY-MM-DD). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of user profiles) and 'total_results' count.
        """
        try:
            result = self._client.tiktok.get_users_by_keywords(
                query, limit=max_results, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute tiktok_get_users_by_keywords")
            return json.dumps({"error": str(e)})

    def tiktok_get_posts_by_ids(
        self,
        post_ids: list[str],
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get multiple TikTok videos by their IDs.

        Args:
            post_ids (list[str]): List of TikTok video IDs to fetch.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of video objects.
        """
        try:
            result = self._client.tiktok.get_posts_by_ids(post_ids, fields=fields)
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute tiktok_get_posts_by_ids")
            return json.dumps({"error": str(e)})

    def tiktok_get_posts_by_hashtags(
        self,
        hashtags: list[str],
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Find TikTok videos by hashtags.

        Args:
            hashtags (list[str]): List of hashtags to search for (without # prefix).
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter videos after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter videos before this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of videos) and 'total_results' count.
        """
        try:
            result = self._client.tiktok.get_posts_by_hashtags(
                hashtags, limit=max_results, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute tiktok_get_posts_by_hashtags")
            return json.dumps({"error": str(e)})

    def tiktok_get_users_by_hashtags(
        self,
        hashtags: list[str],
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Find TikTok users who have been using specific hashtags.

        Args:
            hashtags (list[str]): List of hashtags to search for (without # prefix).
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter by activity after this date (YYYY-MM-DD). Optional.
            end_date (str): Filter by activity before this date (YYYY-MM-DD). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of user profiles) and 'total_results' count.
        """
        try:
            result = self._client.tiktok.get_users_by_hashtags(
                hashtags, limit=max_results, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute tiktok_get_users_by_hashtags")
            return json.dumps({"error": str(e)})
