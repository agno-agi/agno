"""
Load Workflow from Database
===========================

Demonstrates loading a workflow from the database by ID and running it.
"""

from agno.db.postgres import PostgresDb
from agno.workflow.workflow import get_workflow_by_id, get_workflows  # noqa: F401

# ---------------------------------------------------------------------------
# Create Database Client
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Run Workflow Load Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    workflow = get_workflow_by_id(db=db, id="content-creation-workflow")

    if workflow:
        workflow.print_response(input="AI trends in 2024", markdown=True)
    else:
        print("Workflow not found")

    # You can also get all workflows from the database
    # workflows = get_workflows(db=db)
    # for workflow in workflows:
    #     print(workflow)
