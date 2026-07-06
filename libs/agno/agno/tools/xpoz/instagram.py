import json
from typing import TYPE_CHECKING, Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

from agno.tools.xpoz._client import get_client

if TYPE_CHECKING:
    from xpoz import XpozClient


class XpozInstagramTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional["XpozClient"] = None,
        enable_search_posts: bool = True,
        enable_get_user: bool = True,
        enable_get_posts_by_user: bool = True,
        enable_get_comments: bool = True,
        enable_search_users: bool = True,
        enable_get_user_connections: bool = True,
        enable_get_post_interacting_users: bool = True,
        enable_get_users_by_keywords: bool = True,
        enable_get_posts_by_ids: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self._client = get_client(api_key, client=client)

        tools: List[Any] = []
        if all or enable_search_posts:
            tools.append(self.instagram_search_posts)
        if all or enable_get_user:
            tools.append(self.instagram_get_user)
        if all or enable_get_posts_by_user:
            tools.append(self.instagram_get_posts_by_user)
        if all or enable_get_comments:
            tools.append(self.instagram_get_comments)
        if all or enable_search_users:
            tools.append(self.instagram_search_users)
        if all or enable_get_user_connections:
            tools.append(self.instagram_get_user_connections)
        if all or enable_get_post_interacting_users:
            tools.append(self.instagram_get_post_interacting_users)
        if all or enable_get_users_by_keywords:
            tools.append(self.instagram_get_users_by_keywords)
        if all or enable_get_posts_by_ids:
            tools.append(self.instagram_get_posts_by_ids)

        super().__init__(name="xpoz_instagram", tools=tools, **kwargs)

    def instagram_search_posts(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search Instagram posts by keywords.

        Args:
            query (str): Search query for finding posts.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter posts after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter posts before this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of posts) and 'total_results' count.
        """
        try:
            result = self._client.instagram.search_posts(
                query, limit=max_results, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute instagram_search_posts")
            return json.dumps({"error": str(e)})

    def instagram_get_user(
        self,
        identifier: str,
        identifier_type: str = "username",
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get an Instagram user profile by username or user ID.

        Args:
            identifier (str): The username or user ID.
            identifier_type (str): Type of identifier - 'username' or 'id'. Defaults to 'username'.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with user profile data.
        """
        try:
            result = self._client.instagram.get_user(
                identifier, identifier_type=identifier_type, fields=fields
            )
            return json.dumps(result.model_dump())
        except Exception as e:
            logger.exception("Failed to execute instagram_get_user")
            return json.dumps({"error": str(e)})

    def instagram_get_posts_by_user(
        self,
        identifier: str,
        identifier_type: str = "username",
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get posts published by a specific Instagram user.

        Args:
            identifier (str): The username or user ID.
            identifier_type (str): Type of identifier - 'username' or 'id'. Defaults to 'username'.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter posts after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter posts before this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of posts) and 'total_results' count.
        """
        try:
            result = self._client.instagram.get_posts_by_user(
                identifier, identifier_type=identifier_type, limit=max_results,
                start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute instagram_get_posts_by_user")
            return json.dumps({"error": str(e)})

    def instagram_get_comments(
        self,
        post_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get comments on a specific Instagram post.

        Args:
            post_id (str): The Instagram post ID to get comments for.
            start_date (str): Filter comments after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter comments before this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of comments) and 'total_results' count.
        """
        try:
            result = self._client.instagram.get_comments(
                post_id, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute instagram_get_comments")
            return json.dumps({"error": str(e)})

    def instagram_search_users(
        self,
        name: str,
        max_results: Optional[int] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search for Instagram users by name.

        Args:
            name (str): The name or partial name to search for.
            max_results (int): Maximum number of results to return. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of matching user profiles.
        """
        try:
            result = self._client.instagram.search_users(name, limit=max_results, fields=fields)
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute instagram_search_users")
            return json.dumps({"error": str(e)})

    def instagram_get_user_connections(
        self,
        username: str,
        connection_type: str,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get an Instagram user's followers or following list.

        Args:
            username (str): The username to get connections for.
            connection_type (str): Type of connection - 'followers' or 'following'.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of user profiles) and 'total_results' count.
        """
        try:
            result = self._client.instagram.get_user_connections(
                username, connection_type=connection_type, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute instagram_get_user_connections")
            return json.dumps({"error": str(e)})

    def instagram_get_post_interacting_users(
        self,
        post_id: str,
        interaction_type: str,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get users who interacted with a specific Instagram post.

        Args:
            post_id (str): The post ID to get interacting users for.
            interaction_type (str): Type of interaction - 'likers' or 'commenters'.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of user profiles) and 'total_results' count.
        """
        try:
            result = self._client.instagram.get_post_interacting_users(
                post_id, interaction_type=interaction_type, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute instagram_get_post_interacting_users")
            return json.dumps({"error": str(e)})

    def instagram_get_users_by_keywords(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Find Instagram users who have been discussing a specific topic.

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
            result = self._client.instagram.get_users_by_keywords(
                query, limit=max_results, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute instagram_get_users_by_keywords")
            return json.dumps({"error": str(e)})

    def instagram_get_posts_by_ids(
        self,
        post_ids: list[str],
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get multiple Instagram posts by their IDs.

        Args:
            post_ids (list[str]): List of Instagram post IDs to fetch.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of post objects.
        """
        try:
            result = self._client.instagram.get_posts_by_ids(post_ids, fields=fields)
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute instagram_get_posts_by_ids")
            return json.dumps({"error": str(e)})
