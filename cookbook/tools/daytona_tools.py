"""
👩‍💻 Agent with Daytona tools

This example shows how to use Agno's Daytona integration to run Agent-generated code in a remote, secure sandbox.

1. Get your Daytona API key and API URL: https://app.daytona.io/dashboard/keys
2. Set the API key and API URL as environment variables:
    export DAYTONA_API_KEY=<your_api_key>
    export DAYTONA_API_URL=<your_api_url>
3. Install the dependencies:
    pip install agno anthropic daytona_sdk
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.daytona import DaytonaTools

daytona_tools = DaytonaTools()

# Setup an Agent focused on coding tasks, with access to the Daytona tools
agent = Agent(
    name="Coding Agent with Daytona tools",
    agent_id="coding-agent",
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[daytona_tools],
    markdown=True,
    show_tool_calls=True,
    instructions=[
        "You are an expert at writing and validating Python code. You have access to a remote, secure Daytona sandbox.",
        "Your primary purpose is to:",
        "1. Write clear, efficient Python code based on user requests",
        "2. Execute and verify the code in the Daytona sandbox",
        "3. Share the complete code with the user, as this is the main use case",
        "4. Provide thorough explanations of how the code works",
        "You can use the run_python_code tool to run Python code in the Daytona sandbox.",
        "Guidelines:",
        "- ALWAYS share the complete code with the user, properly formatted in code blocks",
        "- Verify code functionality by executing it in the sandbox before sharing",
        "- Iterate and debug code as needed to ensure it works correctly",
        "- Use pandas, matplotlib, and other Python libraries for data analysis when appropriate",
        "- Create proper visualizations when requested and add them as image artifacts to show inline",
        "- Handle file uploads and downloads properly",
        "- Explain your approach and the code's functionality in detail",
        "- Format responses with both code and explanations for maximum clarity",
        "- Handle errors gracefully and explain any issues encountered",
    ],
)


agent.print_response(
    "Write Python code to generate the first 10 Fibonacci numbers and calculate their sum and average"
)
