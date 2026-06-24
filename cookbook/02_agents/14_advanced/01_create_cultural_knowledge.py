"""
01 Create Cultural Knowledge
=============================

Create cultural knowledge to use with your Agents.
"""

from agno.culture.manager import CultureManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Step 1. Initialize the database used for storing cultural knowledge
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/demo.db")

# ---------------------------------------------------------------------------
# Step 2. Create the Culture Manager
# ---------------------------------------------------------------------------
# The CultureManager distills reusable insights into the shared cultural layer
# that your Agents can access for consistent reasoning and behavior.
culture_manager = CultureManager(
    db=db,
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Step 3. Create cultural knowledge from a message
# ---------------------------------------------------------------------------
# You can feed in any insight, principle, or lesson you’d like the system to remember.
# The model will generalize it into structured cultural knowledge entries.
#
# For example:
# - Communication best practices
# - Decision-making patterns
# - Design or engineering principles
#
# Try to phrase inputs as *reusable truths* or *guiding principles*,
# not one-off observations.
message = (
    "All technical guidance should follow the 'Operational Thinking' principle:\n"
    "\n"
    "1. **State the Objective** — What outcome are we trying to achieve and why.\n"
    "2. **Show the Procedure** — List clear, reproducible steps (prefer commands or configs).\n"
    "3. **Surface Pitfalls** — Mention what usually fails and how to detect it early.\n"
    "4. **Define Validation** — How to confirm it’s working (logs, tests, metrics).\n"
    "5. **Close the Loop** — Suggest next iterations or improvements.\n"
    "\n"
    "Keep answers short, structured, and directly actionable. Avoid general theory unless "
    "it informs an operational decision."
)

culture_manager.create_cultural_knowledge(message=message)

# ---------------------------------------------------------------------------
# Step 4. Retrieve and inspect the stored cultural knowledge
# ---------------------------------------------------------------------------
cultural_knowledge = culture_manager.get_all_knowledge()

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n=== Cultural Knowledge Entries ===")
    pprint(cultural_knowledge)
