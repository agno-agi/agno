"""
Example showing how to cache team leader model responses.

Run this cookbook twice to see the difference in response time.

The first time should take a while to run.
The second time should be instant.

This demonstrates:
1. Team leader caching (coordination decisions)
2. Member agent caching (individual responses)
3. Two-layer caching architecture
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team

# Create member agents with individual caching
researcher = Agent(
    name="Researcher",
    role="Research and gather information",
    model=OpenAIChat(id="gpt-4o", cache_response=True),
)

writer = Agent(
    name="Writer",
    role="Write clear and engaging content",
    model=OpenAIChat(id="gpt-4o", cache_response=True),
)

# Create team with team leader caching
content_team = Team(
    members=[researcher, writer],
    model=OpenAIChat(id="gpt-4o", cache_response=True),
    markdown=True,
    debug_mode=True,
)

# Should take a while to run the first time, then replay from cache
content_team.print_response("Write a very very very explanation of caching in software")
