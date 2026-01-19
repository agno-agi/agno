"""
Example: Per-Hook Background Control with AgentAsJudgeEval in AgentOS

This example demonstrates fine-grained control over which hooks run in background:
- Set eval.run_in_background = True for eval instances
- AgentAsJudgeEval evaluates output quality based on custom criteria
"""

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Setup database
db = AsyncSqliteDb(db_file="tmp/agent_as_judge_evals.db")

# AgentAsJudgeEval for completeness - runs synchronously (blocks response)
completeness_eval = AgentAsJudgeEval(
    db=db,
    name="Completeness Check",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be thorough, complete, and address all aspects of the question",
    print_results=True,
    print_summary=True,
    telemetry=True,
)
# completeness_eval.run_in_background = False (default - blocks)

# AgentAsJudgeEval for quality - runs in background (non-blocking)
quality_eval = AgentAsJudgeEval(
    db=db,
    name="Quality Assessment",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be well-structured, concise, and professional",
    scoring_strategy="numeric",
    threshold=8,
    additional_guidelines=[
        "Check if response is easy to understand",
        "Verify response is not overly verbose",
    ],
    print_results=True,
    print_summary=True,
    run_in_background=True,  # Run this eval as a background task
)

agent = Agent(
    id="geography-agent",
    name="GeographyAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a helpful geography assistant. Provide accurate and concise answers.",
    db=db,
    post_hooks=[
        completeness_eval,  # run_in_background=False - runs first, blocks
        quality_eval,  # run_in_background=True - runs after response
    ],
    markdown=True,
    telemetry=False,
)

# Create AgentOS
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

# Flow:
# 1. Agent processes request
# 2. Sync hooks run (completeness_eval)
# 3. Response sent to user
# 4. Background hooks run (quality_eval)

# Test with:
# curl -X POST http://localhost:7777/agents/geography-agent/runs \
#   -F "message=What is the capital of France?" -F "stream=false"

if __name__ == "__main__":
    agent_os.serve(app="background_evals_example:app", port=7777, reload=True)
