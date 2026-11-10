"""Save company details through Super Agent, then inspect them in a new chat.

Run this server and connect the AgentOS UI to http://localhost:7777.
In a Super Agent chat, say: "Our company is Acme. We build warehouse robots."
In a new chat, ask: "What does our company do?"
Then try: "Rename our company to Acme Robotics; keep the description."
Restart with a different CompanyConfig name: the saved edit takes precedence.

Sending chat messages makes live model calls and requires OPENAI_API_KEY.
This local example has no authentication; authenticated deployments require
company:write for edits and company:read to include details in manager context.
"""

from os import getenv

from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
db = PostgresDb(
    db_url=getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")
)
model = OpenAIResponses(id="gpt-5.6-luna")

# -----------------------------------------------------------------------------
# Create AgentOS
# -----------------------------------------------------------------------------
agent_os = AgentOS(
    db=db,
    manager=OSManager(model=model, access_docs=False),
    company=CompanyConfig(name="Example company", model=model),
    telemetry=False,
)
app = agent_os.get_app()

# -----------------------------------------------------------------------------
# Run AgentOS
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app=app, port=7777)
