"""
Add cultural knowledge directly to the database or generate cultural knowledge from a message and add it to the database.
"""

from agno.culture.manager import CulturalKnowledge, CultureManager
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# Setup the SQLite database
db = SqliteDb(db_file="tmp/demo.db")

culture_manager = CultureManager(model=Claude(id="claude-sonnet-4-5"), db=db)

# Add cultural knowledge directly to the database
culture_manager.add_cultural_knowledge(
    knowledge=CulturalKnowledge(
        name="Interaction culture",
        content="Be polite and friendly to the user",
    )
)

# Generate cultural knowledge from a message and add it to the database
culture_manager.create_cultural_knowledge(
    message="Technical users prefer direct answers with code snippets first"
)

# Get all cultural knowledge from the database
cultural_knowledge = culture_manager.get_all_knowledge()
print("Cultural knowledge:")
print(cultural_knowledge)
