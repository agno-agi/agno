"""
WorkflowSession.get_messages for team step executors — reproduction for #8658
=============================================================================

Reproduces the two bugs in ``WorkflowSession.get_messages(team_id=...,
skip_member_messages=...)`` when a ``Team`` is used as a workflow step
executor:

  1. ``skip_member_messages=False`` crashed with ``UnboundLocalError`` before
     returning anything. Reported in #8658 and fixed by the one-line
     initialization at ``session/workflow.py:349`` (``session_runs = runs``).
  2. Even after fixing the crash, the ``skip_member_messages`` flag is a
     silent no-op — passing ``True`` or ``False`` returns identical messages.
     This is because the caller in ``get_messages`` pre-filters
     ``step_executor_runs`` by ``executor_run.team_id == team_id`` (so member
     sub-runs are already excluded before Stage 2 sees them), and the Stage 2
     filter then also keys on ``team_id == team_id`` (a no-op on
     already-filtered data). The sibling ``session/team.py:190-192`` uses
     ``parent_run_id is None`` as the semantically meaningful check.

This cookbook is a **regression demonstration**. Its assertion should:

  - PASS after both bugs are fixed (crash + semantic no-op).
  - FAIL loudly if either bug regresses, or if you run this before the
    semantic fix lands.

Two runtime prerequisites for member messages to actually appear
----------------------------------------------------------------
``TeamRunOutput.member_responses`` is only populated when both of these hold:

  a) ``Team(store_member_responses=True)`` — otherwise the team's own
     persistence path scrubs ``member_responses`` before write.
  b) The team leader actually calls a delegation tool during the run — the
     ``add_member_run`` hook only fires from inside ``delegate_task_to_member``
     / ``delegate_task_to_members``. If the leader chooses to answer the
     prompt itself (which strong models often do for simple prompts),
     ``member_responses`` stays empty and ``skip_member_messages=False``
     legitimately has nothing extra to surface.

Section 2 opts in to both — ``store_member_responses=True`` plus
``delegate_to_all_members=True`` and explicit "you MUST delegate" instructions.

Sections
--------
1. Hand-constructed ``WorkflowSession`` demo — no LLM required. Runs in
   milliseconds and prints exactly what the flag should return in each case.
2. Real workflow with a ``Team`` step executor — requires OPENAI_API_KEY.
   Runs a live workflow (forcing delegation so member sub-runs exist), saves
   the session to SQLite, reloads it, and queries ``get_messages`` both ways.
"""

from pathlib import Path

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession


# ---------------------------------------------------------------------------
# Section 1 - Hand-constructed session (no LLM required)
# ---------------------------------------------------------------------------
def demo_from_handcrafted_session():
    """Show the semantic difference between skip_member_messages True/False.

    This section constructs a WorkflowSession by hand so the demo is fully
    deterministic. The shape mirrors what the runtime produces when a Step is
    executed by a Team whose members are agents.
    """
    print("Section 1: Hand-constructed WorkflowSession")
    print("=" * 60)

    # Match the shape the runtime actually produces: the top-level team
    # executor's parent_run_id points at the enclosing workflow run, and its
    # member sub-runs' parent_run_id points at the team executor itself.
    WORKFLOW_RUN_ID = "wf-1"
    TEAM_TOP_RUN_ID = "run-team-top"

    # Two agent members produce their own RunOutputs.
    researcher_run = RunOutput(
        run_id="run-researcher",
        agent_id="researcher",
        parent_run_id=TEAM_TOP_RUN_ID,
        messages=[
            Message(role="user", content="Look up the population of Tokyo."),
            Message(role="assistant", content="Tokyo has ~13.9 million people."),
        ],
        status=RunStatus.completed,
    )
    summarizer_run = RunOutput(
        run_id="run-summarizer",
        agent_id="summarizer",
        parent_run_id=TEAM_TOP_RUN_ID,
        messages=[
            Message(role="user", content="Summarize the finding."),
            Message(role="assistant", content="Tokyo is home to about 14M."),
        ],
        status=RunStatus.completed,
    )

    # Top-level team run. In a workflow context the team executor's own
    # parent_run_id is the workflow run's id (the team is "under" the workflow).
    team_top_run = TeamRunOutput(
        run_id=TEAM_TOP_RUN_ID,
        team_id="research-team",
        parent_run_id=WORKFLOW_RUN_ID,
        messages=[
            Message(role="system", content="You are a research team lead."),
            Message(role="user", content="What is the population of Tokyo?"),
            Message(
                role="assistant",
                content="Tokyo has approximately 14 million residents.",
            ),
        ],
        member_responses=[researcher_run, summarizer_run],
        status=RunStatus.completed,
    )

    # A workflow run whose single step was executed by the research team.
    workflow_run = WorkflowRunOutput(
        run_id=WORKFLOW_RUN_ID,
        workflow_id="research-workflow",
        session_id="sess-demo",
        step_executor_runs=[team_top_run],
    )

    session = WorkflowSession(
        session_id="sess-demo",
        workflow_id="research-workflow",
        runs=[workflow_run],
        session_data={},
    )

    print()
    print("skip_member_messages=True (default): top-level team messages only")
    print("-" * 60)
    top_only = session.get_messages(team_id="research-team", skip_member_messages=True)
    for m in top_only:
        print(f"  [{m.role:>9}] {m.content}")

    print()
    print("skip_member_messages=False: top-level AND member agent messages")
    print("-" * 60)
    with_members = session.get_messages(
        team_id="research-team", skip_member_messages=False
    )
    for m in with_members:
        print(f"  [{m.role:>9}] {m.content}")

    print()
    print(f"top-level only: {len(top_only)} messages")
    print(f"with members  : {len(with_members)} messages")

    if len(with_members) == len(top_only):
        print()
        print("!! REGRESSION CHECK FAILED — semantic no-op still present")
        print("!! skip_member_messages=False returned the same messages as True.")
        print("!! Member sub-run messages ('Look up the population of Tokyo.',")
        print("!! 'Tokyo has ~13.9 million people.', etc.) never surfaced.")
        print("!! This is bug #2 in #8658. See session/workflow.py:461-466 (caller")
        print("!! pre-filter) and :352 (Stage 2 filter).")
    else:
        print()
        print("OK: skip_member_messages=False surfaced additional member messages.")
    assert len(with_members) > len(top_only), (
        "skip_member_messages=False must surface member-agent messages, but returned the same set as True. "
        "This is the silent-no-op bug (bug 2 of #8658). Fix the caller in get_messages() to walk "
        "TeamRunOutput.member_responses when skip_member_messages=False, and change the Stage 2 filter "
        "in get_messages_from_team_runs to key on parent_run_id is None (matching session/team.py:190-192)."
    )


