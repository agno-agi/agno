"""
Scavio Tools
=============================

Demonstrates the Scavio toolkit: a unified Search API over 31 sources - Google,
YouTube, Amazon, Walmart, Reddit, TikTok, TikTok Shop, Instagram, X, LinkedIn,
Threads, Kuaishou, eBay, Target, Home Depot, Zillow, Redfin, Booking.com, Airbnb,
TripAdvisor, Yelp, Indeed, Glassdoor, the App Store, Google Play, SEC EDGAR,
Companies House, G2, Capterra, Google Ads Transparency and the Meta Ad Library -
plus an extract endpoint that reads any URL as HTML, Markdown or plain text.

ScavioTools exposes 189 tools, one per live Scavio endpoint. That is far more
than any one agent should be shown, so every provider is gated by an enable_*
flag. The ten providers the toolkit shipped with are on by default; everything
else is opt-in. Enable only what the agent needs.

Setup:
    pip install agno scavio
    export SCAVIO_API_KEY=***  # get a key at https://dashboard.scavio.dev
"""

from agno.agent import Agent
from agno.tools.scavio import ScavioTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: the default ten providers (Google, YouTube, Amazon, Walmart, Reddit,
# TikTok, TikTok Shop, Instagram, X, LinkedIn)
agent = Agent(tools=[ScavioTools()])

# Example 2: only the web providers (Google, YouTube, Reddit), plus extract for
# reading any page the search results point at
web_agent = Agent(
    tools=[
        ScavioTools(
            enable_google=True,
            enable_youtube=True,
            enable_reddit=True,
            enable_extract=True,
            enable_amazon=False,
            enable_walmart=False,
            enable_tiktok=False,
            enable_tiktok_shop=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
        )
    ]
)

# Example 3: retail price research across every marketplace Scavio covers
commerce_agent = Agent(
    tools=[
        ScavioTools(
            enable_amazon=True,
            enable_walmart=True,
            enable_tiktok_shop=True,
            enable_ebay=True,
            enable_target=True,
            enable_home_depot=True,
            enable_google=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
        )
    ]
)

# Example 4: only the social providers (X, LinkedIn, Reddit, Threads)
social_agent = Agent(
    tools=[
        ScavioTools(
            enable_reddit=True,
            enable_x=True,
            enable_linkedin=True,
            enable_threads=True,
            enable_google=False,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_tiktok=False,
            enable_tiktok_shop=False,
            enable_instagram=False,
        )
    ]
)

# Example 5: Google only - the SERP plus its thirteen verticals (Maps, Shopping,
# Flights, Hotels, News, Trends, AI Mode)
google_agent = Agent(
    tools=[
        ScavioTools(
            enable_google=True,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_tiktok_shop=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
        )
    ]
)

# Example 6: travel research - stays, hotels and the reviews behind them
travel_agent = Agent(
    tools=[
        ScavioTools(
            enable_booking=True,
            enable_airbnb=True,
            enable_tripadvisor=True,
            enable_yelp=True,
            enable_google=True,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_tiktok_shop=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
        )
    ]
)

# Example 7: company research - filings, employer reviews, software reviews and
# the ads a competitor is running
research_agent = Agent(
    tools=[
        ScavioTools(
            enable_sec=True,
            enable_companies_house=True,
            enable_glassdoor=True,
            enable_indeed=True,
            enable_g2=True,
            enable_capterra=True,
            enable_google_ads=True,
            enable_meta_ads=True,
            enable_extract=True,
            enable_google=False,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_tiktok_shop=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
        )
    ]
)

# Example 8: enable every tool explicitly - all 189 of them
all_agent = Agent(tools=[ScavioTools(all=True)])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    web_agent.print_response(
        "Search Google for the latest news on AI agent frameworks",
        markdown=True,
        stream=True,
    )

    web_agent.print_response(
        "What are people on Reddit saying about the Agno framework?",
        markdown=True,
        stream=True,
    )

    google_agent.print_response(
        "Find three highly rated ramen places in Austin, then check whether interest in "
        "'ramen' is rising or falling in Texas over the last 12 months",
        markdown=True,
        stream=True,
    )

    commerce_agent.print_response(
        "Compare prices for a 'mechanical keyboard' on Amazon, Walmart, Target and eBay, "
        "and use the eBay sold listings to tell me what one actually sells for",
        markdown=True,
        stream=True,
    )

    commerce_agent.print_response(
        "For Amazon ASIN B09V3KXJPB, list every seller and tell me who holds the buy box",
        markdown=True,
        stream=True,
    )

    social_agent.print_response(
        "What are people on X and LinkedIn saying about AI agents this week?",
        markdown=True,
        stream=True,
    )

    travel_agent.print_response(
        "Find a well-reviewed hotel in Lisbon for two nights in June under 200 EUR a night, "
        "and tell me what guests complain about most",
        markdown=True,
        stream=True,
    )

    research_agent.print_response(
        "Look up Notion on G2 and Capterra, summarise what reviewers dislike, then show me "
        "which ads they are currently running on Google",
        markdown=True,
        stream=True,
    )
