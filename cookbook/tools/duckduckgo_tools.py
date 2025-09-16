from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# Example 1: Enable specific DuckDuckGo functions
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(enable_search=True, enable_news=False)],
)

# Example 2: Enable all DuckDuckGo functions
agent_all = Agent(model=OpenAIChat(id="gpt-4o"), tools=[DuckDuckGoTools(all=True)])

# Example 3: Enable only news search
news_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(enable_search=False, enable_news=True)],
)

# Example 4: Specify the search engine
yandex_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(enable_search=True, enable_news=False, backend="yandex")],
    add_datetime_to_context=True,
)

# Test the agents
agent.print_response("What's the latest about GPT-5?", markdown=True)
# news_agent.print_response(
#     "Find recent news about artificial intelligence", markdown=True
# )
# yandex_agent.print_response("What's happening in AI?", markdown=True)
