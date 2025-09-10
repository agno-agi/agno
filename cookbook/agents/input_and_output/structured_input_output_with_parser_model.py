from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel, Field


class ResearchTopic(BaseModel):
    """Structured research topic with specific requirements"""

    topic: str
    focus_areas: List[str] = Field(description="Specific areas to focus on")
    target_audience: str = Field(description="Who this research is for")
    sources_required: int = Field(description="Number of sources needed", default=5)


class HackerNewsResearch(BaseModel):
    """Structured output for Hackernews research results"""
    
    research_summary: str = Field(..., description="Executive summary of the research findings")
    key_insights: List[str] = Field(..., description="Main insights discovered from Hackernews posts")
    trending_topics: List[str] = Field(..., description="Currently trending topics related to the research")
    top_stories: List[str] = Field(..., description="Most relevant and popular stories found")
    discussion_highlights: List[str] = Field(..., description="Notable comments or discussions")
    technologies_mentioned: List[str] = Field(..., description="Technologies, tools, or frameworks mentioned")
    industry_sentiment: str = Field(..., description="Overall sentiment and mood of the community")
    actionable_takeaways: List[str] = Field(..., description="Practical insights the target audience can act on")
    source_links: List[str] = Field(..., description="Links to the most relevant Hackernews posts")
    confidence_score: int = Field(..., ge=1, le=10, description="Research confidence level (1=low, 10=high)")


# Define agents
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
    input_schema=ResearchTopic,
    output_schema=HackerNewsResearch,
    parser_model=OpenAIChat(id="gpt-4.1"),
)

# Pass a dict that matches the input schema
hackernews_agent.print_response(
    input={
        "topic": "AI",
        "focus_areas": ["AI", "Machine Learning"],
        "target_audience": "Developers",
        "sources_required": 5,
    }
)