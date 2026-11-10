"""
Support Triage - Ambiguous Tickets
==================================

Resolve the requested action when one ticket mixes several plausible queues,
while retaining safety overrides for active security and incidents.
"""

from typing import Literal

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class TriageAction(BaseModel):
    queue: Literal["security", "incident", "access", "billing", "bug", "feature"]
    action: Literal[
        "revoke_credentials",
        "restore_service",
        "recover_access",
        "refund_review",
        "diagnose_bug",
        "product_feedback",
    ]
    active_issue_ids: list[str]
    active_issue_checksum: int
    winning_issue_id: str
    reason: str


def action_matches(run, expected) -> bool:
    return (
        isinstance(run.content, TriageAction)
        and run.content.model_dump(exclude={"reason"}) == expected
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=TriageAction,
    instructions=(
        "Choose the queue that owns the customer's current requested action, except "
        "active unauthorized access or credential exposure always overrides to "
        "security/revoke_credentials, and current multi-user outage or data loss "
        "overrides to incident/restore_service. Do not activate overrides from a "
        "hypothesis, a negated statement, quoted history, or a resolved event. Map "
        "access to recover_access, billing to refund_review, bug to diagnose_bug, and "
        "feature to product_feedback. Return active labeled issue ids in lexical order "
        "and the issue id that owns the selected action or safety override. For the "
        "handoff audit, active_issue_checksum is sum((position squared) * "
        "(numeric_suffix cubed)) over the lexically ordered active_issue_ids, with "
        "positions starting at 1, reduced modulo 9973."
    ),
)

environment = Environment(
    name="ambiguous-support-actions",
    agent=agent,
    tasks=(
        Task(
            id="bug-context-refund-request",
            input=(
                "The export bug wasted an hour, but it stopped after I refreshed and I "
                "do not need debugging. I1 is that resolved bug. I2: My only current "
                "request is review of the $30 "
                "charge for that month. No data was lost."
            ),
            expected={
                "queue": "billing",
                "action": "refund_review",
                "active_issue_ids": ["I2"],
                "active_issue_checksum": 8,
                "winning_issue_id": "I2",
            },
        ),
        Task(
            id="feature-with-hypothetical-risk",
            input=(
                "I1: Could you add public share links? I2: We have not exposed any private link "
                "or credential. If someone configured a link incorrectly it might leak "
                "data, but today I only want the feature request recorded."
            ),
            expected={
                "queue": "feature",
                "action": "product_feedback",
                "active_issue_ids": ["I1"],
                "active_issue_checksum": 1,
                "winning_issue_id": "I1",
            },
        ),
        Task(
            id="access-request-active-intrusion",
            input=(
                "I1: Please help me log back in. I2: Audit shows an unknown device is "
                "still using my token and changing settings now. The reset email works."
            ),
            expected={
                "queue": "security",
                "action": "revoke_credentials",
                "active_issue_ids": ["I1", "I2"],
                "active_issue_checksum": 33,
                "winning_issue_id": "I2",
            },
        ),
        Task(
            id="quoted-outage-current-access",
            input=(
                "I1: The previous ticket said 'everyone is down'; that outage was resolved "
                "Friday. I2: Today only I cannot sign in, and I need account recovery. The "
                "status page is green for the rest of the company."
            ),
            expected={
                "queue": "access",
                "action": "recover_access",
                "active_issue_ids": ["I2"],
                "active_issue_checksum": 8,
                "winning_issue_id": "I2",
            },
        ),
        Task(
            id="refund-wording-active-outage",
            input=(
                "I1: I want a refund. I2: Fourteen teammates are currently unable to "
                "open any project and work is stopped. Restore service before discussing credit."
            ),
            expected={
                "queue": "incident",
                "action": "restore_service",
                "active_issue_ids": ["I1", "I2"],
                "active_issue_checksum": 33,
                "winning_issue_id": "I2",
            },
        ),
        Task(
            id="long-requested-action-handoff",
            input=(
                "I01: Last week's unknown-token alert was resolved as our own bot. "
                "I02: One standard user still cannot receive reset mail. I03: A $14 "
                "refund review remains open. I04: Search still crashes for one user. "
                "I05: The customer explicitly says their only requested action today is "
                "to record a bulk-rename feature request. I06: They ask hypothetically "
                "whether public links might expose credentials; none have. I07: A quoted "
                "twelve-user outage is historical and closed. I08: A separate $22 charge "
                "dispute remains open. I09: An export bug was fixed and verified. I10: "
                "The workspace owner recovered access. I11: Dark mode also remains "
                "requested. I12: They wonder whether data could be lost, but report none "
                "missing. I13: A second standard user still cannot pass MFA. I14: Save "
                "still returns a 500 for one user. I15: A $9 duplicate was fully credited. "
                "I16: A forwarded incident transcript is resolved. Do not open actions "
                "for the other active context; record the requested feature action only. "
                "I17: Another $41 refund review remains open. I18: A credential alert "
                "was confirmed as a test and closed. I19: Reports still time out for one "
                "user. I20: They ask whether ten people might lose access next month; no "
                "current outage exists. I21: Calendar view remains requested. I22: A "
                "standard user still cannot receive a login code. I23: A $12 refund was "
                "paid in full. I24: Comments still fail to save for one user. I25: An "
                "admin confirms access was restored. I26: Color labels remain requested. "
                "I27: A quoted organization-wide outage is historical and closed. I28: "
                "A separate $7 duplicate charge remains disputed. I29: They ask if a "
                "future integration could leak a token; no exposure exists. I30: Another "
                "standard user remains locked out. I31: A mobile crash was fixed and "
                "verified. I32: PDF themes remain requested."
            ),
            expected={
                "queue": "feature",
                "action": "product_feedback",
                "active_issue_ids": [
                    "I02",
                    "I03",
                    "I04",
                    "I05",
                    "I08",
                    "I11",
                    "I13",
                    "I14",
                    "I17",
                    "I19",
                    "I21",
                    "I22",
                    "I24",
                    "I26",
                    "I28",
                    "I30",
                    "I32",
                ],
                "active_issue_checksum": 1156,
                "winning_issue_id": "I05",
            },
        ),
    ),
    scorer=CodeScorer(action_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=6, concurrency=6)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
