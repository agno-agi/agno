"""
Basic Tasks Mode Example

Demonstrates `mode=tasks` where the team leader autonomously:
1. Decomposes the user's goal into discrete tasks
2. Assigns each task to the best member agent
3. Executes tasks sequentially
4. Synthesizes results into a final response

Run: .venvs/demo/bin/python cookbook/03_teams/modes/tasks/01_basic.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.mode import TeamMode
from agno.team.team import Team

# -- Member agents -----------------------------------------------------------

planner = Agent(
    name="Planner",
    role="Creates outlines, plans, and structures for content",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a planning specialist.",
        "Create clear, logical outlines and structures.",
        "Break complex topics into well-organized sections.",
    ],
)

writer = Agent(
    name="Writer",
    role="Writes polished content based on outlines or instructions",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a skilled writer.",
        "Write clear, engaging content based on the provided plan or outline.",
        "Follow the structure given to you.",
    ],
)

editor = Agent(
    name="Editor",
    role="Reviews and improves content for clarity and quality",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are an editor.",
        "Review content for clarity, grammar, and logical flow.",
        "Provide the improved version directly.",
    ],
)

# -- Tasks team --------------------------------------------------------------

team = Team(
    name="Content Pipeline Team",
    mode=TeamMode.tasks,
    model=OpenAIChat(id="gpt-4o"),
    members=[planner, writer, editor],
    instructions=[
        "You are a content pipeline team leader.",
        "For each request:",
        "1. Create a task for the Planner to outline the content.",
        "2. Create a task for the Writer to draft based on the outline.",
        "3. Create a task for the Editor to polish the draft.",
        "Execute tasks in order and provide the final edited content.",
    ],
    show_members_responses=True,
    markdown=True,
    max_iterations=10,
)

# -- Run ---------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "Create a blog post explaining microservices vs monolith architecture "
        "for a technical audience."
    )
