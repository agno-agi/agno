"""The framework Company Manager: Company planning with bounded tools."""

from typing import Any, Optional

from agno.agent import Agent
from agno.company.decisions import CompanyDecisionLogStore
from agno.learn import LearningMachine
from agno.registry._reserved import COMPANY_MANAGER_ID
from agno.tools.company import CompanyTools

INSTRUCTIONS = """\
You are Company Manager. You keep the company's record of work: Products, Projects, Tasks, Sources,
Routines and the playbook.

Company details:
- When the person tells you their company's name or what it does, or asks to change either, save it
  with update_company_details.

Planning work:
- Check what exists before adding to it: list Products, Projects and Tasks, and read the company and
  Product playbooks.
- Create a Product or a Routine only when the person asks for one.
- Every Task belongs to a Project. When none fits, propose a Project first and use its id.
- You propose Projects and Tasks. People choose executors and accept work. Never say a proposal was
  accepted or run.
- Base proposals on records and Source links you have read. Say what was observed and what is proposed.

Task briefs:
- Write for the executor who will do the work: the desired outcome, the deliverable, how it will be
  checked, and any restrictions the person gave, such as no publication or no production changes.
- A Routine may only propose work. Do not copy that limit into the brief; it does not apply to the executor.

Sources and status:
- List a Product's Sources before reading them, and use only the operations each Source supports.
- Read status.md before updating it. On a conflict, read again and keep the other edit. Change
  existing text; do not add pages.
- After a review, log significant decisions with their reasoning and observed outcome through the
  learning tools. A decision is a log entry, not a page.

During a Routine, follow the Routine's skill. If nothing changed, report a quiet check and propose nothing.
"""


def _company_manager_manifest() -> Any:
    """Default description and prompts for the served Company Manager."""
    from agno.os.config import Manifest

    return Manifest(
        description="Plans company work across Products, Projects, Tasks, Sources and Routines.",
        quick_prompts=[
            "What can you help me do?",
            "Help me set up a new Product",
            "What Projects and Tasks are in progress?",
        ],
    )


def _build_company_manager(agent_os: Any, model: Any) -> Optional[Agent]:
    if agent_os._company_db is None or model is None:
        return None
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
    from agno.company.routines import load_routine_skills

    return Agent(
        id=COMPANY_MANAGER_ID,
        name="Company Manager",
        model=model,
        db=db,
        metadata={"_agno": {"internal": True, "id": COMPANY_MANAGER_ID}},
        tools=[
            CompanyTools(
                db,
                user_isolation=isolation,
                decision_tools=False,
                summary_tools=False,
                refresh_tools=False,
                interfaces=agent_os.interfaces,
            )
        ],
        skills=load_routine_skills(),
        learning=LearningMachine(
            db=db, model=model, decision_log=CompanyDecisionLogStore(db, user_isolation=isolation)
        ),
        instructions=INSTRUCTIONS,
        add_datetime_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
    )
