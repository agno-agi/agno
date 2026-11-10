"""
Basic Coordinate Mode Example

Demonstrates the default `mode=coordinate` where the team leader:
1. Analyzes the user's request
2. Selects the most appropriate member agent(s)
3. Crafts specific tasks for each selected member
4. Synthesizes member responses into a final answer

"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    role="Research specialist who finds and summarizes information",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You are a research specialist.",
        "Provide clear, factual summaries on any topic.",
        "Organize findings with structure and cite limitations.",
    ],
)

writer = Agent(
    name="Writer",
    role="Content writer who crafts polished, engaging text",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You are a skilled content writer.",
        "Transform raw information into well-structured, readable text.",
        "Use headers, bullet points, and clear prose.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Research & Writing Team",
    mode=TeamMode.coordinate,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[researcher, writer],
    instructions=[
        "You lead a research and writing team.",
        "For informational requests, ask the Researcher to gather facts first,",
        "then ask the Writer to polish the findings into a final piece.",
        "Synthesize everything into a cohesive response.",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "Write a brief overview of how large language models are trained, "
        "covering pre-training, fine-tuning, and RLHF.",
        stream=True,
    )
