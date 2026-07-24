"""
Serve a team from another AgentOS through your own AgentOS.

RemoteTeam is a proxy to a team hosted on a remote AgentOS. The remote AgentOS
must mount the RemoteAccess interface and pass the team to it.

Prerequisites:
1. Start the backing server:
   python cookbook/05_agent_os/remote/server.py

   The server will run on http://localhost:7778

2. Set your OPENAI_API_KEY environment variable

Then run this app and talk to the remote team on http://localhost:7777:
   curl -X POST -F "message=Calculate 15 * 23" -F "stream=false" http://localhost:7777/teams/research-team/runs
"""

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.team import RemoteTeam

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Local database for this client OS. Remote team runs execute and persist on the
# backing server's database; this db exists so you can compare what each side records.
db = SqliteDb(id="remote-team-client-db", db_file="tmp/remote_team_client.db")

remote_research_team = RemoteTeam(
    base_url="http://localhost:7778",
    team_id="research-team",
)

agent_os = AgentOS(
    id="remote-team-client",
    description="AgentOS serving a team that lives on a remote AgentOS",
    teams=[remote_research_team],
    db=db,
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="02_remote_team:app", port=7777)
