import json
from typing import TYPE_CHECKING, Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

from agno.tools.xpoz._client import get_client

if TYPE_CHECKING:
    from xpoz import XpozClient


class XpozTwitterTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional["XpozClient"] = None,
        enable_search_posts: bool = True,
        enable_get_user: bool = True,
        enable_get_users: bool = True,
        enable_get_posts_by_author: bool = True,
        enable_get_comments: bool = True,
        enable_search_users: bool = True,
        enable_get_user_connections: bool = True,
        enable_get_users_by_keywords: bool = True,
        enable_count_posts: bool = True,
        enable_get_posts_by_ids: bool = True,
        enable_get_retweets: bool = True,
        enable_get_quotes: bool = True,
        enable_get_post_interacting_users: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self._client = get_client(api_key, client=client)

        tools: List[Any] = []
        if all or enable_search_posts:
            tools.append(self.twitter_search_posts)
        if all or enable_get_user:
            tools.append(self.twitter_get_user)
        if all or enable_get_users:
            tools.append(self.twitter_get_users)
        if all or enable_get_posts_by_author:
            tools.append(self.twitter_get_posts_by_author)
        if all or enable_get_comments:
            tools.append(self.twitter_get_comments)
        if all or enable_search_users:
            tools.append(self.twitter_search_users)
        if all or enable_get_user_connections:
            tools.append(self.twitter_get_user_connections)
        if all or enable_get_users_by_keywords:
            tools.append(self.twitter_get_users_by_keywords)
        if all or enable_count_posts:
            tools.append(self.twitter_count_posts)
        if all or enable_get_posts_by_ids:
            tools.append(self.twitter_get_posts_by_ids)
        if all or enable_get_retweets:
            tools.append(self.twitter_get_retweets)
        if all or enable_get_quotes:
            tools.append(self.twitter_get_quotes)
        if all or enable_get_post_interacting_users:
            tools.append(self.twitter_get_post_interacting_users)

        super().__init__(name="xpoz_twitter", tools=tools, **kwargs)

    def twitter_search_posts(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        language: Optional[str] = None,
        author_username: Optional[str] = None,
        author_id: Optional[str] = None,
        filter_out_retweets: Optional[bool] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search Twitter/X posts by keywords. Supports boolean operators (AND, OR, NOT).

        Args:
            query (str): Search query. Supports boolean operators like AND, OR, NOT.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter posts after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter posts before this date (YYYY-MM-DD format). Optional.
            language (str): Two-letter language code (e.g., 'en', 'es'). Optional.
            author_username (str): Filter posts by a specific author username. Optional.
            author_id (str): Filter posts by a specific author ID. Optional.
            filter_out_retweets (bool): Exclude retweets from results. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of posts) and 'total_results' count.
        """
        try:
            result = self._client.twitter.search_posts(
                query,
                limit=max_results,
                start_date=start_date,
                end_date=end_date,
                language=language,
                author_username=author_username,
                author_id=author_id,
                filter_out_retweets=filter_out_retweets,
                fields=fields,
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute twitter_search_posts")
            return json.dumps({"error": str(e)})

    def twitter_get_user(
        self,
        identifier: str,
        identifier_type: str = "username",
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get a Twitter/X user profile by username or user ID.

        Args:
            identifier (str): The username (without @) or user ID.
            identifier_type (str): Type of identifier - 'username' or 'id'. Defaults to 'username'.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with user profile data.
        """
        try:
            result = self._client.twitter.get_user(
                identifier, identifier_type=identifier_type, fields=fields
            )
            return json.dumps(result.model_dump())
        except Exception as e:
            logger.exception("Failed to execute twitter_get_user")
            return json.dumps({"error": str(e)})

    def twitter_get_users(
        self,
        identifiers: list[str],
        identifier_type: str = "username",
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get multiple Twitter/X user profiles at once.

        Args:
            identifiers (list[str]): List of usernames or user IDs.
            identifier_type (str): Type of identifiers - 'username' or 'id'. Defaults to 'username'.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of user profiles.
        """
        try:
            result = self._client.twitter.get_users(
                identifiers, identifier_type=identifier_type, fields=fields
            )
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute twitter_get_users")
            return json.dumps({"error": str(e)})

    def twitter_get_posts_by_author(
        self,
        identifier: str,
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get tweets posted by a specific user.

        Args:
            identifier (str): The username (without @) or user ID of the author.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter posts after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter posts before this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of posts) and 'total_results' count.
        """
        try:
            result = self._client.twitter.get_posts_by_author(
                identifier, limit=max_results, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute twitter_get_posts_by_author")
            return json.dumps({"error": str(e)})

    def twitter_get_comments(
        self,
        post_id: str,
        start_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get replies/comments on a specific tweet.

        Args:
            post_id (str): The tweet ID to get comments for.
            start_date (str): Filter comments after this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of reply posts) and 'total_results' count.
        """
        try:
            result = self._client.twitter.get_comments(post_id, start_date=start_date, fields=fields)
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute twitter_get_comments")
            return json.dumps({"error": str(e)})

    def twitter_search_users(
        self,
        name: str,
        max_results: Optional[int] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search for Twitter/X users by name.

        Args:
            name (str): The name or partial name to search for.
            max_results (int): Maximum number of results to return. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of matching user profiles.
        """
        try:
            result = self._client.twitter.search_users(name, limit=max_results, fields=fields)
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute twitter_search_users")
            return json.dumps({"error": str(e)})

    def twitter_get_user_connections(
        self,
        username: str,
        connection_type: str,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get a Twitter/X user's followers or following list.

        Args:
            username (str): The username (without @) to get connections for.
            connection_type (str): Type of connection - 'followers' or 'following'.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of user profiles) and 'total_results' count.
        """
        try:
            result = self._client.twitter.get_user_connections(
                username, connection_type=connection_type, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute twitter_get_user_connections")
            return json.dumps({"error": str(e)})

    def twitter_get_users_by_keywords(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        language: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Find Twitter/X users who have been discussing a specific topic.

        Args:
            query (str): The topic or keywords to search for.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter by activity after this date (YYYY-MM-DD). Optional.
            end_date (str): Filter by activity before this date (YYYY-MM-DD). Optional.
            language (str): Two-letter language code (e.g., 'en'). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of user profiles) and 'total_results' count.
        """
        try:
            result = self._client.twitter.get_users_by_keywords(
                query, limit=max_results, start_date=start_date, end_date=end_date,
                language=language, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute twitter_get_users_by_keywords")
            return json.dumps({"error": str(e)})

    def twitter_count_posts(
        self,
        phrase: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """Count the number of tweets matching a search phrase.

        Args:
            phrase (str): The phrase to count tweets for.
            start_date (str): Count posts after this date (YYYY-MM-DD). Optional.
            end_date (str): Count posts before this date (YYYY-MM-DD). Optional.

        Returns:
            str: JSON string with 'count' (integer).
        """
        try:
            result = self._client.twitter.count_posts(phrase, start_date=start_date, end_date=end_date)
            return json.dumps({"count": result})
        except Exception as e:
            logger.exception("Failed to execute twitter_count_posts")
            return json.dumps({"error": str(e)})

    def twitter_get_posts_by_ids(
        self,
        post_ids: list[str],
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get multiple tweets by their IDs.

        Args:
            post_ids (list[str]): List of tweet IDs to fetch.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of post objects.
        """
        try:
            result = self._client.twitter.get_posts_by_ids(post_ids, fields=fields)
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute twitter_get_posts_by_ids")
            return json.dumps({"error": str(e)})

    def twitter_get_retweets(
        self,
        post_id: str,
        start_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get retweets of a specific tweet.

        Args:
            post_id (str): The tweet ID to get retweets for.
            start_date (str): Filter retweets after this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of retweet posts) and 'total_results' count.
        """
        try:
            result = self._client.twitter.get_retweets(post_id, start_date=start_date, fields=fields)
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute twitter_get_retweets")
            return json.dumps({"error": str(e)})

    def twitter_get_quotes(
        self,
        post_id: str,
        start_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get quote tweets of a specific tweet.

        Args:
            post_id (str): The tweet ID to get quotes for.
            start_date (str): Filter quotes after this date (YYYY-MM-DD format). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of quote posts) and 'total_results' count.
        """
        try:
            result = self._client.twitter.get_quotes(post_id, start_date=start_date, fields=fields)
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute twitter_get_quotes")
            return json.dumps({"error": str(e)})

    def twitter_get_post_interacting_users(
        self,
        post_id: str,
        interaction_type: str,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get users who interacted with a specific tweet (liked, retweeted, or quoted).

        Args:
            post_id (str): The tweet ID to get interacting users for.
            interaction_type (str): Type of interaction - 'likers', 'retweeters', or 'quoters'.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of user profiles) and 'total_results' count.
        """
        try:
            result = self._client.twitter.get_post_interacting_users(
                post_id, interaction_type=interaction_type, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute twitter_get_post_interacting_users")
            return json.dumps({"error": str(e)})
