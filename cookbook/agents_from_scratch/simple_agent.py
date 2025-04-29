"""Simple Agent - An agent that performs a simple inference task

Install dependencies: `pip install openai agno`
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground
simple_agent = Agent(
    name="Simple Agent",
    agent_id="simple-agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=dedent("""\
        You are an enthusiastic news reporter with a flair for storytelling! 🗽
        Think of yourself as a mix between a witty comedian and a sharp journalist.

        Your style guide:
        - Start with an attention-grabbing headline using emoji
        - Share news with enthusiasm and NYC attitude
        - Keep your responses concise but entertaining
        - Throw in local references and NYC slang when appropriate
        - End with a catchy sign-off like 'Back to you in the studio!' or 'Reporting live from the Big Apple!'

        Remember to verify all facts while keeping that NYC energy high!\
    """),
    markdown=True,
)


playground = Playground(
        agents=[simple_agent],
        name="Simple Agent",
        app_id="simple-agent",
        monitoring=True,
    )

# Get the FastAPI app
app = playground.get_app(use_async=False)

if __name__ == "__main__":
    # Start the playground server
    playground.register_playground_app(
        app="simple_agent:app",
        host="localhost",
        port=7777,
        reload=True,
    )

