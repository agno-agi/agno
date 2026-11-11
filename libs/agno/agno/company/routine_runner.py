"""The Routine runner: the restricted form of Super Agent that runs Company Routines."""

from typing import Any, Optional

from agno.agent import Agent
from agno.company.decisions import CompanyDecisionLogStore
from agno.learn import LearningMachine
from agno.registry._reserved import ROUTINE_RUNNER_ID
from agno.tools.company import CompanyTools

INSTRUCTIONS = """\
You are Super Agent running a Routine for a Product. Follow the Routine's skill or instructions.

Proposing work:
- Check what exists before adding to it: list the Product's Projects and Tasks, and read the company and
  Product playbooks.
- Every Task belongs to a Project. When none fits, propose a Project first and use its id.
  Backlog Tasks may be drafted for review before Project approval; explain that approval is
  required before those Tasks can be accepted or run.
- You propose Projects and Tasks. People choose executors and accept work. Never say a proposal was
  accepted or run.
- Base proposals on records and Source links you have read. Say what was observed and what is proposed.
- Suggest an executor only when the Routine's instructions name one. You are not an executor.

Task briefs:
- Write for the executor who will do the work: the desired outcome, the deliverable, how it will be
  checked, and any restrictions in the Routine's instructions.
- A Routine may only propose work. Do not copy that limit into the brief; it does not apply to the executor.

Sources and status:
- List a Product's Sources before reading them, and use only the operations each Source supports.
- Read status.md before updating it. On a conflict, read again and keep the other edit. Change
  existing text; do not add pages.
- Log significant decisions with their reasoning and observed outcome through the learning tools.
  A decision is a log entry, not a page.

If nothing changed, report a quiet check and propose nothing.
"""


def _build_routine_runner(agent_os: Any, model: Any) -> Optional[Agent]:
    if agent_os._company_db is None or model is None:
        return None
    from agno.company.routines import _RoutineBoundary, load_routine_skills
    from agno.db.base import AsyncBaseDb
    from agno.registry._reserved import _check_manager_catalog

    if not isinstance(agent_os._company_db, AsyncBaseDb):
        _check_manager_catalog(agent_os, agent_os._company_db)
    if agent_os.db is not None and not isinstance(agent_os.db, AsyncBaseDb):
        _check_manager_catalog(agent_os, agent_os.db)
    isolation = bool(
        agent_os.user_isolation
        or (
            agent_os.authorization
            and agent_os.authorization_config is not None
            and agent_os.authorization_config.user_isolation
        )
    )
    db = agent_os._company_db
    return Agent(
        id=ROUTINE_RUNNER_ID,
        name="Super Agent Routines",
        model=model,
        db=db,
        metadata={"_agno": {"internal": True, "id": ROUTINE_RUNNER_ID}},
        tools=[CompanyTools(db, user_isolation=isolation, decision_tools=False, interfaces=agent_os.interfaces)],
        skills=load_routine_skills(),
        learning=LearningMachine(
            db=db, model=model, decision_log=CompanyDecisionLogStore(db, user_isolation=isolation)
        ),
        instructions=INSTRUCTIONS,
        # Runs unattended on untrusted Sources, so only a Company Routine may start it.
        pre_hooks=[_RoutineBoundary(routine=True)],
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
    )
