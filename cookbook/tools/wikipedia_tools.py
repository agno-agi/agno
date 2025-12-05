from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.tools.wikipedia import WikipediaTools

# Example 1: Basic Wikipedia search (without knowledge base)
agent = Agent(
    tools=[
        WikipediaTools(
            enable_search_wikipedia=True,
            enable_search_wikipedia_and_update_knowledge_base=False,
        )
    ]
)

# Example 2: Enable all Wikipedia functions
agent_all = Agent(tools=[WikipediaTools(all=True)])

# Example 3: Wikipedia with knowledge base integration
knowledge_base = Knowledge()
kb_agent = Agent(
    tools=[
        WikipediaTools(
            knowledge=knowledge_base,
            enable_search_wikipedia=False,
            enable_search_wikipedia_and_update_knowledge_base=True,
        )
    ]
)

# Test the agents
agent.print_response("Search Wikipedia for 'artificial intelligence'", markdown=True)
kb_agent.print_response(
    "Find information about machine learning and add it to knowledge base",
    markdown=True,
)
