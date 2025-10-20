"""
Create cultural knowledge to use with your Agents.

This minimal example demonstrates how to use Agno's `CultureManager`
to create and persist shared cultural knowledge that can be used with your Agents.

Cultural knowledge represents reusable insights, rules, and values that
Agents can reference to stay consistent in tone, reasoning, and best practices.
"""

from agno.culture.manager import CultureManager
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
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
    model=Claude(id="claude-sonnet-4-5"),
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
    "When explaining technical concepts, start with a short, working example "
    "before diving into details or theory. Developers respond best to concrete, "
    "runnable snippets they can try immediately. Follow up with reasoning, "
    "trade-offs, and references. Avoid long intros or abstract definitions."
)

culture_manager.create_cultural_knowledge(message=message)

# ---------------------------------------------------------------------------
# Step 4. Retrieve and inspect the stored cultural knowledge
# ---------------------------------------------------------------------------
cultural_knowledge = culture_manager.get_all_knowledge()

print("\n=== Cultural Knowledge Entries ===")
pprint(cultural_knowledge)
