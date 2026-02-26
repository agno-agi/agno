"""
19. Multi-Agent Team
====================
Split responsibilities across specialized agents coordinated by a team leader.
Writer drafts, Editor refines, Fact-Checker verifies.

Multi-agent teams are powerful but less predictable than single agents.
The team leader is an LLM making delegation decisions -- sometimes brilliantly,
sometimes not. Teams shine in human-supervised settings.

Run:
    python cookbook/gemini_3/19_team.py

Example prompt:
    "Write a blog post about the health benefits of Mediterranean diet"
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.team.team import Team
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
db = SqliteDb(db_file=str(WORKSPACE / "gemini_agents.db"))

# ---------------------------------------------------------------------------
# Writer Agent -- drafts content
# ---------------------------------------------------------------------------
writer = Agent(
    name="Writer",
    role="Write engaging blog post drafts",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a professional content writer. Write engaging, well-structured blog posts.

## Workflow

1. Research the topic using web search
2. Write a compelling draft with clear structure
3. Include an introduction, body sections, and conclusion

## Rules

- Use clear, accessible language
- Include relevant facts and statistics
- Structure with headers and bullet points where appropriate
- No emojis\
""",
    tools=[WebSearchTools()],
    db=db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Editor Agent -- reviews and improves (no tools, text-only)
# ---------------------------------------------------------------------------
editor = Agent(
    name="Editor",
    role="Review and improve content for clarity and quality",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a senior editor. Review content for quality and suggest improvements.

## Review Checklist

- Clarity: Is the message clear and easy to follow?
- Structure: Is the content well-organized?
- Grammar: Are there any grammatical errors?
- Tone: Is the tone consistent and appropriate?
- Engagement: Will readers find this interesting?

## Rules

- Be specific about what needs improvement
- Suggest concrete rewrites, not vague feedback
- Acknowledge what works well
- No emojis\
""",
    db=db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Fact-Checker Agent -- verifies claims
# ---------------------------------------------------------------------------
fact_checker_member = Agent(
    name="Fact Checker",
    role="Verify factual claims using web search",
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions="""\
You are a fact-checker. Verify claims made in the content.

## Workflow

1. Identify all factual claims in the content
2. Search for evidence supporting or contradicting each claim
3. Flag any unverified or incorrect claims
4. Provide corrections with sources

## Rules

- Check every statistical claim and date
- Provide sources for corrections
- Rate confidence: Verified / Unverified / Incorrect
- No emojis\
""",
    db=db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
content_team = Team(
    name="Content Team",
    model=Gemini(id="gemini-3.1-pro-preview"),
    members=[writer, editor, fact_checker_member],
    instructions="""\
You lead a content creation team with a Writer, Editor, and Fact-Checker.

## Process

1. Send the topic to the Writer to create a draft
2. Send the draft to the Editor for review
3. If the Editor finds issues, send back to the Writer to revise
4. Send the final draft to the Fact-Checker to verify claims
5. Synthesize into a final, polished blog post

## Output Format

Provide the final blog post followed by:
- **Editorial Notes**: Key improvements made during editing
- **Fact-Check Summary**: Verification status of key claims\
""",
    db=db,
    show_members_responses=True,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    content_team.print_response(
        "Write a blog post about the health benefits of Mediterranean diet",
        stream=True,
    )
