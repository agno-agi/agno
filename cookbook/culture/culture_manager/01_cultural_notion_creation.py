"""
Create user memories with an Agent by providing a either text or a list of messages.
"""

from agno.culture.manager import CultureManager
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# Setup the SQLite database
db = SqliteDb(db_file="tmp/demo.db")

culture_manager = CultureManager(model=Claude(id="claude-sonnet-4-5"), db=db)

culture_manager.create_cultural_notions(
    message="Technical users prefer direct answers with code snippets first"
)

cultural_notions = culture_manager.get_all_notions()
print("Cultural notions:")
print(cultural_notions)
