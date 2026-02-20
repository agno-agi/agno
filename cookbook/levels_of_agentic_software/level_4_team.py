"""
Level 4: Multi-agent Team
===========================
Split responsibilities across specialized agents coordinated by a team leader.
Coder writes, Reviewer critiques, Tester validates.

This takes a different architectural path from the single-agent levels:
- Multiple specialized agents with distinct roles
- A Team leader that coordinates and synthesizes

Honest caveat: Multi-agent teams are powerful but less predictable than
single agents. The team leader is an LLM making delegation decisions --
sometimes brilliantly, sometimes not. For production automation, prefer
explicit workflows. Teams shine in human-supervised settings.

Run standalone:
    python cookbook/levels_of_agentic_software/level_4_team.py

Run via Agent OS:
    python cookbook/levels_of_agentic_software/run.py
    Then visit https://os.agno.com and select "L4 Coding Team"

Example prompt:
    "Build a stack data structure with full test coverage"
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from agno.tools.coding import CodingTools

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
db = SqliteDb(db_file=str(WORKSPACE / "agents.db"))

# ---------------------------------------------------------------------------
# Coder Agent -- writes code
# ---------------------------------------------------------------------------
coder = Agent(
    name="L4 Coder",
    role="Write code based on requirements",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="""\
You are a senior developer. Write clean, well-documented code.

## Workflow
1. Understand the requirements
2. Write the implementation with type hints and docstrings
3. Save the code to a file

## Rules
- Write production-quality code
- Include type hints and Google-style docstrings
- Handle edge cases
- No emojis\
""",
    tools=[CodingTools(base_dir=WORKSPACE, all=True)],
    db=db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Reviewer Agent -- reviews code (read-only tools)
# ---------------------------------------------------------------------------
reviewer = Agent(
    name="L4 Reviewer",
    role="Review code for quality, bugs, and best practices",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="""\
You are a senior code reviewer. Provide thorough, constructive reviews.

## Workflow
1. Read the code files
2. Check for bugs, edge cases, and style issues
3. Provide specific, actionable feedback

## Review Checklist
- Correctness: Does it handle edge cases?
- Style: Consistent naming, proper type hints?
- Documentation: Clear docstrings?
- Performance: Any obvious inefficiencies?

## Rules
- Be specific -- reference line numbers and code
- Suggest fixes, not just problems
- Acknowledge what's done well
- No emojis\
""",
    tools=[
        CodingTools(
            base_dir=WORKSPACE,
            enable_read_file=True,
            enable_grep=True,
            enable_find=True,
            enable_ls=True,
            enable_write_file=False,
            enable_edit_file=False,
            enable_run_shell=False,
        ),
    ],
    db=db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Tester Agent -- writes and runs tests
# ---------------------------------------------------------------------------
tester = Agent(
    name="L4 Tester",
    role="Write and run tests for the code",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="""\
You are a QA engineer. Write thorough tests and run them.

## Workflow
1. Read the implementation code
2. Write tests covering normal cases, edge cases, and error cases
3. Save tests to a test file
4. Run the tests and report results

## Rules
- Test both happy path and edge cases
- Test error handling
- Use assert statements with clear messages
- No emojis\
""",
    tools=[CodingTools(base_dir=WORKSPACE, all=True)],
    db=db,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
l4_coding_team = Team(
    name="L4 Coding Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[coder, reviewer, tester],
    instructions="""\
You lead a coding team with a Coder, Reviewer, and Tester.

## Process

1. Send the task to the Coder to implement
2. Send the code to the Reviewer for feedback
3. If the Reviewer finds issues, send back to the Coder to fix
4. Send the final code to the Tester to write and run tests
5. Synthesize results into a final report

## Output Format

Provide a summary with:
- **Implementation**: What was built and key design decisions
- **Review**: Key findings from the code review
- **Tests**: Test results and coverage
- **Status**: Overall pass/fail assessment\
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
    l4_coding_team.print_response(
        "Build a Stack data structure in Python with push, pop, peek, "
        "is_empty, and size methods. Include proper error handling for "
        "operations on an empty stack. Save to stack.py and write tests "
        "in test_stack.py.",
        stream=True,
    )
