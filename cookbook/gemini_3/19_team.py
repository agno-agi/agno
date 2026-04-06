"""
Multi-Agent Team - Writer, Editor, and Fact-Checker
=====================================================
Coordinate specialized agents with a team leader. Writer drafts, Editor refines, Fact-Checker verifies.

Key concepts:
- Team: Coordinates multiple agents, each with a specific role
- Team leader: An LLM (typically a stronger model) that delegates to members
- members: List of Agent instances the team can delegate to
- show_members_responses: If True, shows each member's response in the output
- role: A short description of what each member agent does (helps the leader delegate)

Example prompts to try:
- "Write a blog post about the health benefits of Mediterranean diet"
- "Create an article about the future of AI in healthcare"
- "Write a travel guide for visiting Tokyo in cherry blossom season"
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.team.team import Team
from agno.tools.websearch import WebSearchTools
from db import gemini_agents_db

# ---------------------------------------------------------------------------
# Writer Agent: drafts content
# ---------------------------------------------------------------------------
writer_instructions = """\
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
"""

writer = Agent(
    name="Writer",
    # role helps the team leader understand what this agent does
    role="Write engaging blog post drafts",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=writer_instructions,
    tools=[WebSearchTools()],
    db=gemini_agents_db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Editor Agent: reviews and improves (no tools, text-only)
# ---------------------------------------------------------------------------
editor_instructions = """\
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
"""

editor = Agent(
    name="Editor",
    role="Review and improve content for clarity and quality",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=editor_instructions,
    db=gemini_agents_db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Fact-Checker Agent: verifies claims
# ---------------------------------------------------------------------------
fact_checker_instructions = """\
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
"""

fact_checker_member = Agent(
    name="Fact Checker",
    role="Verify factual claims using web search",
    # Uses Gemini's native search for fact-checking
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions=fact_checker_instructions,
    db=gemini_agents_db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
content_team = Team(
    name="Content Team",
    # Team leader uses a stronger model for better delegation decisions
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
    db=gemini_agents_db,
    # Show each member's response in the output
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

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Team patterns:

1. Research team (search + analysis)
   members=[researcher, analyst, summarizer]

2. Code review team (write + review + test)
   members=[coder, reviewer, tester]

3. Creative team (ideate + create + critique)
   members=[brainstormer, creator, critic]

When to use teams vs single agents:
- Single agent: Task is well-defined, one perspective is enough
- Team: Task benefits from multiple specialist perspectives
- Workflow (step 20): Steps must happen in a specific, predictable order

Use cases for music/film/gaming:
- Music: Lyricist + Composer + Producer agents
- Film: Scriptwriter + Director + Continuity Checker agents
- Gaming: Designer + Artist + QA Tester agents
"""
