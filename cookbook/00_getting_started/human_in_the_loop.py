"""
Human in the Loop - Confirm Before Taking Action
================================================
This example shows how to require user confirmation before executing
certain tools. Critical for actions that are irreversible or sensitive.

We'll build on our self-learning agent, and ask for user confirmation before saving a learning.

Key concepts:
- @tool(requires_confirmation=True): Mark tools that need approval
- run_response.active_requirements: Check for pending confirmations
- requirement.confirm() / requirement.reject(): Approve or deny
- agent.continue_run(): Resume execution after decision

Some practical applications:
- Confirming sensitive operations before execution
- Reviewing API calls before they're made
- Validating data transformations
- Approving automated actions in critical systems

Example prompts to try:
- "What's a good P/E ratio for tech stocks? Save that insight."
- "Analyze NVDA and save any insights"
- "What learnings do we have saved?"
"""

import json
from datetime import datetime, timezone

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.models.google import Gemini
from agno.tools import tool
from agno.tools.yfinance import YFinanceTools
from agno.utils import pprint
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.search import SearchType
from rich.console import Console
from rich.prompt import Prompt

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/agents.db")

# ============================================================================
# Knowledge Base for Learnings
# ============================================================================
learnings_kb = Knowledge(
    name="Agent Learnings",
    vector_db=ChromaDb(
        name="learnings",
        collection="learnings",
        path="tmp/chromadb",
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(id="gemini-embedding-001"),
    ),
    max_results=5,
    contents_db=agent_db,
)


# ============================================================================
# Custom Tool: Save Learning (requires confirmation)
# ============================================================================
@tool(requires_confirmation=True)
def save_learning(title: str, learning: str) -> str:
    """
    Save a reusable insight to the knowledge base for future reference.
    This action requires user confirmation before executing.

    Args:
        title: Short descriptive title (e.g., "Tech stock P/E benchmarks")
        learning: The insight to save — be specific and actionable

    Returns:
        Confirmation message
    """
    if not title or not title.strip():
        return "Cannot save: title is required"
    if not learning or not learning.strip():
        return "Cannot save: learning content is required"

    payload = {
        "title": title.strip(),
        "learning": learning.strip(),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    learnings_kb.add_content(
        name=payload["title"],
        text_content=json.dumps(payload, ensure_ascii=False),
        reader=TextReader(),
        skip_if_exists=True,
    )

    return f"Saved: '{title}'"


# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are a Finance Agent that learns and improves over time.

You have two special abilities:
1. Search your knowledge base for previously saved learnings
2. Save new insights using the save_learning tool

## Workflow

1. Check Knowledge First
   - Before answering, search for relevant prior learnings
   - Apply any relevant insights to your response

2. Gather Information
   - Use YFinance tools for market data
   - Combine with your knowledge base insights

3. Save Valuable Insights
   - If you discover something reusable, save it with save_learning
   - The user will be asked to confirm before it's saved
   - Good learnings are specific, actionable, and generalizable

## What Makes a Good Learning

- Specific: "Tech P/E ratios typically range 20-35x" not "P/E varies"
- Actionable: Can be applied to future questions
- Reusable: Useful beyond this one conversation

Don't save: Raw data, one-off facts, or obvious information.\
"""

# ============================================================================
# Create the Agent
# ============================================================================
human_in_the_loop_agent = Agent(
    name="Agent with Human in the Loop",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[
        YFinanceTools(),
        save_learning,
    ],
    knowledge=learnings_kb,
    search_knowledge=True,
    db=agent_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    console = Console()

    # Ask a question that might trigger a save
    run_response = human_in_the_loop_agent.run(
        "What's a healthy P/E ratio for tech stocks? Save that insight."
    )

    # Handle any confirmation requirements
    for requirement in run_response.active_requirements:
        if requirement.needs_confirmation:
            console.print(
                f"\n[bold yellow]🛑 Confirmation Required[/bold yellow]\n"
                f"Tool: [bold blue]{requirement.tool_execution.tool_name}[/bold blue]\n"
                f"Args: {requirement.tool_execution.tool_args}"
            )

            choice = (
                Prompt.ask(
                    "Do you want to continue?",
                    choices=["y", "n"],
                    default="y",
                )
                .strip()
                .lower()
            )

            if choice == "n":
                requirement.reject()
                console.print("[red]❌ Rejected[/red]")
            else:
                requirement.confirm()
                console.print("[green]✅ Approved[/green]")

    # Continue the run with the user's decisions
    run_response = human_in_the_loop_agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )

    pprint.pprint_run_response(run_response)

# ============================================================================
# More Examples
# ============================================================================
"""
Human-in-the-loop patterns:

1. Confirmation for sensitive actions
   @tool(requires_confirmation=True)
   def delete_file(path: str) -> str:
       ...

2. Confirmation for external calls
   @tool(requires_confirmation=True)
   def send_email(to: str, subject: str, body: str) -> str:
       ...

3. Confirmation for financial transactions
   @tool(requires_confirmation=True)
   def place_order(ticker: str, quantity: int, side: str) -> str:
       ...

The pattern:
1. Mark tool with @tool(requires_confirmation=True)
2. Run agent with agent.run()
3. Loop through run_response.active_requirements
4. Check requirement.needs_confirmation
5. Call requirement.confirm() or requirement.reject()
6. Call agent.continue_run() with requirements

This gives you full control over which actions execute.
"""
