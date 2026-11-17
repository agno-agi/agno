"""
Eval Suite on AgentOS
=====================

Register an eval suite on AgentOS, so it can be listed and run over HTTP, and
its pass rate read back from the eval runs like any other eval.

python cookbook/09_evals/suite/suite_agent_os.py

Try:
    curl http://localhost:7777/eval-suites
    curl -X POST http://localhost:7777/eval-suites/math-tutor-quality/runs -H "Content-Type: application/json" -d '{}'
    curl -X POST http://localhost:7777/eval-suites -H "Content-Type: application/json" -d '{"name": "posted", "cases": [{"name": "adds", "agent_id": "math-tutor", "input": "What is 2 + 2?", "expected_tool_calls": ["add"]}]}'
    curl "http://localhost:7777/eval-runs?agent_id=math-tutor&eval_types=suite"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval import Case, EvalSuite
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agentos.db")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="math-tutor",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[CalculatorTools()],
    instructions="Use the calculator tools for any arithmetic.",
)

# ---------------------------------------------------------------------------
# Declare Suite
# ---------------------------------------------------------------------------
suite = EvalSuite(
    id="math-tutor-quality",
    name="Math tutor quality",
    cases=(
        Case(
            name="factorial_uses_calculator",
            agent=agent,
            input="What is 10! (ten factorial)?",
            tags=("smoke",),
            criteria="States that 10! equals 3628800.",
            expected_tool_calls=("factorial",),
        ),
        Case(
            name="explains_compound_interest",
            agent=agent,
            input="Explain compound interest in one short paragraph.",
            criteria="Explains that interest is earned on both the principal and previously earned interest.",
        ),
    ),
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(agents=[agent], eval_suites=[suite], db=db)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="suite_agent_os:app", reload=True)
