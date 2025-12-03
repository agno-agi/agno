from pprint import pprint

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
    ),
    db=InMemoryDb(),
    tools=[
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }
    ],
    markdown=True,
)

agent.print_response("What's the latest with Anthropic?", stream=True)

# Show the web search metrics
print("---" * 5, "Web Search Metrics", "---" * 5)
pprint(agent.get_last_run_output().metrics)
print("---" * 20)
