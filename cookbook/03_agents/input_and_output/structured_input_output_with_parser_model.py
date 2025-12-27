from typing import List

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel, Field
from rich.pretty import pprint


# Define your input schema
class ResearchTopic(BaseModel):
    topic: str
    sources_required: int = Field(description="Number of sources required", default=5)


# Define your output schema
class ResearchOutput(BaseModel):
    summary: str = Field(..., description="Executive summary of the research findings")
    insights: List[str] = Field(..., description="Key insights discovered from posts")
    top_stories: List[str] = Field(
        ..., description="Most relevant and popular stories found"
    )
    technologies: List[str] = Field(
        ..., description="Technologies, tools, or frameworks mentioned"
    )
    sources: List[str] = Field(..., description="Links to the most relevant posts")


# Define your agent
hn_researcher_agent = Agent(
    # Model to use
    model=Claude(id="claude-sonnet-4-0"),
    # Tools to use
    tools=[HackerNewsTools()],
    instructions="Research hackernews posts for a given topic",
    input_schema=ResearchTopic,
    output_schema=ResearchOutput,
    # Model to use convert the output to the JSON schema
    parser_model=OpenAIChat(id="gpt-5-nano"),
)

# Run the Agent
response = hn_researcher_agent.run(input=ResearchTopic(topic="AI", sources_required=5))

# Print the response
pprint(response.content)
