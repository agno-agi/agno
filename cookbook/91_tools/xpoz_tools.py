"""
Xpoz Tools
=============================

Demonstrates Xpoz social media intelligence tools for Twitter/X, Instagram, Reddit, and TikTok.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.xpoz import (
    XpozAccountTools,
    XpozInstagramTools,
    XpozRedditTools,
    XpozTiktokTools,
    XpozTrackingTools,
    XpozTwitterTools,
)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Twitter-only agent
twitter_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[XpozTwitterTools()],
    show_tool_calls=True,
    markdown=True,
)

# Example 2: Multi-platform agent with Twitter and Instagram
multi_platform_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[XpozTwitterTools(), XpozInstagramTools()],
    show_tool_calls=True,
    markdown=True,
)

# Example 3: All platforms
all_platforms_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        XpozTwitterTools(),
        XpozInstagramTools(),
        XpozRedditTools(),
        XpozTiktokTools(),
        XpozTrackingTools(),
        XpozAccountTools(),
    ],
    show_tool_calls=True,
    markdown=True,
)

# Example 4: Selective tools (only search and user lookup)
selective_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        XpozTwitterTools(
            enable_search_posts=True,
            enable_get_user=True,
            enable_get_users=False,
            enable_get_posts_by_author=False,
            enable_get_comments=False,
            enable_search_users=False,
            enable_get_user_connections=False,
            enable_get_users_by_keywords=False,
            enable_count_posts=False,
            enable_get_posts_by_ids=False,
            enable_get_retweets=False,
            enable_get_quotes=False,
            enable_get_post_interacting_users=False,
        ),
    ],
    show_tool_calls=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 80)
    print("TWITTER SEARCH")
    print("=" * 80)

    twitter_agent.print_response(
        "Search for what people are saying about AI agents on Twitter this week",
        markdown=True,
    )

    print("\n" + "=" * 80)
    print("MULTI-PLATFORM ANALYSIS")
    print("=" * 80)

    multi_platform_agent.print_response(
        "Compare the social media presence of OpenAI on Twitter and Instagram",
        markdown=True,
    )

    print("\n" + "=" * 80)
    print("REDDIT DISCUSSION")
    print("=" * 80)

    all_platforms_agent.print_response(
        "Find the most discussed AI topics on Reddit this week and summarize the key discussions",
        markdown=True,
    )
