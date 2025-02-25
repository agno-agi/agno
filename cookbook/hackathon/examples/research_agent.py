from datetime import datetime
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ExaTools(
            start_published_date=datetime.now().strftime("%Y-%m-%d"), type="keyword"
        )
    ],
    description="You are a distinguished research scholar with expertise in multiple disciplines.",
    instructions=dedent("""\
    - Conduct 3 distinct searches
    - Synthesize findings across sources
    """),
    expected_output=dedent("""\
    A professional research report in markdown format:

    # {Compelling Title That Captures the Topic's Essence}

    ## Introduction
    {Context and importance of the topic}

    ## Key Findings
    {Major discoveries or developments}
    {Supporting evidence and analysis}

    ## Key Takeaways
    - {Bullet point 1}
    - {Bullet point 2}
    - {Bullet point 3}

    ## Sources
    - [Source 1](link) - Key finding/quote
    - [Source 2](link) - Key finding/quote
    - [Source 3](link) - Key finding/quote

    ---
    Date: {current_date}\
    """),
    add_datetime_to_instructions=True,
    show_tool_calls=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Research the latest developments in multi-modal agents", stream=True
    )
