"""
Research Team
==============

Seek + Scout working together on deep research tasks. The team leader
coordinates two agents to produce comprehensive research from external sources
and internal knowledge.

Test:
    python -m teams.research.team
"""

from agents.scout import scout
from agents.seek import seek
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from db import get_postgres_db

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
research_team = Team(
    id="research-team",
    name="Research Team",
    model=OpenAIResponses(id="gpt-5.2"),
    db=get_postgres_db(contents_table="research_team_contents"),
    members=[seek, scout],
    instructions=[
        "You lead a research team with two specialists:",
        "- Seek: Deep web researcher. Use for external research, company analysis, people research, and topic deep-dives.",
        "- Scout: Enterprise knowledge navigator. Use for finding information in internal documents and knowledge bases.",
        "",
        "For research tasks:",
        "1. Break the research question into dimensions (external facts, internal knowledge)",
        "2. Delegate each dimension to the appropriate specialist",
        "3. Synthesize their findings into a comprehensive, well-structured report",
        "4. Cross-reference findings across agents to identify patterns and contradictions",
        "",
        "Always produce a structured report with:",
        "- Executive Summary",
        "- Key Findings (organized by dimension)",
        "- Sources and confidence levels",
        "- Open questions and recommended next steps",
    ],
    show_members_responses=True,
    markdown=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    test_cases = [
        "Research Anthropic - the AI company. What do we know about them, "
        "their products, key people, and recent developments?",
        "Research OpenAI and summarize products, key people, and recent enterprise moves.",
    ]
    for idx, prompt in enumerate(test_cases, start=1):
        print(f"\n--- Research team test case {idx}/{len(test_cases)} ---")
        print(f"Prompt: {prompt}")
        research_team.print_response(prompt, stream=True)
