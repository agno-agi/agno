from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.crawl4ai import Crawl4aiTools

# # Example 1: Basic usage
agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    tools=[Crawl4aiTools(use_pruning=True)],
    instructions="You are a helpful assistant that can crawl the web and extract information. Use have access to crawl4ai tools to extract information from the web.",
)
agent.print_response(
    "Give me a detailed summary of the Agno project from https://github.com/agno-agi/agno and what are its main features?"
)

# Example 2: Extract main content only (remove navigation, ads, etc.)
# agent_clean = Agent(tools=[Crawl4aiTools(use_pruning=True)], show_tool_calls=True)
# agent_clean.print_response(
#     "Get the History from https://en.wikipedia.org/wiki/Python_(programming_language)"
# )

# Example 3: Search for specific content on a page
# agent_search = Agent(
#     instructions="You are a helpful assistant that can crawl the web and extract information. Use have access to crawl4ai tools to extract information from the web.",
#     tools=[Crawl4aiTools()],
#     show_tool_calls=True,
# )
# agent_search.print_response(
#     "What are the diferent Techniques used in AI? https://en.wikipedia.org/wiki/Artificial_intelligence"
# )

# Example 4: Multiple URLs with clean extraction
# agent_multi = Agent(
#     tools=[Crawl4aiTools(use_pruning=True, headless=False)], show_tool_calls=True
# )
# agent_multi.print_response(
#     "Compare the main content from https://en.wikipedia.org/wiki/Artificial_intelligence and https://en.wikipedia.org/wiki/Machine_learning"
# )
