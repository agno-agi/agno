import asyncio
from datetime import datetime

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.exa import ExaTools
from agno.workflow import WorkflowAgent
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from db import demo_db

# =========================
# CONFIG
# =========================
MODEL_ID = "claude-sonnet-4-5"

# =========================
# AGENTS
# =========================
outline_planner = Agent(
    name="OutlinePlanner",
    model=Claude(id=MODEL_ID),
    instructions=(
        "You normalize inputs for generating competitive briefs.\n"
        "- Extract vendor/company names mentioned by the user; dedupe and preserve input order.\n"
        "- If the user specifies focus areas, extract them; otherwise default to "
        "  ['pricing','integrations','features','architecture'].\n"
        "- Produce a compact outline with sections exactly: Positioning, Pricing, Integrations, Risks.\n"
        "- Return a concise plan (<= 100 words) as a tight JSON-ish block with keys:\n"
        "  companies: [...]\n"
        "  focus_areas: [...]\n"
        "  outline: ['Positioning','Pricing','Integrations','Risks']\n"
        "Keep it deterministic and do not add extra prose."
    ),
)

comparator = Agent(
    name="Comparator",
    model=Claude(id=MODEL_ID),
    tools=[
        ExaTools(
            start_published_date=datetime.now().strftime("%Y-%m-%d"), type="keyword"
        )
    ],
    instructions=(
        "You produce a concise, business-credible competitive brief using the plan.\n"
        "- Target length: <= 220 words.\n"
        "- Use sections exactly as in the plan: (e.g. Positioning, Pricing, Integrations, Risks, TL;DR).\n"
        "- Include an explicit list: Top 3 Differences.\n"
        "- If tools are available, call them to retrieve the latest info on named companies; cite inline briefly (e.g., '(via Exa)').\n"
        "- End with a short machine-readable metadata block:\n"
        "  companies: [...]\n"
        "  focus_areas: [...]\n"
        "  top_3_differences: ['A','B','C']\n"
        "Respond in clean Markdown with short bullets; avoid fluff."
    ),
)

# =========================
# WORKFLOW STEPS
# =========================
plan_step = Step(
    name="plan_outline",
    description="Normalize vendors/focus areas and produce a brief outline",
    agent=outline_planner,
)

compare_step = Step(
    name="generate_comparison",
    description="Produce concise competitive brief + Top 3 Pricing Differences",
    agent=comparator,
)

# =========================
# WORKFLOW AGENT (brains)
# =========================
workflow_agent = WorkflowAgent(model=Claude(id=MODEL_ID), num_history_runs=4)

# =========================
# WORKFLOW
# =========================
competitive_brief = Workflow(
    name="Competitive Brief",
    description="Generate a competitive brief between two products. First plan the brief, then compare the products.",
    agent=workflow_agent,
    steps=[plan_step, compare_step],
    db=demo_db,
)


# =========================
# DEMO SCRIPT
# =========================
async def main():
    BANNER = "=" * 80

    # 1) First call — runs workflow (streams events)
    print(
        f"\n{BANNER}\nFIRST CALL: Create a competitive brief for Agno vs LangChain focusing on features and architecture.\n{BANNER}"
    )
    await competitive_brief.aprint_response(
        "Create a competitive brief for Agno vs LangChain focusing on features and architecture.",
        stream=True,
        stream_events=True,
    )

    # 2) Follow-up — should answer from history (no re-run)
    print(
        f"\n{BANNER}\nSECOND CALL: Which one would you recommend for a new project?\n{BANNER}"
    )
    await competitive_brief.aprint_response(
        "Which one would you recommend for a new project?",
        stream=True,
        stream_events=True,  # stays True so the audience can see that nothing re-runs
    )

    # 3) Scope change — introduces new vendor; should trigger re-run
    print(f"\n{BANNER}\nTHIRD CALL: Now add CrewAI to the comparison.\n{BANNER}")
    await competitive_brief.aprint_response(
        "Now add CrewAI to the comparison.",
        stream=True,
        stream_events=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
