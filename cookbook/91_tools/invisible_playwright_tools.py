"""
InvisiblePlaywrightTools - Firefox-based stealth browser

Useful when sites behind Cloudflare, Akamai, Datadome, or hCaptcha return
empty content or 403 from FirecrawlTools / Crawl4aiTools / ScrapegraphTools.

Backend: patched Firefox 150 binary (feder-cr/invisible_firefox, MPL-2.0,
same license as Firefox upstream). Fingerprint patches at the C++ source
code level so there are no JS shims to detect.

Prerequisites:
- pip install invisible_playwright
- python -m invisible_playwright fetch
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.invisible_playwright import InvisiblePlaywrightTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: scrape one URL through stealth Firefox
agent_scrape = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[InvisiblePlaywrightTools()],
    description="You are a web reader that uses a stealth Firefox to read sites that block standard scrapers.",
    instructions=[
        "Use scrape_url to read the requested page.",
        "Summarise what you find concisely.",
    ],
    markdown=True,
)

# Example 2: crawl a domain (multi-page) and search the web
agent_full = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        InvisiblePlaywrightTools(
            all=True,
            seed=42,
            max_pages=5,
            max_depth=2,
            search_engine="duckduckgo",
            num_results=5,
        )
    ],
    description="You are a research agent with stealth browsing.",
    instructions=[
        "Use search_web to discover relevant pages.",
        "Use crawl_site to follow links within a single domain.",
        "Use scrape_url for a single targeted page.",
    ],
    markdown=True,
)

# Example 3: scrape behind a proxy with deterministic fingerprint
agent_proxy = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        InvisiblePlaywrightTools(
            seed=42,
            proxy={
                "server": "socks5://proxy.example.com:1080",
                "username": "user",
                "password": "pass",
            },
            locale="en-US",
            timezone="America/New_York",
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_scrape.print_response(
        "Read https://bot.sannysoft.com and tell me which automation checks pass."
    )
