"""
👩‍💻 Agent with Daytona tools

This example shows how to use Agno's Daytona integration to run Agent-generated code in a remote, secure sandbox.

1. Get your Daytona API key and API URL: https://app.daytona.io/dashboard/keys
2. Set the API key and API URL as environment variables:
    export DAYTONA_API_KEY=<your_api_key>
    export DAYTONA_API_URL=<your_api_url> (optional)
3. Install the dependencies:
    pip install agno anthropic daytona
"""

from agno.agent import Agent
from agno.tools.daytona import DaytonaTools

agent = Agent(
    name="Coding Agent with Daytona tools",
    tools=[DaytonaTools()],
    markdown=True,
    show_tool_calls=True,
)

agent.print_response(
    "Create a Python script called data_analysis.py that generates sample data and saves it to a CSV file"
)

agent.print_response(
    "Run the data_analysis.py script and show me the results. List all files created."
)
