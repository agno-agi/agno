from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    tools=[
        WebSearchTools(
            stop_after_tool_call_tools=["web_search"],
            show_result_tools=["web_search"],
        )
    ],
)

agent.print_response("Whats the latest about gpt 5?", markdown=True)
