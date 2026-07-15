"""
Human in the Loop — Dojo Demo
==============================

Frontend-provided tool: generate_task_steps (external_execution)

The frontend defines this tool via useHumanInTheLoop hook. The agent calls it,
and the frontend renders an interactive step-selector UI where the user can
toggle steps on/off and confirm.

Backend does NOT define the tool — it comes from the frontend in the request.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

hitl_agent = Agent(
    name="human_in_the_loop",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_human_in_the_loop.db"),
    instructions="""You are a task planning assistant. When asked to plan something:

1. **IMMEDIATELY call the generate_task_steps tool** with a list of steps
2. Generate exactly 10 clear, actionable steps
3. Each step must be an object with:
   - description: Brief imperative form (e.g., "Research travel options")
   - status: Set to "enabled" initially

Example tool call for "plan a trip to Mars":
{
  "steps": [
    {"description": "Research Mars travel options", "status": "enabled"},
    {"description": "Prepare necessary equipment", "status": "enabled"},
    {"description": "Complete health screenings", "status": "enabled"},
    ...
  ]
}

After calling the tool:
- Briefly confirm: "I've created a 10-step plan for you!"
- Don't repeat the steps (they're visible in the UI)
- Ask the user to review and select which steps to perform

When user provides feedback (after clicking "Perform Steps"):
- Acknowledge which steps were approved
- Provide a brief summary of next actions""",
    markdown=True,
)
