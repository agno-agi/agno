import json
from os import getenv
from typing import Any, Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

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
        reply_to_post: bool = True,
        reply_to_comment: bool = True,
        **kwargs,
    ):
        if reddit_instance is not None:
            log_info("Using provided Reddit instance")
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
                    log_info("Initializing Reddit client with read-only access")
                    self.reddit = praw.Reddit(
                        client_id=self.client_id,
                        client_secret=self.client_secret,
                        user_agent=self.user_agent,
                    )
                # Initialize with user authentication if credentials provided
                else:
                    log_info(f"Initializing Reddit client with user authentication for u/{self.username}")
                    self.reddit = praw.Reddit(
                        client_id=self.client_id,
                        client_secret=self.client_secret,
                        user_agent=self.user_agent,
                        username=self.username,
                        password=self.password,
                    )
            else:
                logger.warning("Missing Reddit API credentials")

        tools: List[Any] = []
        if get_user_info:
            tools.append(self.get_user_info)
        if get_top_posts:
            tools.append(self.get_top_posts)
        if get_subreddit_info:
            tools.append(self.get_subreddit_info)
        if get_trending_subreddits:
            tools.append(self.get_trending_subreddits)
        if get_subreddit_stats:
            tools.append(self.get_subreddit_stats)
        if create_post:
            tools.append(self.create_post)
        if reply_to_post:
            tools.append(self.reply_to_post)
        if reply_to_comment:
            tools.append(self.reply_to_comment)

        super().__init__(name="reddit", tools=tools, **kwargs)

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
            log_info(f"Getting info for u/{username}")

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
            log_debug(f"Getting top posts from r/{subreddit}")
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
            log_info(f"Getting info for r/{subreddit_name}")

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
            log_debug("Getting trending subreddits")
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
            log_debug(f"Getting stats for r/{subreddit}")
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
            log_info(f"Creating post in r/{subreddit}")

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
            log_info(f"Post created: {submission.permalink}")

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

    def reply_to_post(self, post_id: str, content: str, subreddit: Optional[str] = None) -> str:
        """
        Post a reply to an existing Reddit post or comment.

        Args:
            post_id (str): The ID of the post or comment to reply to.
                          Can be a full URL, permalink, or just the ID.
            content (str): The content of the reply.
            subreddit (Optional[str]): The subreddit name if known.
                                     This helps with error handling and validation.

        Returns:
            str: JSON string containing information about the created reply.
        """
        if not self.reddit:
            logger.error("Reddit instance not initialized")
            return "Please provide Reddit API credentials"

        if not self._check_user_auth():
            logger.error("User authentication failed")
            return "User authentication required for posting replies. Please provide username and password."

        try:
            log_debug(f"Creating reply to post {post_id}")

            # Clean up the post_id if it's a full URL or permalink
            if "/" in post_id:
                # Extract the actual ID from the URL/permalink
                original_id = post_id
                post_id = post_id.split("/")[-1]
                log_debug(f"Extracted post ID {post_id} from {original_id}")

            # Verify post exists
            if not self._check_post_exists(post_id):
                error_msg = f"Post with ID {post_id} does not exist or is not accessible"
                logger.error(error_msg)
                return error_msg

            # Get the submission object
            submission = self.reddit.submission(id=post_id)

            log_debug(
                f"Post details: Title: {submission.title}, Author: {submission.author}, Subreddit: {submission.subreddit.display_name}"
            )

            # If subreddit was provided, verify we're in the right place
            if subreddit and submission.subreddit.display_name.lower() != subreddit.lower():
                error_msg = f"Error: Post ID belongs to r/{submission.subreddit.display_name}, not r/{subreddit}"
                logger.error(error_msg)
                return error_msg

            # Create the reply
            log_debug(f"Attempting to post reply with content length: {len(content)}")
            reply = submission.reply(body=content)

            # Prepare the response information
            reply_info: Dict[str, Union[str, int, float]] = {
                "id": reply.id,
                "body": reply.body,
                "score": reply.score,
                "permalink": reply.permalink,
                "created_utc": reply.created_utc,
                "author": str(reply.author),
                "parent_id": reply.parent_id,
                "submission_id": submission.id,
                "subreddit": str(reply.subreddit),
            }

            log_debug(f"Reply created successfully: {reply.permalink}")
            return json.dumps({"reply": reply_info})

        except praw.exceptions.RedditAPIException as api_error:
            # Handle specific Reddit API errors
            error_messages = [f"{error.error_type}: {error.message}" for error in api_error.items]
            error_msg = f"Reddit API Error: {'; '.join(error_messages)}"
            logger.error(error_msg)
            return error_msg

        except Exception as e:
            error_msg = f"Error creating reply: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def reply_to_comment(self, comment_id: str, content: str, subreddit: Optional[str] = None) -> str:
        """
        Post a reply to an existing Reddit comment.

        Args:
            comment_id (str): The ID of the comment to reply to.
                            Can be a full URL, permalink, or just the ID.
            content (str): The content of the reply.
            subreddit (Optional[str]): The subreddit name if known.
                                     This helps with error handling and validation.

        Returns:
            str: JSON string containing information about the created reply.
        """
        if not self.reddit:
            logger.error("Reddit instance not initialized")
            return "Please provide Reddit API credentials"

        if not self._check_user_auth():
            logger.error("User authentication failed")
            return "User authentication required for posting replies. Please provide username and password."

        try:
            log_debug(f"Creating reply to comment {comment_id}")

            # Clean up the comment_id if it's a full URL or permalink
            if "/" in comment_id:
                original_id = comment_id
                comment_id = comment_id.split("/")[-1]
                log_info(f"Extracted comment ID {comment_id} from {original_id}")

            # Get the comment object
            comment = self.reddit.comment(id=comment_id)

            log_debug(f"Comment details: Author: {comment.author}, Subreddit: {comment.subreddit.display_name}")

            # If subreddit was provided, verify we're in the right place
            if subreddit and comment.subreddit.display_name.lower() != subreddit.lower():
                error_msg = f"Error: Comment ID belongs to r/{comment.subreddit.display_name}, not r/{subreddit}"
                logger.error(error_msg)
                return error_msg

            # Create the reply
            log_debug(f"Attempting to post reply with content length: {len(content)}")
            reply = comment.reply(body=content)

            # Prepare the response information
            reply_info: Dict[str, Union[str, int, float]] = {
                "id": reply.id,
                "body": reply.body,
                "score": reply.score,
                "permalink": reply.permalink,
                "created_utc": reply.created_utc,
                "author": str(reply.author),
                "parent_id": reply.parent_id,
                "submission_id": comment.submission.id,
                "subreddit": str(reply.subreddit),
            }

            log_debug(f"Reply created successfully: {reply.permalink}")
            return json.dumps({"reply": reply_info})

        except praw.exceptions.RedditAPIException as api_error:
            # Handle specific Reddit API errors
            error_messages = [f"{error.error_type}: {error.message}" for error in api_error.items]
            error_msg = f"Reddit API Error: {'; '.join(error_messages)}"
            logger.error(error_msg)
            return error_msg

        except Exception as e:
            error_msg = f"Error creating reply: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def _check_post_exists(self, post_id: str) -> bool:
        """
        Verify that a post exists and is accessible.

        Args:
            post_id (str): The ID of the post to check

        Returns:
            bool: True if post exists and is accessible, False otherwise
        """
        try:
            submission = self.reddit.submission(id=post_id)
            # Try to access some attributes to verify the post exists
            _ = submission.title
            _ = submission.author
            return True
        except Exception as e:
            logger.error(f"Error checking post existence: {str(e)}")
            return False
