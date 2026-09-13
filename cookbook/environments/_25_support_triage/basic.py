"""
Support Triage - Basic
======================

Classify precedence-heavy tickets after separating active customer impact from
quoted, hypothetical, or already resolved details.
"""

from typing import Literal

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Triage(BaseModel):
    queue: Literal["security", "incident", "access", "billing", "bug", "feature"]
    active_issue_ids: list[str]
    winning_issue_id: str
    handoff_checksum: int
    reason: str


def queue_matches(run, expected) -> bool:
    return (
        isinstance(run.content, Triage)
        and run.content.model_dump(exclude={"reason"}) == expected
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Triage,
    instructions=(
        "Route active issues using precedence security > incident > access > billing "
        "> bug > feature. Security requires current unauthorized access, credential "
        "exposure, or payment-card exposure; a user merely unable to sign in is access. "
        "Incident requires current multi-user unavailability or data loss. Ignore "
        "hypothetical risks, quoted history, and issues explicitly resolved. Return "
        "all active labeled issue ids in lexical order and the id that wins precedence. "
        "For the handoff audit, handoff_checksum is sum((position squared) * (numeric "
        "suffix cubed)) over the lexically ordered active issue ids, positions starting "
        "at 1, reduced modulo 9973."
    ),
)

environment = Environment(
    name="support-triage-basics",
    agent=agent,
    tasks=(
        Task(
            id="self-login-plus-charge",
            input=(
                "I1: I cannot sign in because the reset email never arrives. I2: I also "
                "see a duplicate invoice charge. I3: The security alert about a new login "
                "was me on my new phone, so there is no unauthorized access."
            ),
            expected={
                "queue": "access",
                "active_issue_ids": ["I1", "I2"],
                "winning_issue_id": "I1",
                "handoff_checksum": 33,
            },
        ),
        Task(
            id="resolved-token-history",
            input=(
                "I1: Forwarded from last month: 'our API token was posted publicly.' "
                "That token was revoked and the exposure review is closed. I2: Today's "
                "issue is a second $85 charge; please reverse the duplicate."
            ),
            expected={
                "queue": "billing",
                "active_issue_ids": ["I2"],
                "winning_issue_id": "I2",
                "handoff_checksum": 8,
            },
        ),
        Task(
            id="twenty-issue-handoff",
            input=(
                "I01: One standard user currently cannot receive a reset email. "
                "I02: An unknown-login alert from Monday was confirmed as the owner's "
                "phone and closed. I03: Dark mode remains requested. I04: The customer "
                "asks hypothetically whether an outage could lose data; none is missing. "
                "I05: A duplicate $18 charge remains disputed. I06: A quoted old ticket "
                "says twelve users were down; that outage is resolved. I07: Save crashes "
                "for one current user. I08: Eleven different users currently cannot open "
                "projects. I09: A token alert was confirmed as the customer's own "
                "automation and dismissed. I10: A current attachment exposes a real "
                "customer card number. I11: A duplicate $9 charge was fully refunded. "
                "I12: An admin lockout was fixed and login is restored. I13: A missing "
                "report was restored and verified complete. I14: Bulk rename remains a "
                "feature request. I15: Search currently returns a 500 for one user. "
                "I16: They ask whether a future debug build might expose credentials; "
                "none are exposed now. I17: A separate $27 refund request remains open. "
                "I18: A second standard user currently cannot pass MFA. I19: A forwarded "
                "incident transcript is historical and closed. I20: CSV themes remain a "
                "requested feature."
            ),
            expected={
                "queue": "security",
                "active_issue_ids": [
                    "I01",
                    "I03",
                    "I05",
                    "I07",
                    "I08",
                    "I10",
                    "I14",
                    "I15",
                    "I17",
                    "I18",
                    "I20",
                ],
                "winning_issue_id": "I10",
                "handoff_checksum": 1503,
            },
        ),
    ),
    scorer=CodeScorer(queue_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=8, concurrency=6)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
