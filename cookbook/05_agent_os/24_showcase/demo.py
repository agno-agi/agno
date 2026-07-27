"""
Run the Complete AgentOS Showcase
=================================

Load Agno documentation into pgvector, run and store one real AccuracyEval,
then serve two Agents and one finance Team with authentication and tracing.

Prerequisites: Postgres on port 5532, OPENAI_API_KEY, ANTHROPIC_API_KEY, and OS_SECURITY_KEY
Run: .venvs/demo/bin/python -m cookbook.05_agent_os.24_showcase.demo
Try: authenticate to GET /config, then run agno-assist, sage, or finance-team
"""

import os
from importlib import import_module

from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings

agents_module = import_module("cookbook.05_agent_os.24_showcase._agents")
teams_module = import_module("cookbook.05_agent_os.24_showcase._teams")

AGNO_DOCS_URL = agents_module.AGNO_DOCS_URL
agno_assist = agents_module.agno_assist
agno_docs = agents_module.agno_docs
sage = agents_module.sage
showcase_db = agents_module.showcase_db
finance_team = teams_module.finance_team

security_key = os.getenv("OS_SECURITY_KEY")
if not security_key:
    raise ValueError("OS_SECURITY_KEY is required for the authenticated showcase")
showcase_port = int(os.getenv("SHOWCASE_PORT", "7777"))

# ---------------------------------------------------------------------------
# Create Secured and Traced AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="agent-os-showcase",
    name="AgentOS Showcase",
    description="A secured, traced AgentOS with RAG, research, finance, and evaluation.",
    db=showcase_db,
    agents=[agno_assist, sage],
    teams=[finance_team],
    knowledge=[agno_docs],
    tracing=True,
    settings=AgnoAPISettings(os_security_key=security_key),
)
app = agent_os.get_app()

accuracy_evaluation = AccuracyEval(
    db=showcase_db,
    name="AgentOS Documentation Accuracy",
    model=Claude(id="claude-sonnet-4-6"),
    agent=agno_assist,
    input="Which three component types can AgentOS serve?",
    expected_output="AgentOS can serve Agents, Teams, and Workflows.",
    additional_guidelines=[
        "Accept capitalization and singular or plural variations.",
        "The answer must identify all three component types.",
    ],
    num_iterations=1,
    show_spinner=False,
)


def prepare_knowledge() -> int:
    """Load the docs page and prove pgvector can retrieve it."""
    agno_docs.insert(
        name="Agno introduction",
        url=AGNO_DOCS_URL,
        skip_if_exists=True,
    )
    matches = agno_docs.search(
        "Which components can AgentOS serve?",
        max_results=3,
    )
    if not matches:
        raise RuntimeError("The Agno documentation load produced no vector matches")
    print(f"Knowledge search returned {len(matches)} pgvector match(es)")
    return len(matches)


def run_accuracy_evaluation() -> AccuracyResult:
    """Run the live judge evaluation and require one stored result."""
    result = accuracy_evaluation.run(
        print_summary=True,
        print_results=False,
    )
    if result is None or not result.results:
        raise RuntimeError("The showcase AccuracyEval produced no result")
    if showcase_db.get_eval_run(accuracy_evaluation.eval_id) is None:
        raise RuntimeError("The showcase AccuracyEval was not stored")
    print(
        f"AccuracyEval stored {len(result.results)} result(s); "
        f"average score={result.avg_score}"
    )
    return result


# ---------------------------------------------------------------------------
# Run the Showcase
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    prepare_knowledge()
    run_accuracy_evaluation()
    agent_os.serve(
        app="cookbook.05_agent_os.24_showcase.demo:app",
        host="127.0.0.1",
        port=showcase_port,
    )