# ---------------------------------------------------------------------------
# Section 2 - Real workflow with a Team step executor (requires OPENAI_API_KEY)
# ---------------------------------------------------------------------------
def demo_from_live_workflow():
    """Run a real workflow whose step is executed by a Team, then query the
    session's messages both ways.

    Skipped automatically if ``OPENAI_API_KEY`` is not set so this cookbook can
    still run in restricted environments.
    """
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        print()
        print("Section 2: skipped (OPENAI_API_KEY not set)")
        return

    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.models.openai import OpenAIResponses
    from agno.team import Team
    from agno.workflow.step import Step
    from agno.workflow.workflow import Workflow

    print()
    print("Section 2: Live workflow with a Team step executor")
    print("=" * 60)

    tmp_dir = Path("tmp")
    tmp_dir.mkdir(exist_ok=True)
    # Fresh DB so the demo is reproducible.
    db_path = tmp_dir / "team_messages_from_session.db"
    if db_path.exists():
        db_path.unlink()
    db = SqliteDb(db_file=str(db_path))

    fact_finder = Agent(
        name="FactFinder",
        model=OpenAIResponses(id="gpt-5.4"),
        instructions=["Find one concrete fact for the topic. Keep it under 20 words."],
        db=db,
    )
    summarizer = Agent(
        name="Summarizer",
        model=OpenAIResponses(id="gpt-5.4"),
        instructions=["Rewrite the finding in a single crisp sentence."],
        db=db,
    )
    # Two flags matter for `get_messages(skip_member_messages=False)` to surface
    # member-agent messages from a live workflow session:
    #
    # 1. `store_member_responses=True` on the Team — otherwise the team's own
    #    persistence path scrubs `TeamRunOutput.member_responses` before write.
    # 2. `delegate_to_all_members=True` (and/or explicit instructions to
    #    delegate) — otherwise the team leader may just answer the prompt
    #    itself. `member_responses` only gets populated when a delegation tool
    #    call actually happens; if the leader never delegates, there are no
    #    member runs to store, and `skip_member_messages` has nothing extra to
    #    surface.
    research_team = Team(
        name="ResearchTeam",
        id="research-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[fact_finder, summarizer],
        store_member_responses=True,
        delegate_to_all_members=True,
        instructions=[
            "You MUST delegate the task to your members. Do not answer yourself.",
            "First delegate to FactFinder, then delegate to Summarizer with the fact.",
        ],
        db=db,
    )

    workflow = Workflow(
        name="research-workflow",
        id="research-workflow",
        session_id="cookbook-team-messages",
        db=db,
        steps=[Step(name="research", team=research_team)],
    )

    print("Running workflow with team-executed step...")
    workflow.run("Give me one interesting fact about the moon.")

    session = workflow.get_session(session_id="cookbook-team-messages")
    assert session is not None, "session should exist after run"

    print()
    print("skip_member_messages=True (default): top-level team messages only")
    print("-" * 60)
    top_only = session.get_messages(team_id="research-team", skip_member_messages=True)
    for m in top_only:
        preview = (m.content or "")[:80].replace("\n", " ")
        print(f"  [{m.role:>9}] {preview}")

    print()
    print("skip_member_messages=False: top-level AND member agent messages")
    print("-" * 60)
    with_members = session.get_messages(
        team_id="research-team", skip_member_messages=False
    )
    for m in with_members:
        preview = (m.content or "")[:80].replace("\n", " ")
        print(f"  [{m.role:>9}] {preview}")

    print()
    print(f"top-level only: {len(top_only)} messages")
    print(f"with members  : {len(with_members)} messages")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    demo_from_handcrafted_session()
    demo_from_live_workflow()
