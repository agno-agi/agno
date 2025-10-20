"""
Create user memories with an Agent by providing a either text or a list of messages.
"""

from agno.culture.manager import CultureManager
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# Setup the SQLite database
db = SqliteDb(db_file="tmp/demo.db")

culture = CultureManager(model=Claude(id="claude-sonnet-4-5"), db=db)

culture.create_notion(message="We should live in peace and harmony with each other.")


# artifacts = culture.get_all_artifacts()
# print("Artifacts:")
# pprint(artifacts)
