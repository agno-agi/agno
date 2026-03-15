"""
Docs PR Agent — Workflow
========================
Finds the most recent closed PR in agno-agi/agno with the "docs-needed" label,
analyzes its changes, and creates a corresponding documentation PR in agno-agi/docs.

Uses a sequential Workflow with specialized agents for each step:
1. PR Discovery — find and analyze the source PR
2. Docs Research — explore the docs repo structure and conventions
3. Docs Creation — create branch and write documentation files
4. PR & Cleanup — open the docs PR and remove the label

Prerequisites:
- GITHUB_ACCESS_TOKEN env var with repo scope
- ANTHROPIC_API_KEY env var

Usage:
    .venvs/demo/bin/python libs/agno/agno/docs_pr_agent.py
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.github import GithubTools
from agno.workflow import Step, Workflow
from agno.os import AgentOS
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Shared model
# ---------------------------------------------------------------------------
model = Claude(id="claude-opus-4-20250514")

# ---------------------------------------------------------------------------
# Tools — each agent gets only the tools it needs
# ---------------------------------------------------------------------------
read_tools = GithubTools(
    include_tools=[
        "search_issues_and_prs",
        "get_pull_request_with_details",
        "get_pull_request_changes",
    ]
)

docs_read_tools = GithubTools(
    include_tools=[
        "get_file_content",
        "get_directory_content",
    ]
)

write_tools = GithubTools(
    include_tools=[
        "create_branch",
        "create_file",
        "update_file",
        "get_file_content",
        "get_directory_content",
    ]
)

pr_tools = GithubTools(
    include_tools=[
        "create_pull_request",
        "remove_label_from_issue",
    ]
)

# ---------------------------------------------------------------------------
# Step 1: PR Discovery — find and analyze the source PR
# ---------------------------------------------------------------------------
pr_discovery_agent = Agent(
    name="PR Discovery",
    model=model,
    tools=[read_tools],
    instructions=[
        "You find and analyze closed PRs with the docs-needed label in agno-agi/agno.",
        "Focus on understanding WHAT changed and WHY — the PR title, description, and key code changes.",
        "For large diffs, focus on public API changes, new features, and user-facing behavior.",
    ],
)

pr_discovery_step = Step(
    name="PR Discovery",
    agent=pr_discovery_agent,
    description="Find the most recent closed PR with docs-needed label and analyze its changes",
)

# ---------------------------------------------------------------------------
# Step 2: Docs Research — explore the docs repo structure
# ---------------------------------------------------------------------------
docs_research_agent = Agent(
    name="Docs Researcher",
    model=model,
    tools=[docs_read_tools],
    instructions=[
        "You explore the agno-agi/docs repo to understand its structure and conventions.",
        "Browse the directory tree, read a few existing doc files to learn the format and style.",
        "Report back the directory structure, file format (MDX, MD, etc), and any naming conventions.",
    ],
)

docs_research_step = Step(
    name="Docs Research",
    agent=docs_research_agent,
    description="Explore agno-agi/docs repo structure, conventions, and file format",
)

# ---------------------------------------------------------------------------
# Step 3: Docs Creation — create branch and write doc files
# ---------------------------------------------------------------------------
docs_creation_agent = Agent(
    name="Docs Creator",
    model=model,
    tools=[write_tools],
    instructions=[
        "You create documentation files in agno-agi/docs based on the PR analysis and docs structure "
        "provided by previous steps.",
        "Create a branch named 'docs/agno-pr-{pr_number}' in agno-agi/docs.",
        "Write documentation files that match the existing style and conventions of the docs repo.",
        "Use clear commit messages referencing the source PR: 'docs: add documentation for agno-agi/agno#{pr_number}'.",
        "If a branch already exists (create_branch fails), note it and continue writing files to it.",
    ],
)

docs_creation_step = Step(
    name="Docs Creation",
    agent=docs_creation_agent,
    description="Create a branch in agno-agi/docs and write documentation files",
)

# ---------------------------------------------------------------------------
# Step 4: PR & Cleanup — open the docs PR and remove the label
# ---------------------------------------------------------------------------
pr_cleanup_agent = Agent(
    name="PR & Cleanup",
    model=model,
    tools=[pr_tools],
    instructions=[
        "You create a pull request in agno-agi/docs and clean up labels on the source PR.",
        "The PR title should be: 'docs: {brief description from source PR}'.",
        "The PR body should include a summary of docs added and a link to the source PR.",
        "Base branch is 'main', head branch is 'docs/agno-pr-{pr_number}'.",
        "After creating the docs PR, remove the 'docs-needed' label from the source PR in agno-agi/agno.",
        "Print a final summary with the source PR info, docs PR URL, and files created.",
    ],
)

pr_cleanup_step = Step(
    name="PR & Cleanup",
    agent=pr_cleanup_agent,
    description="Create the docs PR in agno-agi/docs and remove the docs-needed label from the source PR",
)

# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
docs_workflow = Workflow(
    name="Docs PR Workflow",
    description="Find docs-needed PRs, analyze changes, create documentation PRs",
    steps=[
        pr_discovery_step,
        docs_research_step,
        docs_creation_step,
        pr_cleanup_step,
    ],
    db=db,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example app for docs workflow",
    workflows=[docs_workflow],
    scheduler=True,
    scheduler_poll_interval=15,
    db=db,
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="docs-workflow:app", reload=True)


# # ---------------------------------------------------------------------------
# # Run
# # ---------------------------------------------------------------------------
# if __name__ == "__main__":
#     docs_workflow.print_response(
#         Find the most recent closed PR in agno-agi/agno with the 'docs-needed' label. 
#         Use search_issues_and_prs with query='', state='closed', type_filter='pr', 
#         repo='agno-agi/agno', label='docs-needed', per_page=1. 
#         Then analyze its changes, explore the docs repo structure, create documentation, 
#         and open a PR in agno-agi/docs.
#         stream=True,
#     )
