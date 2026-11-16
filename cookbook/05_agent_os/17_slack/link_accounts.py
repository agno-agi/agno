"""
Super Agent in Slack Under Authorization
========================================

Serve Super Agent in Slack with AgentOS authorization on, with no users= map.

A Slack message carries no AgentOS token, so Super Agent has to know which AgentOS
user each Slack member is. With Slack(resolve_user_identity=True) and the user
directory, a member is matched on their first message: their confirmed Slack email
must be the ID of exactly one active user who has signed in to this AgentOS, as an
os.agno.com sign-in is. The match is stored, the member is told once which user
they act as, and every message, approval and Task result then runs with that
user's roles. Anyone not matched is told to sign in first.

Everyone who signs in gets the "member" role, so a matched member can start Tasks
from Slack with no per-user setup. OS_ADMIN is given "admin", for the AgentOS UI.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, PostgreSQL (./cookbook/scripts/run_pgvector.sh)
Sign in with os.agno.com: JWT_ALGORITHM=RS256, JWT_VERIFICATION_KEY=<public key from Settings > OS Security>, OS_ADMIN=<your email>
Or locally: JWT_VERIFICATION_KEY=<any 32+ characters>, SLACK_TEST_EMAIL=<your Slack email> (added as if you had signed in)
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/link_accounts.py (--check builds it without serving)
Try in Slack: "Start the task <printed id>", and later "What is its status?"; someone who has not signed in is asked to sign in first
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, mpim:history, channels:history, groups:history, users:read, users:read.email
"""

import asyncio
import os
import sys

from agno.company.manager import CompanyManager
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.os.interfaces.slack import Slack
from agno.registry import Registry
from agno.workflow import Step, StepInput, StepOutput, Workflow

PORT = 7777
# RS256 with the os.agno.com key verifies its sign-ins; HS256 is enough for a local run
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

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

# A Slack message carries no token, so a member runs with the roles stored here
authz = Authorization(
    verification_keys=[required_env("JWT_VERIFICATION_KEY")], algorithm=ALGORITHM
)
authz.define_role("member", MEMBER_SCOPES, default=True)
# The AgentOS UI needs more than the member role; seed() grants admin while nobody holds it
authz.define_role("admin", ["agent_os:admin"])
if os.getenv("OS_ADMIN"):
    authz.seed(admin=os.environ["OS_ADMIN"])

agent_os = AgentOS(
    id="slack-link-accounts-os",
    description="Super Agent in Slack under authorization, matching members by email.",
    db=db,
    registry=registry,
    workflows=[investigator],
    company=CompanyConfig(model=model),
    manager=OSManager(model=model, access_docs=False),
    queue=QueueConfig(durable=True, db=db),
    authorization=authz,
    # The users who have signed in: a Slack member is matched to one of them by email
    user_directory=True,
)
# The manager exists only once AgentOS is constructed
agent_os.interfaces.append(Slack(team=agent_os.manager, resolve_user_identity=True))
app = agent_os.get_app()


def add_test_user() -> None:
    """Add SLACK_TEST_EMAIL to the directory with the member role, as its first sign-in would."""
    email = os.getenv("SLACK_TEST_EMAIL")
    if not email or agent_os.user_directory is None:
        return
    agent_os.user_directory.upsert(id=email)
    authz.assign(email, "member")


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


# ---------------------------------------------------------------------------
# Run the AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    add_test_user()
    if "--check" in sys.argv:
        slack = agent_os.interfaces[-1]
        print(f"Slack members are matched by email: {slack.ctx.links is not None}")
        sys.exit(0)
    task_id = create_accepted_task()
    print(
        "\nMessage the bot in Slack as someone who has signed in to this AgentOS, "
        f"and ask it: Start the task {task_id}\n",
        flush=True,
    )
    agent_os.serve(app=app, port=PORT, reload=False)
