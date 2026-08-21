"""
Coordinate Mode with Per-Call respond_directly

Demonstrates research -> write coordination where the leader:
1. Delegates research with respond_directly=False (results return to the leader)
2. Delegates writing with respond_directly=True so the writer's output is the
   team's final answer — no second leader synthesis turn

This avoids double generation for long-form content and lets the writer's
tokens stream as the final TeamRunContent when stream=True.

See: https://github.com/agno-agi/agno/issues/9171
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
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You are a research specialist.",
        "Provide clear, factual bullet-point findings on the topic.",
        "Keep findings concise so a writer can turn them into an article.",
    ],
)

writer = Agent(
    name="Writer",
    role="Content writer who crafts polished long-form articles",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You are a skilled content writer.",
        "Turn research findings into a well-structured article with headers and clear prose.",
        "Your output is the final deliverable — write it ready for the user.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Research & Writing Team",
    mode=TeamMode.coordinate,
    model=OpenAIResponses(id="gpt-5.5"),
    members=[researcher, writer],
    instructions=[
        "You lead a research and writing team.",
        "First delegate research to the Researcher with respond_directly=False.",
        "Then delegate writing to the Writer with respond_directly=True so their "
        "article is returned directly as the final answer without rewriting it.",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "Write a short article about how RAG (retrieval-augmented generation) works, "
        "covering indexing, retrieval, and generation.",
        stream=True,
    )
