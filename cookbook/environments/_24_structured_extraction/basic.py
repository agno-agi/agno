"""
Structured Extraction - Basic
=============================

Reconcile a dense record into typed fields, applying source and amendment
precedence before scoring the complete object.
"""

from typing import Literal

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class AccountRecord(BaseModel):
    account_id: str
    plan: Literal["starter", "pro", "enterprise"]
    seats: int = Field(ge=1)
    renewal_date: str
    auto_renew: bool
    applied_source_ids: list[str] = Field(
        description="Operative source ids in lexical order"
    )


def record_matches(run, expected) -> bool:
    return (
        isinstance(run.content, AccountRecord) and run.content.model_dump() == expected
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=AccountRecord,
    instructions=(
        "Extract the operative account record. A later signed amendment overrides "
        "only the fields it changes. Signed documents outrank email and chat. Ignore "
        "drafts, proposals, quoted old text, and explicitly rejected changes. Preserve "
        "unchanged fields from the governing signed document. A contingent amendment "
        "applies only after its condition is confirmed in signed evidence. A rescission "
        "reverts only its named fields to their values immediately before the rescinded "
        "amendment. When an as-of date is given, future-effective changes do not apply."
        " Return the ids of every source that contributes at least one current field, "
        "using the exact uppercase ids in lexical order."
    ),
)

environment = Environment(
    name="account-record-extraction",
    agent=agent,
    tasks=(
        Task(
            id="partial-amendment",
            input=(
                "Signed source BASE dated 2026-04-01: account AC-17, Pro plan, 40 seats, "
                "renewal 2027-04-01, auto-renew yes. A forwarded draft proposed "
                "Enterprise with 100 seats but was never executed. Signed amendment "
                "source A dated 2026-06-12 changes seats to 55 and disables auto-renew; all other "
                "terms remain. A later chat says 'probably 60 seats next month'."
            ),
            expected={
                "account_id": "AC-17",
                "plan": "pro",
                "seats": 55,
                "renewal_date": "2027-04-01",
                "auto_renew": False,
                "applied_source_ids": ["A", "BASE"],
            },
        ),
        Task(
            id="rejected-revision",
            input=(
                "Signed source BASE dated 2026-02-10: account BX-204, Starter plan, 12 seats, "
                "renewal 2027-02-10, no auto-renew. Signed source A dated 2026-05-03: "
                "upgrade to Pro and enable auto-renew, seats unchanged. Amendment "
                "draft v3 says 25 seats and renewal 2027-05-03; legal marked it "
                "REJECTED. Billing email repeats the rejected date as if approved."
            ),
            expected={
                "account_id": "BX-204",
                "plan": "pro",
                "seats": 12,
                "renewal_date": "2027-02-10",
                "auto_renew": True,
                "applied_source_ids": ["A", "BASE"],
            },
        ),
        Task(
            id="later-narrow-amendment",
            input=(
                "Signed source BASE: account QZ-9, Enterprise, 220 seats, renewal "
                "2027-09-30, auto-renew yes. Signed source A on 2026-06-01 sets "
                "180 seats and disables auto-renew. Signed source B on 2026-06-18 "
                "says only: 'seat count is 205; Amendment A otherwise remains in "
                "force.' A sales note quotes the original 220-seat line."
            ),
            expected={
                "account_id": "QZ-9",
                "plan": "enterprise",
                "seats": 205,
                "renewal_date": "2027-09-30",
                "auto_renew": False,
                "applied_source_ids": ["A", "B", "BASE"],
            },
        ),
        Task(
            id="contingent-rescission",
            input=(
                "Signed source BASE: account LM-44, Starter, 18 seats, renewal "
                "2027-01-15, no auto-renew. Signed Amendment A changes plan to Pro, "
                "seats to 30, and enables auto-renew. Signed Amendment B would change "
                "seats to 44 and renewal to 2027-06-30 only if security approval is "
                "confirmed. An email says approval probably happened, but the signed "
                "security decision says NOT APPROVED. Signed Amendment C then rescinds "
                "only Amendment A's plan change; A's other terms remain."
            ),
            expected={
                "account_id": "LM-44",
                "plan": "starter",
                "seats": 30,
                "renewal_date": "2027-01-15",
                "auto_renew": True,
                "applied_source_ids": ["A", "BASE", "C"],
            },
        ),
        Task(
            id="as-of-effective-date",
            input=(
                "Extract as of 2026-07-15. Signed source BASE: account TR-6, Pro, 75 seats, "
                "renewal 2027-03-01, auto-renew yes. Signed Amendment A, effective "
                "2026-07-01, sets 82 seats and disables auto-renew. Signed Amendment B, "
                "effective 2026-08-01, upgrades to Enterprise, sets 95 seats, and moves "
                "renewal to 2027-08-01. Finance already entered B in its spreadsheet; "
                "the signed effective date was not accelerated."
            ),
            expected={
                "account_id": "TR-6",
                "plan": "pro",
                "seats": 82,
                "renewal_date": "2027-03-01",
                "auto_renew": False,
                "applied_source_ids": ["A", "BASE"],
            },
        ),
    ),
    scorer=CodeScorer(record_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4, concurrency=4)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
