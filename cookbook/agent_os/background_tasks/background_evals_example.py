"""
Example: Per-Hook Background Control with CriteriaEval in AgentOS

This example demonstrates fine-grained control over which hooks run in background:
- Set eval.run_in_background = True for eval instances
- CriteriaEval evaluates output quality based on custom criteria
"""

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.eval.criteria import CriteriaEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Setup database
db = AsyncSqliteDb(db_file="tmp/criteria_evals.db")

# CriteriaEval for accuracy - runs synchronously (blocks response)
accuracy_criteria = CriteriaEval(
    db=db,
    name="Accuracy Check",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be factually correct and complete",
    threshold=7,
    num_iterations=2,
    print_results=True,
    print_summary=True,
    telemetry=True,
)
# accuracy_criteria.run_in_background = False (default - blocks)

# CriteriaEval for quality - runs in background (non-blocking)
quality_criteria = CriteriaEval(
    db=db,
    name="Quality Assessment",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be well-structured, concise, and professional",
    threshold=8,
    num_iterations=2,
    additional_guidelines=[
        "Check if response is easy to understand",
        "Verify response is not overly verbose",
    ],
    print_results=True,
    print_summary=True,
    telemetry=True,
)
quality_criteria.run_in_background = True

agent = Agent(
    id="geography-agent",
    name="GeographyAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a helpful geography assistant. Provide accurate and concise answers.",
    db=db,
    post_hooks=[
        accuracy_criteria,  # run_in_background=False - runs first, blocks
        quality_criteria,  # run_in_background=True - runs after response
    ],
    markdown=True,
    telemetry=False,
)

# Create AgentOS
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

# Flow:
# 1. Agent processes request
# 2. Sync hooks run (accuracy_criteria)
# 3. Response sent to user
# 4. Background hooks run (quality_criteria)

# Test with:
# curl -X POST http://localhost:7777/agents/geography-agent/runs \
#   -F "message=What is the capital of France?" -F "stream=false"

if __name__ == "__main__":
    agent_os.serve(app="background_evals_example:app", port=7777, reload=True)
