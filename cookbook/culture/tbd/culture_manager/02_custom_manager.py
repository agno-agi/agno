"""
Create cultural knowledge with a custom Culture Manager. You can provide a custom system message to the Culture Manager to capture the cultural knowledge you want to capture.
"""

from agno.culture import CultureManager
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# Setup the SQLite database
db = SqliteDb(db_file="tmp/demo.db")

CULTURE_MANAGER_SYSTEM_MESSAGE = """
Only capture cultural knowledge releated to users preference for food and cooking.
"""

# Define the Culture Manager
culture_manager = CultureManager(
    model=Claude(id="claude-sonnet-4-5"),
    system_message=CULTURE_MANAGER_SYSTEM_MESSAGE,
    db=db,
)

# Generate cultural knowledge from a message and add it to the database
culture_manager.create_cultural_knowledge(
    message="I love cooking vegetarian ramen. Give me a quick recipe."
)

# Get all cultural knowledge from the database
cultural_knowledge = culture_manager.get_all_knowledge()
print("Cultural knowledge:")
print(cultural_knowledge)
