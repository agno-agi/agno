"""
Tasks Mode: Sprint Planning with Dependencies
==============================================

Demonstrates autonomous task decomposition with dependencies, blockers, and
iterative execution served via AgentOS.

Inspired by Claude Code's agent teams where teammates claim tasks, track
dependencies, and coordinate through a shared task list.

Key patterns from Claude Code agent teams:
- Task decomposition with explicit dependencies
- Blocked tasks that unblock automatically when dependencies complete
- Members self-claim available work
- Lead synthesizes final output after all tasks complete

Use case: A product team planning and executing a sprint with interconnected
deliverables where some tasks must complete before others can start.

Run with: .venvs/demo/bin/python cookbook/05_agent_os/team_modes/tasks_mode.py
Access at: http://localhost:7777
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team, TeamMode

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------
db = PostgresDb(
    id="team-modes-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Specialist Members
# ---------------------------------------------------------------------------

requirements_analyst = Agent(
    name="Requirements Analyst",
    id="requirements-analyst",
    model=OpenAIChat(id="gpt-5.2"),
    db=db,
    role="Analyze user stories and break them into clear technical requirements",
    instructions=[
        "Extract acceptance criteria from user stories.",
        "Identify edge cases and potential blockers early.",
        "Flag dependencies on external systems or teams.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

backend_engineer = Agent(
    name="Backend Engineer",
    id="backend-engineer",
    model=OpenAIChat(id="gpt-5.2"),
    db=db,
    role="Design and implement API endpoints and data models",
    instructions=[
        "Define API contracts before implementation.",
        "Consider database migrations and rollback strategies.",
        "Document breaking changes that affect frontend.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

frontend_engineer = Agent(
    name="Frontend Engineer",
    id="frontend-engineer",
    model=OpenAIChat(id="gpt-5.2"),
    db=db,
    role="Build UI components and integrate with backend APIs",
    instructions=[
        "Wait for API contracts before starting integration.",
        "Design for loading and error states.",
        "Ensure accessibility compliance.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

qa_engineer = Agent(
    name="QA Engineer",
    id="qa-engineer",
    model=OpenAIChat(id="gpt-5.2"),
    db=db,
    role="Create test plans and validate feature completeness",
    instructions=[
        "Write test cases based on acceptance criteria.",
        "Test edge cases identified in requirements.",
        "Validate integration between frontend and backend.",
    ],
    update_memory_on_run=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Tasks Team with Dependency Management
# ---------------------------------------------------------------------------

sprint_team = Team(
    name="Sprint Execution Team",
    id="sprint-execution-team",
    description="Cross-functional product team with autonomous task decomposition and dependency tracking",
    model=OpenAIChat(id="gpt-5.2"),
    db=db,
    members=[requirements_analyst, backend_engineer, frontend_engineer, qa_engineer],
    mode=TeamMode.tasks,
    max_iterations=15,
    instructions=[
        "You are a sprint lead coordinating a cross-functional product team.",
        "",
        "Task Management Protocol:",
        "1. DECOMPOSE: Break the goal into discrete tasks with clear deliverables",
        "2. DEPENDENCIES: Explicitly declare task dependencies (e.g., frontend depends on API contract)",
        "3. ASSIGN: Match tasks to the most qualified member based on their role",
        "4. SEQUENCE: Ensure blocked tasks wait for their dependencies",
        "5. SYNTHESIZE: After all tasks complete, provide a sprint summary",
        "",
        "Task Naming Convention:",
        "- Use prefixes: [REQ], [API], [UI], [QA] to categorize tasks",
        "- Include estimated complexity: S/M/L",
        "",
        "Dependency Rules:",
        "- API implementation depends on requirements analysis",
        "- UI integration depends on API contract definition",
        "- QA test plan depends on requirements being finalized",
        "- QA execution depends on both API and UI completion",
        "",
        "Mark goal complete only when all tasks reach terminal state.",
    ],
    markdown=True,
    show_members_responses=True,
    share_member_interactions=True,
    update_memory_on_run=True,
)

# ---------------------------------------------------------------------------
# AgentOS Setup
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    description="Sprint Execution with Tasks Mode - Autonomous task decomposition and dependency management",
    agents=[requirements_analyst, backend_engineer, frontend_engineer, qa_engineer],
    teams=[sprint_team],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    Access the API at: http://localhost:7777
    View configuration at: http://localhost:7777/config

    Example sprint goal to try:
    "Implement user notification preferences with email, push, and in-app options.
    Include quiet hours feature and frequency preview. Backend deadline: Wednesday, Frontend: Thursday."
    """
    agent_os.serve(app="tasks_mode:app", reload=True)
