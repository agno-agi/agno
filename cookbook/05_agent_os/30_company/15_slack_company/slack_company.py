"""CompanyOS in verified Slack threads with durable intake and result delivery.

Set the variables documented in README.md before serving this example. Importing
it configures providers; running requests may call those providers and Slack.
"""

import json
from os import environ

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.os.interfaces.slack import Slack, SlackCompany

# Each configured channel is an explicit shared destination for generated replies.
db = PostgresDb(db_url=environ["DATABASE_URL"], id="company-slack-db")
model = OpenAIResponses(id="gpt-5.6-luna")
writer = Agent(
    id="writer",
    model=model,
    db=db,
    instructions="Produce the requested written deliverable.",
)
users = json.loads(environ["SLACK_PLATFORM_USERS"])
authorization = Authorization(
    db=db, verification_keys=[environ["JWT_SECRET"]], algorithm="HS256"
)
# Existing deployments should assign their established roles to mapped users.
# This example role has only this Company's lifecycle and writer permissions.
authorization.define_role(
    "company-delegator",
    [
        "teams:super-agent:run",
        "teams:super-agent:read",
        "agents:company-manager:run",
        "products:read",
        "products:write",
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
        "company:read",
        "wiki:read",
        "sessions:read",
        "agents:writer:run",
        "agents:writer:read",
    ],
)
for principal in set(users.values()):
    authorization.assign(principal, "company-delegator")

agent_os = AgentOS(
    id="company-slack",
    db=db,
    manager=OSManager(model=model, access_docs=False),
    company=CompanyConfig(model=model),
    agents=[writer],
    authorization=authorization,
    user_isolation=True,
    queue=QueueConfig(durable=True),
    scheduler=True,
    interfaces=[
        Slack(
            company=SlackCompany(
                workspace_id=environ["SLACK_WORKSPACE_ID"],
                app_id=environ["SLACK_APP_ID"],
                bot_user_id=environ["SLACK_BOT_USER_ID"],
                users=users,
                channels=tuple(environ["SLACK_CHANNEL_IDS"].split(",")),
                agent_os_url=environ["COMPANY_UI_URL"],
            )
        )
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="slack_company:app", reload=False)
