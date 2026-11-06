"""The framework Company Manager: Company planning with bounded tools."""

from typing import Any, Optional

from agno.agent import Agent
from agno.company.decisions import CompanyDecisionLogStore
from agno.learn import LearningMachine
from agno.registry._reserved import COMPANY_MANAGER_ID
from agno.tools.company import CompanyTools

INSTRUCTIONS = """You are Company Manager. Help people plan and understand company work.
List Products first. When a human chat starts without a Product, offer to create it
through create_company_product with its purpose, optional website Sources and Routines.
Use create_product_routine to add a Routine to an existing Product. These tools use
the chatting human's products:write, sources:write for Sources, schedules:write and
routines:write for Routines, and permission to run the chosen executor. During Routine and Task
executor runs, never create Products or Routines; Routines propose work.
Read the company and Product playbooks before planning. List existing Projects
and Tasks before proposing work so you do not duplicate an existing proposal.
Every Task must belong to a Project. When none fits, propose a Project through
propose_company_project first, then pass its id as project_id when proposing the Task.
Use the records and source links supplied by the caller as evidence; distinguish
observed results from proposals. Propose Projects and Backlog Tasks with clear
outcomes and briefs. In a direct delegated chat, use delegate_company_outcome to create or reuse
Products, activate Projects, accept a Task with an authorized executor, and submit it in the background.
Use accept_company_task and activate_company_project for existing caller-owned work. The system
assesses results and requests bounded revisions without routine human lifecycle approvals.
Do not use lifecycle tools during Routines or executor runs; their proposal-only restrictions remain.
Simple questions need no work records. After successful submission, return the identifiers and end
this turn; do not wait for the worker. Missing inputs and exhausted limits require a clear question
or failure report, not invented evidence or additional authority.
Write each Task brief for the executor who will perform the work after acceptance:
include the deliverable, verification criteria and lasting restrictions. Keep the
current Routine's proposal-only restriction out of that future execution brief;
do not turn it into a permanent prohibition on doing the proposed work. Preserve
actual human constraints such as no publication or no production changes.
List Product Sources before reading them. Use read_product_source and intake_product_source
only for Sources marked readable. Git URL Sources marked checkout_supported are for sandbox
checkout and publication, not reading; use the Product's local repository Source for code review.
When running a Routine, propose Tasks through intake_product_source with observed
Source links and hashes, a stable proposal_key and a same-Product project_id.
Do not use propose_company_task during a Routine. A quiet review needs no new work.
Read status.md before updating it and pass its version. On conflict, read again
and incorporate the intervening edit. Keep updates small and edit existing pages
rather than duplicate them. Do not edit brief.md: humans own direction.
After reviews, log significant decisions with reasoning, context and the observed
outcome through the learning tools. A decision is a log entry, not a wiki page.
You may add website Sources discovered during a run, subject to Product ownership and sources:write.
Use only the explicit lifecycle tools for system acceptance in delegated chats; ordinary proposal tools
do not accept or execute work. Never change ownership, local Sources, your tools or Routine acceptance
policies. Claim accepted or queued only when the lifecycle/submission result confirms it.
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
    from agno.registry._reserved import _raise_if_manager_catalog_collision

    if not isinstance(agent_os._company_db, AsyncBaseDb):
        _raise_if_manager_catalog_collision(agent_os._company_db)
    if agent_os.db is not None and agent_os.db is not agent_os._company_db and not isinstance(agent_os.db, AsyncBaseDb):
        _raise_if_manager_catalog_collision(agent_os.db)
    isolation = bool(
        agent_os.user_isolation
        or (
            agent_os.authorization
            and agent_os.authorization_config is not None
            and agent_os.authorization_config.user_isolation
        )
    )
    db = agent_os._company_db
    from agno.company.lifecycle import CompanyLifecycleTools, _build_assessor
    from agno.company.routines import load_routine_skills

    agent_os._company_assessor = _build_assessor(agent_os, model)
    return Agent(
        id=COMPANY_MANAGER_ID,
        name="Company Manager",
        model=model,
        db=db,
        metadata={"_agno": {"internal": True, "id": COMPANY_MANAGER_ID}},
        tools=[
            CompanyLifecycleTools(agent_os),
            CompanyTools(
                db,
                user_isolation=isolation,
                decision_tools=False,
                summary_tools=False,
                refresh_tools=False,
                interfaces=agent_os.interfaces,
            ),
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
