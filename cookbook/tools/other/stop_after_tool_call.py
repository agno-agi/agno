from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[
        DuckDuckGoTools(
            stop_after_tool_call_tools=["duckduckgo_search"],
            show_result_tools=["duckduckgo_search"],
        )
    ],
)

agent.print_response("Whats the latest about gpt 5?", markdown=True)
