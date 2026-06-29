import json
from typing import TYPE_CHECKING, Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

from agno.tools.xpoz._client import get_client

if TYPE_CHECKING:
    from xpoz import XpozClient


class XpozRedditTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional["XpozClient"] = None,
        enable_search_posts: bool = True,
        enable_get_post_with_comments: bool = True,
        enable_search_comments: bool = True,
        enable_get_user: bool = True,
        enable_search_users: bool = True,
        enable_get_users_by_keywords: bool = True,
        enable_search_subreddits: bool = True,
        enable_get_subreddit_with_posts: bool = True,
        enable_get_subreddits_by_keywords: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self._client = get_client(api_key, client=client)

        tools: List[Any] = []
        if all or enable_search_posts:
            tools.append(self.reddit_search_posts)
        if all or enable_get_post_with_comments:
            tools.append(self.reddit_get_post_with_comments)
        if all or enable_search_comments:
            tools.append(self.reddit_search_comments)
        if all or enable_get_user:
            tools.append(self.reddit_get_user)
        if all or enable_search_users:
            tools.append(self.reddit_search_users)
        if all or enable_get_users_by_keywords:
            tools.append(self.reddit_get_users_by_keywords)
        if all or enable_search_subreddits:
            tools.append(self.reddit_search_subreddits)
        if all or enable_get_subreddit_with_posts:
            tools.append(self.reddit_get_subreddit_with_posts)
        if all or enable_get_subreddits_by_keywords:
            tools.append(self.reddit_get_subreddits_by_keywords)

        super().__init__(name="xpoz_reddit", tools=tools, **kwargs)

    def reddit_search_posts(
        self,
        query: str,
        max_results: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        subreddit: Optional[str] = None,
        sort: Optional[str] = None,
        time: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search Reddit posts by keywords.

        Args:
            query (str): Search query for finding posts.
            max_results (int): Maximum number of results to return. Optional.
            start_date (str): Filter posts after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter posts before this date (YYYY-MM-DD format). Optional.
            subreddit (str): Limit search to a specific subreddit name. Optional.
            sort (str): Sort order - 'relevance', 'hot', 'top', 'new'. Optional.
            time (str): Time filter - 'hour', 'day', 'week', 'month', 'year', 'all'. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of posts) and 'total_results' count.
        """
        try:
            result = self._client.reddit.search_posts(
                query, limit=max_results, start_date=start_date, end_date=end_date,
                subreddit=subreddit, sort=sort, time=time, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute reddit_search_posts")
            return json.dumps({"error": str(e)})

    def reddit_get_post_with_comments(
        self,
        post_id: str,
        post_fields: Optional[list[str]] = None,
        comment_fields: Optional[list[str]] = None,
    ) -> str:
        """Get a Reddit post along with its comments.

        Args:
            post_id (str): The Reddit post ID.
            post_fields (list[str]): Specific fields to include for the post. Optional.
            comment_fields (list[str]): Specific fields to include for comments. Optional.

        Returns:
            str: JSON string with 'post' (post object) and 'comments' (list of comment objects).
        """
        try:
            result = self._client.reddit.get_post_with_comments(
                post_id, post_fields=post_fields, comment_fields=comment_fields
            )
            return json.dumps({
                "post": result.post.model_dump() if result.post else None,
                "comments": [c.model_dump() for c in result.comments] if result.comments else [],
            })
        except Exception as e:
            logger.exception("Failed to execute reddit_get_post_with_comments")
            return json.dumps({"error": str(e)})

    def reddit_search_comments(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        subreddit: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search Reddit comments by keywords.

        Args:
            query (str): Search query for finding comments.
            start_date (str): Filter comments after this date (YYYY-MM-DD format). Optional.
            end_date (str): Filter comments before this date (YYYY-MM-DD format). Optional.
            subreddit (str): Limit search to a specific subreddit name. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of comments) and 'total_results' count.
        """
        try:
            result = self._client.reddit.search_comments(
                query, start_date=start_date, end_date=end_date, subreddit=subreddit, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute reddit_search_comments")
            return json.dumps({"error": str(e)})

    def reddit_get_user(
        self,
        username: str,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Get a Reddit user profile.

        Args:
            username (str): The Reddit username.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with user profile data.
        """
        try:
            result = self._client.reddit.get_user(username, fields=fields)
            return json.dumps(result.model_dump())
        except Exception as e:
            logger.exception("Failed to execute reddit_get_user")
            return json.dumps({"error": str(e)})

    def reddit_search_users(
        self,
        name: str,
        max_results: Optional[int] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search for Reddit users by name.

        Args:
            name (str): The name or partial name to search for.
            max_results (int): Maximum number of results to return. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of matching user profiles.
        """
        try:
            result = self._client.reddit.search_users(name, limit=max_results, fields=fields)
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute reddit_search_users")
            return json.dumps({"error": str(e)})

    def reddit_get_users_by_keywords(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        subreddit: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Find Reddit users who have been discussing a specific topic.

        Args:
            query (str): The topic or keywords to search for.
            start_date (str): Filter by activity after this date (YYYY-MM-DD). Optional.
            end_date (str): Filter by activity before this date (YYYY-MM-DD). Optional.
            subreddit (str): Limit to a specific subreddit. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of user profiles) and 'total_results' count.
        """
        try:
            result = self._client.reddit.get_users_by_keywords(
                query, start_date=start_date, end_date=end_date, subreddit=subreddit, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute reddit_get_users_by_keywords")
            return json.dumps({"error": str(e)})

    def reddit_search_subreddits(
        self,
        query: str,
        max_results: Optional[int] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Search for subreddits by name or topic.

        Args:
            query (str): Search query for finding subreddits.
            max_results (int): Maximum number of results to return. Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with list of matching subreddits.
        """
        try:
            result = self._client.reddit.search_subreddits(query, limit=max_results, fields=fields)
            return json.dumps([item.model_dump() for item in result])
        except Exception as e:
            logger.exception("Failed to execute reddit_search_subreddits")
            return json.dumps({"error": str(e)})

    def reddit_get_subreddit_with_posts(
        self,
        subreddit_name: str,
        subreddit_fields: Optional[list[str]] = None,
        post_fields: Optional[list[str]] = None,
    ) -> str:
        """Get subreddit information along with its recent posts.

        Args:
            subreddit_name (str): The subreddit name (without r/ prefix).
            subreddit_fields (list[str]): Specific fields for subreddit info. Optional.
            post_fields (list[str]): Specific fields for posts. Optional.

        Returns:
            str: JSON string with 'subreddit' (subreddit info) and 'posts' (list of posts).
        """
        try:
            result = self._client.reddit.get_subreddit_with_posts(
                subreddit_name, subreddit_fields=subreddit_fields, post_fields=post_fields
            )
            return json.dumps({
                "subreddit": result.subreddit.model_dump() if result.subreddit else None,
                "posts": [p.model_dump() for p in result.posts] if result.posts else [],
            })
        except Exception as e:
            logger.exception("Failed to execute reddit_get_subreddit_with_posts")
            return json.dumps({"error": str(e)})

    def reddit_get_subreddits_by_keywords(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> str:
        """Find subreddits where a specific topic is being discussed.

        Args:
            query (str): The topic or keywords to search for.
            start_date (str): Filter by activity after this date (YYYY-MM-DD). Optional.
            end_date (str): Filter by activity before this date (YYYY-MM-DD). Optional.
            fields (list[str]): Specific fields to include in results. Optional.

        Returns:
            str: JSON string with 'data' (list of subreddits) and 'total_results' count.
        """
        try:
            result = self._client.reddit.get_subreddits_by_keywords(
                query, start_date=start_date, end_date=end_date, fields=fields
            )
            return json.dumps({
                "data": [item.model_dump() for item in result.data],
                "total_results": result.pagination.total_rows,
            })
        except Exception as e:
            logger.exception("Failed to execute reddit_get_subreddits_by_keywords")
            return json.dumps({"error": str(e)})
