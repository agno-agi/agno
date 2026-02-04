"""
Schedule Workflow Example

This example demonstrates scheduling workflow executions.
Workflows can be scheduled just like agents.

Requirements:
    pip install agno[scheduler]

Run:
    python cookbook/05_agent_os/scheduler/03_schedule_workflow.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.workflow import Workflow


class ReportWorkflow(Workflow):
    """A workflow that generates a multi-step report."""

    id: str = "report-workflow"
    description: str = "Generate a comprehensive report with multiple steps"

    # Define agents used in the workflow
    researcher: Agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher. Gather key facts about the given topic.",
    )

    writer: Agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a report writer. Write a clear summary based on research.",
    )

    def run(self, topic: str = "AI trends") -> str:
        """Run the report generation workflow."""
        # Step 1: Research
        research = self.researcher.run(f"Research key facts about: {topic}")

        # Step 2: Write report
        report = self.writer.run(
            f"Write a brief report based on this research:\n{research.content}"
        )

        return report.content


# Create database and AgentOS
db = SqliteDb(db_file="scheduled_workflow.db")
agent_os = AgentOS(
    workflows=[ReportWorkflow()],
    db=db,
    enable_scheduler=True,
    scheduler_poll_interval=10,
)

if __name__ == "__main__":
    print("Starting AgentOS with scheduled workflow...")
    print("\nAvailable workflow:")
    print("  - report-workflow: Generates research-based reports")
    print("\nCreate a schedule to run the workflow:")
    print("""
    curl -X POST http://localhost:7777/v1/schedules \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "weekly-ai-report",
        "endpoint": "/v1/workflows/report-workflow/runs",
        "method": "POST",
        "payload": {"topic": "Latest AI developments"},
        "cron_expr": "0 9 * * 1"
      }'
    """)

    agent_os.run(port=7777)
