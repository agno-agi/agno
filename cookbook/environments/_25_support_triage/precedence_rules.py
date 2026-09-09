"""
Support Triage - Precedence Rules
=================================

Apply queue precedence and derive severity plus response target from the
winning active condition.
"""

from typing import Literal

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class RoutedTicket(BaseModel):
    queue: Literal["security", "incident", "access", "billing", "bug"]
    severity: Literal["P0", "P1", "P2", "P3"]
    response_minutes: int
    matched_rule_ids: list[str]
    winning_rule_id: str


def route_matches(run, expected) -> bool:
    return (
        isinstance(run.content, RoutedTicket) and run.content.model_dump() == expected
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=RoutedTicket,
    instructions=(
        "Ignore resolved, denied, hypothetical, and quoted-old conditions. Then apply: "
        "R1: current credential or card exposure, or unauthorized access => security "
        "P0, 15 minutes. R2: current data loss or outage affecting at least 10 users => "
        "incident P1, 30 minutes. R3: locked-out workspace owner/admin => access P1, "
        "30 minutes. R4: other access => access P2, 240 minutes. R5: billing => billing "
        "P3, 1440 minutes. R6: other product defects => bug P2, 240 minutes. If several "
        "active rules match, precedence is R1 > R2 > R3 > R4 > R5 > R6. Return every "
        "matched rule id in numeric order and the winning rule id."
    ),
)

environment = Environment(
    name="support-precedence-rules",
    agent=agent,
    tasks=(
        Task(
            id="owner-lockout-with-old-alert",
            input=(
                "Workspace owner cannot pass MFA and all recovery codes are rejected. "
                "A quoted alert from Tuesday mentioned an unknown login, but audit later "
                "confirmed it was our IT contractor and closed that investigation. "
                "Three invoices also need corrected addresses."
            ),
            expected={
                "queue": "access",
                "severity": "P1",
                "response_minutes": 30,
                "matched_rule_ids": ["R3", "R5"],
                "winning_rule_id": "R3",
            },
        ),
        Task(
            id="card-data-not-outage",
            input=(
                "The app is slow for 18 staff but remains usable. One screenshot in the "
                "ticket currently exposes a customer's full card number. The customer "
                "also disputes the charge."
            ),
            expected={
                "queue": "security",
                "severity": "P0",
                "response_minutes": 15,
                "matched_rule_ids": ["R1", "R5", "R6"],
                "winning_rule_id": "R1",
            },
        ),
        Task(
            id="resolved-loss-active-outage",
            input=(
                "Yesterday's missing report was restored and verified complete. Today "
                "the dashboard is unavailable for exactly 10 users; an eleventh user "
                "says theirs still works. A refund request is also open."
            ),
            expected={
                "queue": "incident",
                "severity": "P1",
                "response_minutes": 30,
                "matched_rule_ids": ["R2", "R5"],
                "winning_rule_id": "R2",
            },
        ),
        Task(
            id="standard-user-and-bug",
            input=(
                "A standard member, not an owner or admin, is locked out after the reset "
                "link opens a blank page. Other members can sign in. No suspicious "
                "access appears in audit logs."
            ),
            expected={
                "queue": "access",
                "severity": "P2",
                "response_minutes": 240,
                "matched_rule_ids": ["R4", "R6"],
                "winning_rule_id": "R4",
            },
        ),
        Task(
            id="current-state-boundaries",
            input=(
                "A screenshot contains only the documented Stripe test number 4242, "
                "not a customer card. An unknown-login alert was confirmed as the "
                "customer's own automation. Twelve users lost dashboards at the peak, "
                "but the current update says eleven recovered and exactly one standard "
                "user remains affected. A separate workspace owner is still locked out. "
                "Another standard member still cannot pass MFA. A duplicate $31 charge "
                "remains open. Search also still crashes for one otherwise unaffected "
                "user. Yesterday's missing data was restored and verified complete."
            ),
            expected={
                "queue": "access",
                "severity": "P1",
                "response_minutes": 30,
                "matched_rule_ids": ["R3", "R4", "R5", "R6"],
                "winning_rule_id": "R3",
            },
        ),
    ),
    scorer=CodeScorer(route_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=6, concurrency=6)
    print(results)
    for task_result in results.task_results:
        print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
