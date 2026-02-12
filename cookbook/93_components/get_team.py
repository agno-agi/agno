"""
Load Team from Database
=======================

Demonstrates loading a team from the database by ID and running it.
"""

from agno.db.postgres import PostgresDb
from agno.team.team import get_team_by_id, get_teams  # noqa: F401

# ---------------------------------------------------------------------------
# Create Database Client
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Run Team Load Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team = get_team_by_id(db=db, id="content-team")

    if team:
        team.print_response("Write about the history of the internet.", stream=True)
    else:
        print("Team not found")

    # You can also get all teams from the database
    # teams = get_teams(db=db)
    # for team in teams:
    #     print(team)
