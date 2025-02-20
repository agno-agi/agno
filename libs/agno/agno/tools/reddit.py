import json
from os import getenv
from typing import Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import praw  # type: ignore
except ImportError:
    raise ImportError("praw` not installed. Please install using `pip install praw`")


class RedditTools(Toolkit):
    def __init__(
        self,
        reddit_instance: Optional[praw.Reddit] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        get_user_info: bool = True,
        get_top_posts: bool = True,
        get_subreddit_info: bool = True,
        get_trending_subreddits: bool = True,
        get_subreddit_stats: bool = True,
        create_post: bool = True,
    ):
        super().__init__(name="reddit")

        if reddit_instance is not None:
            logger.info("Using provided Reddit instance")
            self.reddit = reddit_instance
        else:
            # Get credentials from environment variables if not provided
            self.client_id = client_id or getenv("REDDIT_CLIENT_ID")
            self.client_secret = client_secret or getenv("REDDIT_CLIENT_SECRET")
            self.user_agent = user_agent or getenv("REDDIT_USER_AGENT", "RedditTools v1.0")
            self.username = username or getenv("REDDIT_USERNAME")
            self.password = password or getenv("REDDIT_PASSWORD")

            self.reddit = None
            # Check if we have all required credentials
            if all([self.client_id, self.client_secret]):
                # Initialize with read-only access if no user credentials
                if not all([self.username, self.password]):
                    logger.info("Initializing Reddit client with read-only access")
                    self.reddit = praw.Reddit(
                        client_id=self.client_id,
                        client_secret=self.client_secret,
                        user_agent=self.user_agent,
                    )
                # Initialize with user authentication if credentials provided
                else:
                    logger.info(f"Initializing Reddit client with user authentication for u/{self.username}")
                    self.reddit = praw.Reddit(
                        client_id=self.client_id,
                        client_secret=self.client_secret,
                        user_agent=self.user_agent,
                        username=self.username,
                        password=self.password,
                    )
            else:
                logger.warning("Missing Reddit API credentials")

        if get_user_info:
            self.register(self.get_user_info)
        if get_top_posts:
            self.register(self.get_top_posts)
        if get_subreddit_info:
            self.register(self.get_subreddit_info)
        if get_trending_subreddits:
            self.register(self.get_trending_subreddits)
        if get_subreddit_stats:
            self.register(self.get_subreddit_stats)
        if create_post:
            self.register(self.create_post)

    def _check_user_auth(self) -> bool:
        """
        Check if user authentication is available for actions that require it.
        Returns:
            bool: True if user is authenticated, False otherwise
        """
        if not self.reddit:
            logger.error("Reddit client not initialized")
            return False

        if not all([self.username, self.password]):
            logger.error("User authentication required. Please provide username and password.")
            return False

        try:
            # Verify authentication by checking if we can get the authenticated user
            self.reddit.user.me()
            return True
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def get_user_info(self, username: str) -> str:
        """Get information about a Reddit user."""
        if not self.reddit:
            return "Please provide Reddit API credentials"

        try:
            logger.info(f"Getting info for u/{username}")

            user = self.reddit.redditor(username)
            info: Dict[str, Union[str, int, bool, float]] = {
                "name": user.name,
                "comment_karma": user.comment_karma,
                "link_karma": user.link_karma,
                "is_mod": user.is_mod,
                "is_gold": user.is_gold,
                "is_employee": user.is_employee,
                "created_utc": user.created_utc,
            }

            return json.dumps(info)

        except Exception as e:
            return f"Error getting user info: {e}"

    def get_top_posts(self, subreddit: str, time_filter: str = "week", limit: int = 10) -> str:
        """
        Get top posts from a subreddit for a specific time period.
        Args:
            subreddit (str): Name of the subreddit.
            time_filter (str): Time period to filter posts.
            limit (int): Number of posts to fetch.
        Returns:
            str: JSON string containing top posts.
        """
        if not self.reddit:
            return "Please provide Reddit API credentials"

        try:
            logger.debug(f"Getting top posts from r/{subreddit}")
            posts = self.reddit.subreddit(subreddit).top(time_filter=time_filter, limit=limit)
            top_posts: List[Dict[str, Union[str, int, float]]] = [
                {
                    "id": post.id,
                    "title": post.title,
                    "score": post.score,
                    "url": post.url,
                    "selftext": post.selftext,
                    "author": str(post.author),
                    "permalink": post.permalink,
                    "created_utc": post.created_utc,
                    "subreddit": str(post.subreddit),
                    "subreddit_name_prefixed": post.subreddit_name_prefixed,
                }
                for post in posts
            ]
            return json.dumps({"top_posts": top_posts})
        except Exception as e:
            return f"Error getting top posts: {e}"

    def get_subreddit_info(self, subreddit_name: str) -> str:
        """
        Get information about a specific subreddit.
        Args:
            subreddit_name (str): Name of the subreddit.
        Returns:
            str: JSON string containing subreddit information.
        """
        if not self.reddit:
            return "Please provide Reddit API credentials"

        try:
            logger.info(f"Getting info for r/{subreddit_name}")

            subreddit = self.reddit.subreddit(subreddit_name)
            flairs = [flair["text"] for flair in subreddit.flair.link_templates]
            info: Dict[str, Union[str, int, bool, float, List[str]]] = {
                "display_name": subreddit.display_name,
                "title": subreddit.title,
                "description": subreddit.description,
                "subscribers": subreddit.subscribers,
                "created_utc": subreddit.created_utc,
                "over18": subreddit.over18,
                "available_flairs": flairs,
                "public_description": subreddit.public_description,
                "url": subreddit.url,
            }

            return json.dumps(info)

        except Exception as e:
            return f"Error getting subreddit info: {e}"

    def get_trending_subreddits(self) -> str:
        """Get currently trending subreddits."""
        if not self.reddit:
            return "Please provide Reddit API credentials"

        try:
            logger.debug("Getting trending subreddits")
            popular_subreddits = self.reddit.subreddits.popular(limit=5)
            trending: List[str] = [subreddit.display_name for subreddit in popular_subreddits]
            return json.dumps({"trending_subreddits": trending})
        except Exception as e:
            return f"Error getting trending subreddits: {e}"

    def get_subreddit_stats(self, subreddit: str) -> str:
        """
        Get statistics about a subreddit.
        Args:
            subreddit (str): Name of the subreddit.
        Returns:
            str: JSON string containing subreddit statistics
        """
        if not self.reddit:
            return "Please provide Reddit API credentials"

        try:
            logger.debug(f"Getting stats for r/{subreddit}")
            sub = self.reddit.subreddit(subreddit)
            stats: Dict[str, Union[str, int, bool, float]] = {
                "display_name": sub.display_name,
                "subscribers": sub.subscribers,
                "active_users": sub.active_user_count,
                "description": sub.description,
                "created_utc": sub.created_utc,
                "over18": sub.over18,
                "public_description": sub.public_description,
            }
            return json.dumps({"subreddit_stats": stats})
        except Exception as e:
            return f"Error getting subreddit stats: {e}"

    def create_post(
        self,
        subreddit: str,
        title: str,
        content: str,
        flair: Optional[str] = None,
        is_self: bool = True,
    ) -> str:
        """
        Create a new post in a subreddit.

        Args:
            subreddit (str): Name of the subreddit to post in.
            title (str): Title of the post.
            content (str): Content of the post (text for self posts, URL for link posts).
            flair (Optional[str]): Flair to add to the post. Must be an available flair in the subreddit.
            is_self (bool): Whether this is a self (text) post (True) or link post (False).
        Returns:
            str: JSON string containing the created post information.
        """
        if not self.reddit:
            return "Please provide Reddit API credentials"

        if not self._check_user_auth():
            return "User authentication required for posting. Please provide username and password."

        try:
            logger.info(f"Creating post in r/{subreddit}")

            subreddit_obj = self.reddit.subreddit(subreddit)

            if flair:
                available_flairs = [f["text"] for f in subreddit_obj.flair.link_templates]
                if flair not in available_flairs:
                    return f"Invalid flair. Available flairs: {', '.join(available_flairs)}"

            if is_self:
                submission = subreddit_obj.submit(
                    title=title,
                    selftext=content,
                    flair_id=flair,
                )
            else:
                submission = subreddit_obj.submit(
                    title=title,
                    url=content,
                    flair_id=flair,
                )
            logger.info(f"Post created: {submission.permalink}")

            post_info: Dict[str, Union[str, int, float]] = {
                "id": submission.id,
                "title": submission.title,
                "url": submission.url,
                "permalink": submission.permalink,
                "created_utc": submission.created_utc,
                "author": str(submission.author),
                "flair": submission.link_flair_text,
            }

            return json.dumps({"post": post_info})

        except Exception as e:
            return f"Error creating post: {e}"
