"""
This cookbook demonstrates how to get an agent from the database.
"""

from agno.db.postgres import PostgresDb
from agno.workflow.workflow import get_workflow_by_id, get_workflows

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

workflow = get_workflow_by_id(db=db, id="content-creation-workflow")

workflow.print_response(input="AI trends in 2024", markdown=True)

# You can also get all workflows from the database
# workflows = get_workflows(db=db)
# for workflow in workflows:
#     print(workflow)
