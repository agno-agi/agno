import json
import os
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    import tweepy
except ImportError:
    raise ImportError("`tweepy` not installed. Please install using `pip install tweepy`.")


class XTools(Toolkit):
    def __init__(
        self,
        bearer_token: Optional[str] = None,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
        include_post_metrics: bool = False,
        wait_on_rate_limit: bool = False,
        **kwargs,
    ):
        """
        Initialize the XTools.

        Args:
            bearer_token Optional[str]: The bearer token for Twitter API.
            consumer_key Optional[str]: The consumer key for Twitter API.
            consumer_secret Optional[str]: The consumer secret for Twitter API.
            access_token Optional[str]: The access token for Twitter API.
            access_token_secret Optional[str]: The access token secret for Twitter API.
            include_post_metrics Optional[bool]: Whether to include post metrics in the search results.
            wait_on_rate_limit Optional[bool]: Whether to wait on rate limit.
        """
        self.bearer_token = bearer_token or os.getenv("X_BEARER_TOKEN")
        self.consumer_key = consumer_key or os.getenv("X_CONSUMER_KEY")
        self.consumer_secret = consumer_secret or os.getenv("X_CONSUMER_SECRET")
        self.access_token = access_token or os.getenv("X_ACCESS_TOKEN")
        self.access_token_secret = access_token_secret or os.getenv("X_ACCESS_TOKEN_SECRET")
        self.wait_on_rate_limit = wait_on_rate_limit
        self.client = tweepy.Client(
            bearer_token=self.bearer_token,
            consumer_key=self.consumer_key,
            consumer_secret=self.consumer_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            wait_on_rate_limit=self.wait_on_rate_limit,
        )
        self.include_post_metrics = include_post_metrics

        tools: List[Any] = []
        tools.append(self.create_post)
        tools.append(self.reply_to_post)
        tools.append(self.send_dm)
        tools.append(self.get_user_info)
        tools.append(self.get_home_timeline)
        tools.append(self.search_posts)

        super().__init__(name="x", tools=tools, **kwargs)

    def create_post(self, text: str) -> str:
        """
        Create a new X post.

        Args:
            text (str): The content of the post to create.

        Returns:
            A JSON-formatted string containing the response from X API (Twitter API) with the created post details,
            or an error message if the post creation fails.
        """
        log_debug(f"Attempting to create post with text: {text}")
        try:
            response = self.client.create_tweet(text=text)
            post_id = response.data["id"]
            user = self.client.get_me().data
            post_url = f"https://x.com/{user.username}/status/{post_id}"

            result = {"message": "Post successfully created!", "url": post_url}
            return json.dumps(result, indent=2)
        except tweepy.TweepyException as e:
            logger.error(f"Error creating post: {e}")
            return json.dumps({"error": str(e)})

    def reply_to_post(self, post_id: str, text: str) -> str:
        """
        Reply to an existing post.

        Args:
            post_id (str): The ID of the post to reply to.
            text (str): The content of the reply post.

        Returns:
            A JSON-formatted string containing the response from Twitter API with the reply post details,
            or an error message if the reply fails.
        """
        log_debug(f"Attempting to reply to {post_id} with text {text}")
        try:
            response = self.client.create_tweet(text=text, in_reply_to_tweet_id=post_id)
            reply_id = response.data["id"]
            user = self.client.get_me().data
            reply_url = f"https://twitter.com/{user.username}/status/{reply_id}"
            result = {"message": "Reply successfully posted!", "url": reply_url}
            return json.dumps(result, indent=2)
        except tweepy.TweepyException as e:
            logger.error(f"Error replying to post: {e}")
            return json.dumps({"error": str(e)})

    def send_dm(self, recipient: str, text: str) -> str:
        """
        Send a direct message to a user.

        Args:
            recipient (str): The username or user ID of the recipient.
            text (str): The content of the direct message.

        Returns:
            A JSON-formatted string containing the response from Twitter API with the sent message details,
            or an error message if sending the DM fails.
        """
        log_debug(f"Attempting to send DM to user {recipient}")
        try:
            # Check if recipient is a user ID (numeric) or username
            if not recipient.isdigit():
                # If it's not numeric, assume it's a username and get the user ID
                user = self.client.get_user(username=recipient)
                log_debug(f"Attempting to send DM to user's id {user}")
                recipient_id = user.data.id
            else:
                recipient_id = recipient

            log_debug(f"Attempting to send DM to user's id {recipient_id}")
            response = self.client.create_direct_message(participant_id=recipient_id, text=text)
            result = {
                "message": "Direct message sent successfully!",
                "dm_id": response.data["id"],
                "recipient_id": recipient_id,
                "recipient_username": recipient if not recipient.isdigit() else None,
            }
            return json.dumps(result, indent=2)
        except tweepy.TweepyException as e:
            logger.error(f"Error from X while sending DM: {e}")
            error_message = str(e)
            if "User not found" in error_message:
                error_message = f"User '{recipient}' not found. Please check the username or user ID."
            elif "You cannot send messages to this user" in error_message:
                error_message = (
                    f"Unable to send message to '{recipient}'. The user may have restricted who can send them messages."
                )
            return json.dumps({"error": error_message}, indent=2)
        except Exception as e:
            logger.error(f"Unexpected error sending DM: {e}")
            return json.dumps({"error": f"An unexpected error occurred: {str(e)}"}, indent=2)

    def get_my_info(self) -> str:
        """
        Retrieve information about the authenticated user.

        Returns:
            A JSON-formatted string containing the user's profile information,
            including id, name, username, description, and follower/following counts,
            or an error message if fetching the information fails.
        """
        log_debug("Fetching information about myself")
        try:
            me = self.client.get_me(user_fields=["description", "public_metrics"])
            user_info = me.data.data
            result = {
                "id": user_info["id"],
                "name": user_info["name"],
                "username": user_info["username"],
                "description": user_info["description"],
                "followers_count": user_info["public_metrics"]["followers_count"],
                "following_count": user_info["public_metrics"]["following_count"],
                "tweet_count": user_info["public_metrics"]["tweet_count"],
            }
            return json.dumps(result, indent=2)
        except tweepy.TweepyException as e:
            logger.error(f"Error fetching user info: {e}")
            return json.dumps({"error": str(e)})

    def get_user_info(self, username: str) -> str:
        """
        Retrieve information about a specific user.

        Args:
            username (str): The username of the user to fetch information about.

        Returns:
            A JSON-formatted string containing the user's profile information,
            including id, name, username, description, and follower/following counts,
            or an error message if fetching the information fails.
        """
        log_debug(f"Fetching information about user {username}")
        try:
            user = self.client.get_user(username=username, user_fields=["description", "public_metrics"])
            user_info = user.data.data
            result = {
                "id": user_info["id"],
                "name": user_info["name"],
                "username": user_info["username"],
                "description": user_info["description"],
                "followers_count": user_info["public_metrics"]["followers_count"],
                "following_count": user_info["public_metrics"]["following_count"],
                "tweet_count": user_info["public_metrics"]["tweet_count"],
            }
            return json.dumps(result, indent=2)
        except tweepy.TweepyException as e:
            logger.error(f"Error fetching user info: {e}")
            return json.dumps({"error": str(e)})

    def get_home_timeline(self, max_results: int = 10) -> str:
        """
        Retrieve the authenticated user's home timeline.

        Args:
            max_results (int): The maximum number of tweets to retrieve. Default is 10.

        Returns:
            A JSON-formatted string containing a list of tweets from the user's home timeline,
            including tweet id, text, creation time, and author id,
            or an error message if fetching the timeline fails.
        """
        log_debug(f"Fetching home timeline, max results: {max_results}")
        try:
            tweets = self.client.get_home_timeline(
                max_results=max_results, tweet_fields=["created_at", "public_metrics"]
            )
            timeline = []
            for tweet in tweets.data:
                timeline.append(
                    {
                        "id": tweet.id,
                        "text": tweet.text,
                        "created_at": tweet.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "author_id": tweet.author_id,
                    }
                )
            log_info(f"Successfully fetched {len(timeline)} tweets")
            result = {"home_timeline": timeline}
            return json.dumps(result, indent=2)
        except tweepy.TweepyException as e:
            logger.error(f"Error fetching home timeline: {e}")
            return json.dumps({"error": str(e)})

    def search_posts(self, query: str, max_results: int = 10) -> str:
        """
        Search for tweets based on a search query.

        Args:
            query (str): The search query.
            max_results (int): The maximum number of posts to retrieve.

        Returns:
            A list of posts matching the search query
        """
        try:
            max_results = max(10, min(max_results, 100))  # range 10 - 100

            log_debug(f"Searching for posts with query: {query}, bounded max results: {max_results}")
            results = self.client.search_recent_tweets(
                query=query,
                max_results=max_results,
                tweet_fields=[
                    "author_id",
                    "created_at",
                    "id",
                    "public_metrics",
                    "text",
                ],
                user_fields=["name", "username", "verified"],
            )

            users_data = {}
            if hasattr(results, "includes") and "users" in results.includes:
                for user in results.includes["users"]:
                    users_data[user.id] = {
                        "id": user.id,
                        "name": user.name,
                        "username": user.username,
                        "verified": getattr(user, "verified", False),
                    }
            tweets = []

            if results.data:
                for tweet in results.data:
                    author_info = users_data.get(
                        tweet.author_id, {"id": tweet.author_id, "name": "Unknown", "username": "unknown"}
                    )

                    post_url = f"https://x.com/{author_info.get('username', 'unknown')}/status/{tweet.id}"

                    post_data = {
                        "id": tweet.id,
                        "text": tweet.text,
                        "created_at": tweet.created_at.strftime("%Y-%m-%d %H:%M:%S")
                        if hasattr(tweet, "created_at")
                        else None,
                        "author": author_info,
                        "url": post_url,
                    }
                    if self.include_post_metrics:
                        post_data["metrics"] = {
                            "retweet_count": tweet.public_metrics.get("retweet_count", 0)
                            if hasattr(tweet, "public_metrics")
                            else 0,
                            "reply_count": tweet.public_metrics.get("reply_count", 0)
                            if hasattr(tweet, "public_metrics")
                            else 0,
                            "like_count": tweet.public_metrics.get("like_count", 0)
                            if hasattr(tweet, "public_metrics")
                            else 0,
                            "quote_count": tweet.public_metrics.get("quote_count", 0)
                            if hasattr(tweet, "public_metrics")
                            else 0,
                        }
                    tweets.append(post_data)

                log_info(f"Successfully found {len(tweets)} posts for query: {query}")
                result = {"query": query, "count": len(tweets), "posts": tweets}
            else:
                log_info(f"No posts found for query: {query}")
                result = {}
            return json.dumps(result, indent=2)

        except tweepy.TweepyException as e:
            logger.error(f"Error searching posts: {e}")
            return json.dumps({"error": str(e), "query": query})
        except Exception as e:
            logger.error(f"Unexpected error searching posts: {e}")
            return json.dumps({"error": f"An unexpected error occurred: {str(e)}", "query": query})
