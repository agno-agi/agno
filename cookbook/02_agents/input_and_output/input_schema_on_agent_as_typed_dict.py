from typing import List, Optional, TypedDict

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools


# Define a TypedDict schema
class ResearchTopicDict(TypedDict):
    topic: str
    focus_areas: List[str]
    target_audience: str
    sources_required: int


# Optional: Define a TypedDict with optional fields
class ResearchTopicWithOptionals(TypedDict, total=False):
    topic: str
    focus_areas: List[str]
    target_audience: str
    sources_required: int
    priority: Optional[str]


# Create agent with TypedDict input schema
hackernews_agent = Agent(
    name="Hackernews Agent with TypedDict",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
    input_schema=ResearchTopicDict,
)

# with valid input
print("=== Testing TypedDict Input Schema ===")
hackernews_agent.print_response(
    input={
        "topic": "AI",
        "focus_areas": ["Machine Learning", "LLMs", "Neural Networks"],
        "target_audience": "Developers",
        "sources_required": 5,
    }
)

# with optional fields
optional_agent = Agent(
    name="Hackernews Agent with Optional Fields",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    input_schema=ResearchTopicWithOptionals,
)

print("\n=== Testing TypedDict with Optional Fields ===")
optional_agent.print_response(
    input={
        "topic": "Blockchain",
        "focus_areas": ["DeFi", "NFTs"],
        "target_audience": "Investors",
        # sources_required is optional, omitting it
        "priority": "high",
    }
)

# Should raise an error - missing required field
try:
    hackernews_agent.print_response(
        input={
            "topic": "AI",
            # Missing required fields: focus_areas, target_audience, sources_required
        }
    )
except ValueError as e:
    print("\n=== Expected Error for Missing Fields ===")
    print(f"Error: {e}")

# This will raise an error - unexpected field
try:
    hackernews_agent.print_response(
        input={
            "topic": "AI",
            "focus_areas": ["Machine Learning"],
            "target_audience": "Developers",
            "sources_required": 5,
            "unexpected_field": "value",  # This field is not in the TypedDict
        }
    )
except ValueError as e:
    print("\n=== Expected Error for Unexpected Field ===")
    print(f"Error: {e}")
