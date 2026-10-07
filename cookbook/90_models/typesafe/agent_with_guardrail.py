"""
Jev Agent With Guardrail and Storage
====================================

A decision-model Agent keeps the usual Agent features that do not need text
generation: pre-hooks and guardrails run before the decision, and runs are
stored in the session like any other run.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import CheckTrigger, InputCheckError
from agno.models.typesafe import Jev
from agno.run.agent import RunInput
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define the Output and the Guardrail
# ---------------------------------------------------------------------------


class Moderation(BaseModel):
    """Moderate a community forum post."""

    spam: bool = Field(description="The post is unsolicited advertising")
    abusive: bool = Field(description="The post insults or threatens someone")


def reject_empty_posts(run_input: RunInput) -> None:
    if not run_input.input_content_string().strip():
        raise InputCheckError(
            "Empty post", check_trigger=CheckTrigger.INPUT_NOT_ALLOWED
        )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Jev(),
    output_schema=Moderation,
    pre_hooks=[reject_empty_posts],
    db=SqliteDb(db_file="tmp/decision_agent.db"),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for post in [
        "Buy cheap watches at example.shop!!!",
        "Has anyone tried the new release?",
        "   ",
    ]:
        run = agent.run(post, session_id="forum-moderation")
        print(f"{post!r}: status={run.status.value} content={run.content}")

    session = agent.get_session(session_id="forum-moderation")
    print(f"Runs stored in session: {len(session.runs or []) if session else 0}")
