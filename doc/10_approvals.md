# Approvals — Human-in-the-Loop

Agno's approval system pauses agent execution and waits for a human to confirm before proceeding. This is essential for agents that perform sensitive, irreversible, or compliance-gated actions.

**Directory:** `libs/agno/agno/approval/`
**Cookbook:** `cookbook/02_agents/11_approvals/`

---

## How approvals work

1. Agent decides to call a tool marked with `@approval` + `requires_confirmation=True`
2. Agent **pauses** — `run_response.is_paused == True`
3. An approval record is created in the database
4. The calling code (or a human via API/UI) **confirms** or **rejects** the pending requirement
5. `agent.continue_run(...)` resumes execution with the confirmed requirements
6. Agent calls the tool and completes

---

## Basic approval

```python
import json
import time
from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool
import httpx

# Mark a tool as requiring approval
@approval
@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to the specified address.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body content.

    Returns:
        Confirmation that the email was sent.
    """
    # send_email_via_api(to, subject, body)
    return f"Email sent to {to}: {subject}"

db = SqliteDb(
    db_file="tmp/approvals.db",
    session_table="sessions",
    approvals_table="approvals",
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[send_email],
    db=db,
)

# Step 1: Run — agent pauses before sending email
run_response = agent.run("Send a welcome email to alice@example.com")
print(f"Status: {run_response.status}")    # "paused"
assert run_response.is_paused

# Step 2: Inspect pending approval
pending, total = db.get_approvals(status="pending")
print(f"Pending approvals: {total}")
approval_record = pending[0]
print(f"Tool: {approval_record['source_type']}")

# Step 3: Approve and continue
for requirement in run_response.active_requirements:
    if requirement.needs_confirmation:
        print(f"Approving: {requirement.tool_execution.tool_name}")
        requirement.confirm()

run_response = agent.continue_run(
    run_id=run_response.run_id,
    requirements=run_response.requirements,
)
print(f"Final status: {run_response.status}")  # "success"
print(run_response.content)
```

---

## Rejecting a requirement

```python
for requirement in run_response.active_requirements:
    if requirement.needs_confirmation:
        requirement.reject(reason="Not authorised to send marketing emails")

run_response = agent.continue_run(
    run_id=run_response.run_id,
    requirements=run_response.requirements,
)
# Agent receives the rejection reason and responds accordingly
```

---

## Async approval

```python
import asyncio
from agno.agent import Agent
from agno.approval import approval
from agno.tools import tool

@approval
@tool(requires_confirmation=True)
async def delete_record(record_id: str) -> str:
    """Permanently delete a database record."""
    # await db.delete(record_id)
    return f"Record {record_id} deleted."

async def main():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), tools=[delete_record], db=db)

    run_response = await agent.arun("Delete record R-12345")
    assert run_response.is_paused

    for req in run_response.active_requirements:
        if req.needs_confirmation:
            req.confirm()

    run_response = await agent.acontinue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    print(run_response.content)

asyncio.run(main())
```

---

## External approval (out-of-band)

For scenarios where approval happens via an external system (Slack, email, web UI):

```python
# Step 1: Run the agent, get a paused response
run_response = agent.run("Transfer $10,000 to account 12345")
assert run_response.is_paused

run_id = run_response.run_id

# Step 2: Store the run_id, send approval request to Slack/email
send_slack_message(
    channel="#approvals",
    text=f"Agent wants to transfer $10,000. Approve? Run ID: {run_id}",
)

# Step 3: Later — human clicks approve in Slack bot / web UI
# which calls your webhook, which calls:
pending, _ = db.get_approvals(status="pending")
approval_id = pending[0]["id"]

db.update_approval(
    approval_id=approval_id,
    expected_status="pending",
    status="approved",
    resolved_by="bob",
    resolved_at=int(time.time()),
)

# Step 4: Resume execution
# (retrieve the saved run_response.requirements from storage)
run_response = agent.continue_run(
    run_id=run_id,
    requirements=saved_requirements,  # re-confirm all requirements
)
```

---

## Team approval

Approvals also work across multi-agent teams:

```python
from agno.team import Team

@approval
@tool(requires_confirmation=True)
def publish_to_production(content: str) -> str:
    """Publish content to the production website."""
    return f"Published: {content[:50]}..."

team = Team(
    model=OpenAIChat(id="gpt-4o"),
    members=[writer, editor],
    tools=[publish_to_production],
    db=db,
)

run_response = team.run("Write and publish an article about AI safety")
if run_response.is_paused:
    # handle approval as above
    ...
```

---

## AgentOS approval endpoints

When running via `AgentOS`, approvals are managed through the REST API:

```bash
# List pending approvals
GET /approvals?status=pending

# Approve
POST /approvals/{run_id}/approve
{
    "requirement_id": "...",
    "resolved_by": "alice"
}

# Reject
POST /approvals/{run_id}/reject
{
    "requirement_id": "...",
    "reason": "Not authorised"
}
```

---

## Approval decorators reference

```python
from agno.approval import approval
from agno.tools import tool

# Both decorators are required:
@approval                           # registers the tool in the approval system
@tool(requires_confirmation=True)   # marks tool as needing confirmation at runtime
def my_sensitive_tool(...) -> str:
    ...
```

The `@tool(requires_confirmation=True)` flag tells the agent execution loop to pause before invoking the tool. The `@approval` decorator registers audit metadata with the approval tracking system.

---

## RunResponse approval fields

```python
run_response = agent.run("...")

run_response.is_paused                  # True if waiting for approval
run_response.status                     # "paused" | "success" | "error"
run_response.run_id                     # ID to pass to continue_run()
run_response.requirements               # all requirements (pending + resolved)
run_response.active_requirements        # only pending requirements

for req in run_response.active_requirements:
    req.needs_confirmation              # True if waiting
    req.tool_execution.tool_name        # name of the tool requiring approval
    req.tool_execution.tool_args        # arguments the agent wants to pass
    req.confirm()                       # approve
    req.reject(reason="...")            # reject with explanation
```

---

## Audit log

Every approval is persisted in the database with:

| Field | Description |
|-------|-------------|
| `id` | Unique approval ID |
| `run_id` | Agent run that requested approval |
| `source_type` | Tool name |
| `context` | Tool arguments (what the agent wants to do) |
| `status` | `pending` → `approved` / `rejected` |
| `resolved_by` | Who approved or rejected |
| `resolved_at` | Unix timestamp of resolution |
| `created_at` | When the approval was requested |

Query the audit log:

```python
# All approvals for a run
approvals, count = db.get_approvals(run_id="run-123")

# All pending approvals
pending, count = db.get_approvals(status="pending")

# All approvals resolved by alice
resolved_by_alice, count = db.get_approvals(resolved_by="alice")
```
