from agno.agent import Agent
from agno.tools.tzafon import TzafonTools

# Tzafon Configuration
# -------------------------------
# These environment variables are required for the TzafonTools to function properly.
# You can set them in your .env file or export them directly in your terminal.

# TZAFON_API_KEY: Your API key from Tzafon dashboard
#   - Required for authentication
#   - Get your API key from https://tzafon.ai/dashboard

agent = Agent(
    name="Tzafon Web Assistant",
    tools=[TzafonTools()],
    instructions=[
        "You are a Tzafon-powered agent designed for seamless web interactions.",
        "Your capabilities include browsing the live web, gathering textual data, and visually capturing web pages.",
        "When given a URL:",
        "1. Access the page using the Tzafon cloud browser.",
        "2. Retrieve the relevant information requested by the user.",
        "3. If visual confirmation is needed, capture a screenshot.",
        "4. Present the findings clearly and concisely.",
    ],
    markdown=True,
)

agent.print_response("""
    Visit https://en.wikipedia.org/wiki/Main_Page and:
    1. Extract the featured article
    2. Take a screenshot of the page
""")
