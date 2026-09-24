"""
AntiBrow Tools
=============================

Demonstrates antibrow tools: browser tools that drive a persistent profile.
"""

from agno.agent import Agent
from agno.tools.antibrow import AntibrowTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# AntiBrow Configuration
# -------------------------------
# ANTIBROW_API_KEY: Your API key from the AntiBrow dashboard
#   - Required for authentication; `python -m antibrow login --key ...` stores it too
#   - Pass `api_key=` to override it per toolkit

# profile: The profile name. The same name always gets the same fingerprint,
#   cookies and storage, so an agent that signed in on an earlier run is still
#   signed in on the next one. Unlimited and free locally.

# proxy: Optional per-profile proxy URL (http, https or socks5, credentials in
#   the URL). The engine answers the challenge itself, so nothing is loaded into
#   chrome://extensions.

# temporary: Discard the profile when the session closes - use it for one-off
#   anonymous runs instead of polluting a named identity.

agent = Agent(
    name="Web Automation Assistant",
    tools=[AntibrowTools(profile="research-01")],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

agent.print_response(
    "Open https://example.com and tell me what the heading says.",
    stream=True,
)

# Two agents that must not share an identity need two profile names, not two
# tabs. How many may run at once is your plan's concurrency limit.
