"""
Publish and schedule social media posts with Publora.

Publora reaches LinkedIn, X, Instagram, Threads, TikTok, YouTube, Facebook,
Bluesky, Mastodon and Telegram through one API.

1. Create an account at https://publora.com and connect at least one channel.
2. Open API in the left menu and generate a key.
3. `export PUBLORA_API_KEY=***`
4. `pip install requests`

Nothing is published without a scheduled time: a post created without one is
saved as a draft.
"""

from agno.agent import Agent
from agno.tools.publora import PubloraTools

agent = Agent(
    tools=[PubloraTools()],
    instructions=[
        "Call list_connections first and copy platform ids exactly as returned.",
        "Times are ISO 8601 in UTC, for example 2026-10-20T09:00:00Z.",
        "Show the text, the accounts and the time, and publish only after the user confirms.",
    ],
    markdown=True,
)

# List the connected accounts.
agent.print_response("Which social accounts are connected?", stream=True)

# Save a draft: no scheduled time, so nothing goes out.
agent.print_response(
    "Draft a short post about our new changelog page for LinkedIn and Mastodon",
    stream=True,
)

# Schedule a post with an image.
agent.print_response(
    "Schedule that post for 20 October 2026 at 09:00 UTC and attach https://publora.com/og-image.png",
    stream=True,
)

# Check what is in the queue.
agent.print_response("List my scheduled posts", stream=True)
