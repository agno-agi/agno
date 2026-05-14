"""
AgentOS Workflow HITL Examples

Run all workflow human-in-the-loop examples from this directory in one AgentOS.
"""

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

from condition_user_decision import workflow as condition_user_decision_workflow
from decision_tree import workflow as decision_tree_workflow
from dual_level_hitl import travel_agent
from dual_level_hitl import workflow as dual_level_hitl_workflow
from loop_confirmation import workflow as loop_confirmation_workflow
from output_review import workflow as output_review_workflow
from router_user_selection import workflow as router_user_selection_workflow
from step_confirmation import workflow as step_confirmation_workflow
from step_user_input import workflow as step_user_input_workflow
from step_user_input import workflow_with_executor as step_user_input_executor_workflow

db = SqliteDb(db_file="tmp/agentos_workflow_hitl_examples.db")

agent_os = AgentOS(
    id="workflow-hitl-examples",
    name="Workflow HITL Examples",
    description="All AgentOS-compatible workflow human-in-the-loop examples.",
    agents=[travel_agent],
    workflows=[
        step_confirmation_workflow,
        output_review_workflow,
        router_user_selection_workflow,
        loop_confirmation_workflow,
        condition_user_decision_workflow,
        decision_tree_workflow,
        step_user_input_workflow,
        step_user_input_executor_workflow,
        dual_level_hitl_workflow,
    ],
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="main:app", reload=True)
