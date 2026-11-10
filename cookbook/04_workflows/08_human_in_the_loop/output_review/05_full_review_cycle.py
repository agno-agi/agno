"""
Full Review Cycle Example
=========================

Demonstrates the complete HITL review workflow with all three decisions,
using the HITL config class:

  Workflow topology:
    agent_a -> [human review] -+- approve -> agent_b -> END
                               +- reject  -> agent_a (retry with feedback)
                               +- cancel  -> END

  The post-execution review on agent_a acts as the human review gate.
  No separate review step needed -- the framework handles pause/resume.

Demonstrates:
  - Post-execution output review (HITL.requires_output_review)
  - Reject with retry (on_reject=OnReject.retry)
  - Reject with feedback (reject(feedback=...))
  - Max retries (HITL.max_retries)
  - All three decisions: approve, reject, cancel
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import HumanReview
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

agent_a = Agent(
    name="Agent A",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=(
        "You are Agent A - a research assistant. "
        "Produce a concise numbered list of the key benefits of morning exercise. "
        "Output ONLY the numbered list (no prose). "
        "A human reviewer will read your output and decide whether to approve it, "
        "ask you to redo it (reject), or cancel the workflow entirely."
    ),
)

agent_b = Agent(
    name="Agent B",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=(
        "You are Agent B - a science writer for a general audience. "
        "The human reviewer has APPROVED Agent A's research points. "
        "Read those points and write a concise, engaging, jargon-free summary "
        "(3-5 sentences). Do NOT repeat the bullet points verbatim."
    ),
)

# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

workflow = Workflow(
    name="hitl_review_workflow",
    db=SqliteDb(db_file="tmp/hitl_full_review_cycle.db"),
    steps=[
        Step(
            name="agent_a",
            agent=agent_a,
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Review Agent A's draft and decide: approve / reject / cancel",
                on_reject=OnReject.retry,
                max_retries=3,
            ),
        ),
        Step(
            name="agent_b",
            agent=agent_b,
        ),
    ],
)

# ---------------------------------------------------------------------------
# Demo 1: APPROVE
# ---------------------------------------------------------------------------

print("=" * 65)
print("  Demo 1: APPROVE")
print("=" * 65)

run_output = workflow.run("Summarise the benefits of morning exercise.")

if run_output.is_paused:
    for req in run_output.steps_requiring_output_review:
        print(f"\n[PAUSED] Step '{req.step_name}' produced output for review:")
        print(
            f"  Draft:\n    {req.step_output.content[:300] if req.step_output and req.step_output.content else '(none)'}"
        )
        print("\n  -> Simulating decision: APPROVE")
        req.confirm()

    run_output = workflow.continue_run(run_output)

print(
    f"\n[RESULT] Agent B summary:\n  {str(run_output.content)[:400] if run_output.content else '(none)'}"
)

# ---------------------------------------------------------------------------
# Demo 2: CANCEL
# ---------------------------------------------------------------------------

print(f"\n{'=' * 65}")
print("  Demo 2: CANCEL")
print("=" * 65)

# Separate workflow with on_reject=cancel for the cancel demo
cancel_workflow = Workflow(
    name="hitl_cancel_workflow",
    db=SqliteDb(db_file="tmp/hitl_full_review_cancel.db"),
    steps=[
        Step(
            name="agent_a",
            agent=agent_a,
            human_review=HumanReview(
                requires_output_review=True,
                output_review_message="Review Agent A's draft",
                on_reject=OnReject.cancel,
            ),
        ),
        Step(
            name="agent_b",
            agent=agent_b,
        ),
    ],
)

run_output = cancel_workflow.run("Summarise the benefits of morning exercise.")

if run_output.is_paused:
    for req in run_output.steps_requiring_output_review:
        print(
            f"\n[PAUSED] Draft:\n    {req.step_output.content[:300] if req.step_output and req.step_output.content else '(none)'}"
        )
        print("\n  -> Simulating decision: CANCEL")
        req.reject()

    run_output = cancel_workflow.continue_run(run_output)

print(f"\n[RESULT] Status: {run_output.status}")
print(f"  Content: {run_output.content}")

# ---------------------------------------------------------------------------
# Demo 3: REJECT (with feedback), then APPROVE on retry
# ---------------------------------------------------------------------------

print(f"\n{'=' * 65}")
print("  Demo 3: REJECT on first attempt, then APPROVE on retry")
print("=" * 65)

run_output = workflow.run("Summarise the benefits of morning exercise.")

attempt = 0
while run_output.is_paused:
    attempt += 1
    for req in run_output.steps_requiring_output_review:
        draft = (
            req.step_output.content[:300]
            if req.step_output and req.step_output.content
            else "(none)"
        )
        print(f"\n[PAUSED] Attempt {attempt} - Draft:\n    {draft}")

        if attempt == 1:
            # First attempt: reject with feedback
            print("\n  -> Simulating decision: REJECT (with feedback)")
            req.reject(
                feedback="Please add a point about improved mood and mental health."
            )
        else:
            # Second attempt: approve the revised draft
            print("\n  -> Simulating decision: APPROVE")
            req.confirm()

    run_output = workflow.continue_run(run_output)

print(
    f"\n[RESULT] Final Agent B summary:\n  {str(run_output.content)[:400] if run_output.content else '(none)'}"
)
print(f"  Status: {run_output.status}")
