"""
Super Agent in Slack, With Each Person Linking Their Own Account
================================================================

Serve Super Agent in Slack under AgentOS authorization. Each person links their
own Slack account to the AgentOS user they sign in as, with
Slack(link_accounts=True), instead of an admin keeping a users= map:

1. Signed in to AgentOS, they create a one-time code: Settings > Profile > Slack
   in the AgentOS UI, or POST /identity-links/slack/codes with their token.
2. They send `link <code>` to the bot in a direct message.

Their token proves who they are and Slack's signed event proves the Slack
account, so nothing is matched by email and any identity provider works.
Everyone who signs in gets the default "member" role, so a linked person can
start Tasks from Slack with no per-user setup.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, PostgreSQL (./cookbook/scripts/run_pgvector.sh)
Sign in with os.agno.com: JWT_ALGORITHM=RS256, JWT_VERIFICATION_KEY=<public key from Settings > OS Security>, OS_ADMIN=<your token's sub, e.g. your email>; link from Settings > Profile > Slack
Or sign in locally: JWT_VERIFICATION_KEY=<any 32+ characters>; run the printed curl command to get a code
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/link_accounts.py (--check builds it and creates a code without serving)
Try in Slack: message the bot before linking (refused, with how to link); DM it `link <code>`; then "Start the task <printed id>", and later "What is its status?"
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, mpim:history, channels:history, groups:history
"""

import asyncio
import os
import sys
import time

import jwt
from agno.company.manager import CompanyManager
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.os.interfaces.slack import Slack
from agno.registry import Registry
from agno.workflow import Step, StepInput, StepOutput, Workflow

PORT = 7777
# HS256 verifies the example's own local tokens; RS256 with the os.agno.com key verifies its sign-ins
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
# Who the local token signs in as; with os.agno.com the token's own sub is used
LOCAL_USER = os.getenv("LOCAL_USER", "alice")

# What every signed-in person may do: talk to Super Agent and start and follow Tasks
MEMBER_SCOPES = [
    "teams:superagent:run",
    "teams:superagent:read",
    "sessions:read",
    "products:read",
    "projects:read",
    "tasks:read",
    "tasks:write",
    "wiki:read",
    "workflows:investigator:run",
    "workflows:investigator:read",
]


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is required for this example")
    return value


# ---------------------------------------------------------------------------
# A slow executor for the Task
# ---------------------------------------------------------------------------
async def investigate(step_input: StepInput) -> StepOutput:
    await asyncio.sleep(int(os.getenv("TASK_SECONDS", "30")))
    return StepOutput(
        content="Findings: the nightly export fails because the job uses the old IAM role."
    )


db = PostgresDb(
    id="slack-link-accounts-db",
    db_url=os.getenv("COMPANY_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="slack_link_accounts",
)
investigator = Workflow(
    id="investigator",
    name="Investigator",
    description="Slow investigation executor for Tasks started from Slack.",
    db=db,
    steps=[Step(name="investigate", executor=investigate)],
)
registry = Registry(workflows=[investigator])
model = OpenAIResponses(id="gpt-5.6-luna")

# ---------------------------------------------------------------------------
# Create the AgentOS
# ---------------------------------------------------------------------------

# A Slack message carries no token, so a linked person runs with the roles stored here
authz = Authorization(
    verification_keys=[required_env("JWT_VERIFICATION_KEY")], algorithm=ALGORITHM
)
authz.define_role("member", MEMBER_SCOPES, default=True)
# The person running the example administers it: the AgentOS UI needs more than the member role.
# seed() grants admin while nobody holds it, replacing the member role a first sign-in gave them
authz.define_role("admin", ["agent_os:admin"])
if os.getenv("OS_ADMIN"):
    authz.seed(admin=os.environ["OS_ADMIN"])

agent_os = AgentOS(
    id="slack-link-accounts-os",
    description="Super Agent in Slack, with each person linking their own account.",
    db=db,
    registry=registry,
    workflows=[investigator],
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db),
    authorization=authz,
    # Each person is added on their first sign-in, with the default role
    user_directory=True,
)
# The manager exists only once AgentOS is constructed
agent_os.interfaces.append(Slack(team=agent_os.manager, link_accounts=True))
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# A Task a person has already accepted
# ---------------------------------------------------------------------------
def create_accepted_task() -> str:
    # The registry is how the Company checks that the Task's executor exists
    company = CompanyManager(db, registry=registry)
    product = company.create(name="Billing")
    project = company.create_project(product_id=product["id"], name="Export failures")
    company.transition_project(
        project_id=project["id"], target="active", reason="Approved"
    )
    task = company.create_task(
        product_id=product["id"],
        project_id=project["id"],
        title="Investigate the nightly export failure",
        brief="Find why the nightly billing export to S3 fails with access denied.",
    )
    company.transition_task(
        task_id=task["id"],
        target="ready",
        reason="Approved investigation",
        executor_type="workflow",
        executor_id="investigator",
    )
    return task["id"]


def local_token() -> str:
    """A token for LOCAL_USER, standing in for the one a frontend gets at sign-in."""
    claims = {"sub": LOCAL_USER, "exp": int(time.time()) + 3600}
    return jwt.encode(claims, required_env("JWT_VERIFICATION_KEY"), algorithm="HS256")


def check() -> None:
    """Create a link code as LOCAL_USER and confirm the default role lets them start a Task."""
    from agno.os.interfaces.slack.security import resolve_principal_authorization
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        "/identity-links/slack/codes",
        headers={"Authorization": f"Bearer {local_token()}"},
    )
    response.raise_for_status()
    print(response.json()["instructions"])

    async def allowed() -> None:
        # What a Slack message from a linked LOCAL_USER runs with
        authority = await resolve_principal_authorization(
            app, LOCAL_USER, "teams", "superagent"
        )
        await authority.arequire("tasks", "write")
        await authority.arequire("workflows", "run", "investigator")

    asyncio.run(allowed())
    print(f"{LOCAL_USER} may run Super Agent and start the investigator Task.")


# ---------------------------------------------------------------------------
# Run the AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
        sys.exit(0)
    task_id = create_accepted_task()
    if ALGORITHM == "HS256":
        how = (
            f"Get a link code for '{LOCAL_USER}':\n\n"
            f"  curl -s -X POST http://localhost:{PORT}/identity-links/slack/codes "
            f'-H "Authorization: Bearer {local_token()}"\n'
        )
    else:
        how = "Get a link code in the AgentOS UI: Settings > Profile > Slack.\n"
    print(
        f"\n{how}\nThen DM the bot `link <code>`, and ask it: Start the task {task_id}\n",
        flush=True,
    )
    agent_os.serve(app=app, port=PORT, reload=False)
