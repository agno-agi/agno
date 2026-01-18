"""
Manually add cultural knowledge to your Agents.

This example shows how to persist cultural knowledge WITHOUT invoking a model.
Use this to seed cultural knowledge for your Agents and Multi-Agent Teams.

Cultural knowledge represents reusable insights, rules, and values that Agents
can reference to stay consistent in tone, reasoning, and best practices.
"""

from agno.agent import Agent
from agno.culture.manager import CultureManager
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Step 1. Initialize the database used for storing cultural knowledge
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/demo.db")

# ---------------------------------------------------------------------------
# Step 2. Create the Culture Manager (no model needed for manual inserts)
# ---------------------------------------------------------------------------
culture_manager = CultureManager(db=db)

# ---------------------------------------------------------------------------
# Step 3. Manually add cultural knowledge
# ---------------------------------------------------------------------------
# Example: Response Format Standard (short and actionable)
response_format = CulturalKnowledge(
    name="Response Format Standard (Agno)",
    summary="Keep responses concise, scannable, and runnable-first where applicable.",
    categories=["communication", "ux"],
    content=(
        "- Lead with the minimal runnable snippet or example when possible.\n"
        "- Use numbered steps for procedures; keep each step testable.\n"
        "- Prefer metric units and explicit defaults (ports, paths, versions).\n"
        "- End with a short validation checklist."
    ),
    notes=["Derived from repeated feedback favoring actionable answers."],
    metadata={"source": "manual_seed", "version": 1},
)

# Persist the cultural knowledge
culture_manager.add_cultural_knowledge(response_format)

# Optional: show what is stored
print("\n=== Cultural Knowledge (Manual Add) ===")
pprint(culture_manager.get_all_knowledge())

# ---------------------------------------------------------------------------
# Step 4. Initialize the Agent with cultural knowledge enabled
# ---------------------------------------------------------------------------
# The Agent will load shared cultural knowledge and include it in context.
agent = Agent(
    db=db,
    model=Claude(id="claude-sonnet-4-5"),
    add_culture_to_context=True,  # adds culture into the prompt context
    # update_cultural_knowledge=True,  # uncomment to let the agent update culture after runs
)

# (Optional) A/B without culture for contrast:
# agent_no_culture = Agent(model=Claude(id="claude-sonnet-4-5"))

# ---------------------------------------------------------------------------
# Step 5. Ask the Agent to generate a response that benefits from culture
# ---------------------------------------------------------------------------
print("\n=== With Culture ===\n")
agent.print_response(
    "How do I set up a FastAPI service using Docker? ",
    stream=True,
    markdown=True,
)

# (Optional) Run without culture for contrast:
# print("\n=== Without Culture ===\n")
# agent_no_culture.print_response(
#     "How do I set up a FastAPI service using Docker?",
#     stream=True,
#     markdown=True,
# )
