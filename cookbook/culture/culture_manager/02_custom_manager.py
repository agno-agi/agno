"""
Create cultural knowledge with a custom CultureManager.
"""

import inspect
import sys

from agno.culture import CultureManager
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

print("Class repr:", CultureManager)
print("Module path:", CultureManager.__module__)
print("File path:", inspect.getsourcefile(CultureManager))
print("Init signature:", inspect.signature(CultureManager.__init__))


# Setup the SQLite database
db = SqliteDb(db_file="tmp/demo.db")

CULTURE_MANAGER_SYSTEM_MESSAGE = """
Only capture cultural knowledge releated to users preference for food and cooking.
"""

culture_manager = CultureManager(
    model=Claude(id="claude-sonnet-4-5"),
    system_message=CULTURE_MANAGER_SYSTEM_MESSAGE,
    db=db,
)

# Generate a cultural knowledge from a message
culture_manager.create_cultural_knowledge(
    message="I love cooking vegetarian ramen. Give me a quick recipe."
)

# Get all cultural knowledge
cultural_knowledge = culture_manager.get_all_knowledge()
print("Cultural knowledge:")
print(cultural_knowledge)
