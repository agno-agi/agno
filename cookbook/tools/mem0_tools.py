"""
This example demonstrates how to use the Mem0 toolkit with Agno agents.

To get started, please export your Mem0 API key as an environment variable. You can get your Mem0 API key from https://app.mem0.ai/dashboard/api-keys

export MEM0_API_KEY=<your-mem0-api-key>
export MEM0_ORG_ID=<your-mem0-org-id> (Optional)
export MEM0_PROJECT_ID=<your-mem0-project-id> (Optional)
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mem0 import Mem0Tools

USER_ID = "jane_doe"
SESSION_ID = "agno_session"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[Mem0Tools()],
    user_id=USER_ID,
    session_id=SESSION_ID,
    add_state_in_messages=True,
    markdown=True,
    instructions=dedent(
        """
        You have an evolving memory of this user. Proactively capture new personal details,
        preferences, plans, and relevant context the user shares, and naturally bring them up
        in later conversation. Before answering questions about past details, recall from your memory
        to provide precise and personalized responses. Keep your memory concise: store only
        meaningful information that enhances long-term dialogue. If the user asks to start fresh,
        clear all remembered information and proceed anew.
        """
    ),
    show_tool_calls=True,
)

agent.print_response("I live in NYC")
agent.print_response("I lived in San Francisco for 5 years previously")
agent.print_response("I'm going to a Taylor Swift concert tomorrow")

agent.print_response("Summarize all the details of the conversation")

# More examples:
# agent.print_response("NYC has a famous Brooklyn Bridge")
# agent.print_response("Delete all my memories")
# agent.print_response("I moved to LA")
# agent.print_response("What is the name of the concert I am going to?")
