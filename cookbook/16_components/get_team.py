"""
This cookbook demonstrates how to save a team to a PostgreSQL database.
"""

from agno.db.postgres import PostgresDb
from agno.team.team import get_team_by_id, get_teams  # noqa: F401

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

team = get_team_by_id(db=db, id="content-team")

if team:
    team.print_response("Write about the history of the internet.", stream=True)
else:
    print("Team not found")

# You can also get all teams from the database
# teams = get_teams(db=db)
# for team in teams:
#     print(team)
