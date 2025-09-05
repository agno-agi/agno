"""📝 Interactive Writing Assistant - CLI App Example

This example shows how to create an interactive CLI app with an agent.

Run `pip install openai agno duckduckgo-search` to install dependencies.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

writing_assistant = Agent(
    name="Writing Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions=dedent("""\
        You are a friendly and professional writing assistant! 
        
        Your capabilities include:
        - **Brainstorming**: Help generate ideas, topics, and creative concepts
        - **Research**: Find current information and facts to support writing
        - **Editing**: Improve grammar, style, clarity, and flow
        - **Feedback**: Provide constructive suggestions for improvement
        - **Content Creation**: Help write articles, emails, stories, and more
        
        Always:
        - Ask clarifying questions to better understand the user's needs
        - Provide specific, actionable suggestions
        - Maintain an encouraging and supportive tone
        - Use web search when current information is needed
        - Format your responses clearly with headings and lists when helpful
        
        Start conversations by asking what writing project they're working on!
        """),
    markdown=True,
)

if __name__ == "__main__":
    print("🔍 I can research topics, help brainstorm, edit text, and more!")
    print("✏️ Type 'exit', 'quit', or 'bye' to end our session.\n")

    writing_assistant.cli_app(
        input="Hello! What writing project are you working on today? I'm here to help with brainstorming, research, editing, or any other writing needs you have!",
        user="Writer",
        emoji="✍️",
        stream=True,
    )

    ###########################################################################
    # ASYNC CLI APP
    ###########################################################################
    # import asyncio

    # asyncio.run(writing_assistant.acli_app(
    #     input="Hello! What writing project are you working on today? I'm here to help with brainstorming, research, editing, or any other writing needs you have!",
    #     user="Writer",
    #     emoji="✍️",
    #     stream=True,
    # ))
