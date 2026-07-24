"""
Customer Support AgentOS: a support agent that talks to the remote coding agent.

The support agent escalates technical problems to the coding agent on the news
agency AgentOS (server.py) and translates its findings for the customer. It is
itself exposed through RemoteAccess, so the coding agent can contact it back for
user-facing context: two agents on different OSes as contacts of each other,
wired purely through RemoteAgent references.

Start the news agency server first: python cookbook/05_agent_os/contacts/server.py
Then run: python cookbook/05_agent_os/contacts/03_support_agent.py
"""

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.contacts import Contact
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.remote_access import RemoteAccess

db = SqliteDb(id="support-db", db_file="tmp/contacts_support.db")

support_agent = Agent(
    name="Customer Support",
    id="customer-support",
    description="Handles customer issues and escalates technical problems.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a customer support agent.",
        "Resolve customer issues with clear, empathetic answers.",
        "Escalate technical problems to your coding agent contact and translate its findings for the customer.",
        "Ask the coding agent to open a GitHub issue for confirmed bugs.",
    ],
    contacts=[
        Contact(
            agent=RemoteAgent(
                base_url="http://localhost:7778", agent_id="coding-agent"
            ),
            instructions="Contact to debug technical problems and open GitHub issues or PRs",
        ),
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="support-os",
    description="Customer support AgentOS, exposed so the coding agent can contact it back",
    agents=[support_agent],
    interfaces=[
        RemoteAccess(
            agents=[support_agent],
        ),
    ],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="03_support_agent:app", access_log=True, port=7779)
