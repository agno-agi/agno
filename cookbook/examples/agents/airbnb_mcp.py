"""🏠 MCP Airbnb Agent - Search for Airbnb listings!

This example shows how to create an agent that uses MCP and Llama 4 to search for Airbnb listings.

1. Run: `pip install groq mcp agno` to install the dependencies
2. Export your GROQ_API_KEY
3. Run: `python cookbook/examples/agents/airbnb_mcp.py` to run the agent
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.mcp import MCPTools
from agno.tools.reasoning import ReasoningTools


async def run_agent(message: str) -> None:
    async with MCPTools(
        "npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt"
    ) as mcp_tools:
        agent = Agent(
            model=Groq(id="meta-llama/llama-4-scout-17b-16e-instruct"),
            tools=[ReasoningTools(add_instructions=True), mcp_tools],
            instructions=dedent("""\
            ## General Instructions
            - Always start by using the think tool to map out the steps needed to complete the task.
            - After receiving tool results, use the think tool as a scratchpad to validate the results for correctness
            - Before responding to the user, use the think tool to jot down final thoughts and ideas.
            - Present final outputs in well-organized tables whenever possible.
            - Always provide links to the listings in your response.
            - Show your top 10 recommendations in a table and make a case for why each is the best choice.

            ## Using the think tool
            At every step, use the think tool as a scratchpad to:
            - Restate the object in your own words to ensure full comprehension.
            - List the  specific rules that apply to the current request
            - Check if all required information is collected and is valid
            - Verify that the planned action completes the task\
            """),
            add_datetime_to_context=True,
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    task = dedent("""\
    I'm traveling to San Francisco from April 20th - May 8th. Can you find me the best deals for a 1 bedroom apartment?
    I'd like a dedicated workspace and close proximity to public transport.\
    """)
    asyncio.run(run_agent(task))
