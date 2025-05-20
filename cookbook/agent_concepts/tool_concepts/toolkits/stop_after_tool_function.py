from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.googlesearch import GoogleSearchTools

agent = Agent(
    model=OpenAIChat(id="gpt-4.5-preview"),
    tools=[
        GoogleSearchTools(
            stop_after_tool_function=["google_search"],
            show_result=True,
        )
    ],
    show_tool_calls=True,
    debug_mode=True,
)

agent.print_response("Whats the latest about gpt 4.5?", markdown=True)
