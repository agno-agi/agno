import datetime
from typing import Any, Dict, Optional

import requests
from agno.run.response import RunResponse
from agno.utils.log import logger
from config import (
    HEADERS,
    TYPEFULLY_API_URL,
    PostType,
)
from dotenv import load_dotenv

load_dotenv()


def json_to_typefully_content(thread_json: Dict[str, Any]) -> str:
    """Convert JSON thread format to Typefully's format with 4 newlines between tweets."""
    tweets = thread_json["tweets"]
    formatted_tweets = []
    for tweet in tweets:
        tweet_text = tweet["content"]
        if "media_urls" in tweet and tweet["media_urls"]:
            tweet_text += f"\n{tweet['media_urls'][0]}"
        formatted_tweets.append(tweet_text)

    return "\n\n\n\n".join(formatted_tweets)


def json_to_linkedin_content(thread_json: Dict[str, Any]) -> str:
    """Convert JSON thread format to Typefully's format."""
    content = thread_json["content"]
    if "url" in thread_json and thread_json["url"]:
        content += f"\n{thread_json['url']}"
    return content


def schedule_thread(
    content: str,
    schedule_date: str = "next-free-slot",
    threadify: bool = False,
    share: bool = False,
    auto_retweet_enabled: bool = False,
    auto_plug_enabled: bool = False,
) -> Optional[Dict[str, Any]]:
    """Schedule a thread on Typefully."""
    payload = {
        "content": content,
        "schedule-date": schedule_date,
        "threadify": threadify,
        "share": share,
        "auto_retweet_enabled": auto_retweet_enabled,
        "auto_plug_enabled": auto_plug_enabled,
    }

    payload = {key: value for key, value in payload.items() if value is not None}

    try:
        response = requests.post(TYPEFULLY_API_URL, json=payload, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error: {e}")
        return None


def schedule(
    thread_data,
    threadify: bool = False,
    share: bool = True,
    post_type: PostType = PostType.TWITTER,
    schedule_date: str = None,
) -> Optional[Dict[str, Any]]:
    """
    Schedule a thread from a Pydantic model.

    Args:
        thread_data: Post content
        threadify: Whether to let Typefully split the content (default: False)
        share: Whether to get a share URL in response (default: True)
        post_type: Type of post (Twitter or LinkedIn)
        schedule_date: Optional specific date in ISO format

    Returns:
        API response dictionary or None if failed
    """
    try:
        thread_content = ""
        logger.info(f"######## Thread JSON: {thread_data}")
        # Convert to Typefully format
        if post_type == PostType.TWITTER:
            thread_content = json_to_typefully_content(thread_data)
        elif post_type == PostType.LINKEDIN:
            thread_content = json_to_linkedin_content(thread_data)

        # Calculate schedule time if not explicitly provided
        if schedule_date is None:
            schedule_date = (
                datetime.datetime.now() + datetime.timedelta(hours=1)
            ).isoformat() + "Z"

        if thread_content:
            # Schedule the thread
            response = schedule_thread(
                content=thread_content,
                schedule_date=schedule_date,
                threadify=threadify,
                share=share,
            )

            if response:
                logger.info("Thread scheduled successfully!")
                return response
            else:
                logger.error("Failed to schedule the thread.")
                return None
        return None

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return None


def schedule_and_publish(plan, post_type: PostType, schedule_date: str) -> RunResponse:
    """
    Schedules and publishes the content leveraging Typefully api.
    """
    logger.info(f"Publishing content for post type: {post_type}")

    # Use the `scheduler` module directly to schedule the content
    response = schedule(
        thread_data=plan,
        post_type=post_type,  # Either "Twitter" or "LinkedIn"
        schedule_date=schedule_date,
    )

    if response:
        return RunResponse(content="Content is scheduled!")
    else:
        return RunResponse(content="Failed to schedule content.")
