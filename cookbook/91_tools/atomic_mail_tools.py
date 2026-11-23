"""
Atomic Mail Workflow
====================

Runs AtomicMailTools (https://atomicmail.ai) end to end inside a deterministic
Agno workflow -- no LLM required. The three steps mirror the toolkit's tools:

    1. Register (or reuse) an inbox via the autonomous proof-of-work signup flow.
    2. Read the most recent messages in that inbox.
    3. Send a plain-text email from the inbox.

The username and recipient are read from `additional_data` (with environment
fallbacks) so the same workflow can provision a throwaway inbox and mail a test
message without editing the file:

    export ATOMIC_MAIL_USERNAME=my-agent-inbox           # 5-21 chars
    export ATOMIC_MAIL_TEST_RECIPIENT=you@example.com
    export ATOMIC_MAIL_CREDENTIALS_DIR=./tmp/atomicmail  # optional, isolates creds
    .venvs/demo/bin/python cookbook/91_tools/atomic_mail_tools.py
"""

from os import getenv

from agno.tools.atomic_mail import AtomicMailTools
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

# A single toolkit instance is shared across steps. It caches the registered
# inbox's API key to disk, so every step operates on the same inbox.
atomic_mail = AtomicMailTools()


def register_inbox_step(step_input: StepInput) -> StepOutput:
    data = step_input.additional_data or {}
    username = data.get("username") or getenv("ATOMIC_MAIL_USERNAME", "agno-demo-inbox")

    result = atomic_mail.register_inbox(username)
    if "error" in result:
        return StepOutput(
            content=f"Could not register inbox: {result['error']}", success=False
        )

    reused = "reused existing" if result.get("idempotent") else "registered new"
    return StepOutput(content=f"Inbox ready ({reused}): {result['inbox']}")


def read_inbox_step(step_input: StepInput) -> StepOutput:
    result = atomic_mail.list_inbox(limit=5)
    if "error" in result:
        return StepOutput(
            content=f"Could not read inbox: {result['error']}", success=False
        )

    return StepOutput(
        content=f"Inbox {result['inbox']} currently holds {result['count']} message(s)."
    )


def send_email_step(step_input: StepInput) -> StepOutput:
    data = step_input.additional_data or {}
    recipient = data.get("recipient") or getenv("ATOMIC_MAIL_TEST_RECIPIENT")
    if not recipient:
        return StepOutput(
            content="No recipient set. Pass additional_data['recipient'] or ATOMIC_MAIL_TEST_RECIPIENT.",
            success=False,
        )

    result = atomic_mail.send_email(
        to=recipient,
        subject="Hello from an Agno workflow",
        body="This inbox was registered, read, and used to send this message autonomously by an Agno workflow.",
    )
    if "error" in result:
        return StepOutput(
            content=f"Could not send email: {result['error']}", success=False
        )

    return StepOutput(content=f"Sent email {result.get('email_id')} to {recipient}.")


atomic_mail_workflow = Workflow(
    name="Atomic Mail Workflow",
    description="Register an AtomicMail inbox, read it, and send an email -- end to end, without an LLM.",
    steps=[
        Step(name="Register Inbox", executor=register_inbox_step),
        Step(name="Read Inbox", executor=read_inbox_step),
        Step(name="Send Email", executor=send_email_step),
    ],
)


if __name__ == "__main__":
    atomic_mail_workflow.print_response(
        input="Provision an AtomicMail inbox and send a test email.",
        additional_data={
            "username": getenv("ATOMIC_MAIL_USERNAME", "agno-demo-inbox"),
            "recipient": getenv("ATOMIC_MAIL_TEST_RECIPIENT", "someone@example.com"),
        },
        markdown=True,
    )
