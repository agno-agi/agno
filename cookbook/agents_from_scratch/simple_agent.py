"""Simple Agent - An agent that performs a simple inference task

Install dependencies: `pip install openai agno`
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat

simple_agent = Agent(
    name="Simple Agent",
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

if __name__ == "__main__":
    simple_agent.print_response("Share a news story from NYC and SF.", stream=True)
