"""
Main entry point for Multi-Agent B2B Pipeline Builder
Creates workflow and exposes via AgentOS for UI interaction
"""

import logging
import os

from dotenv import load_dotenv
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.workflow import Step, Workflow

from agents import data_enricher, icp_scorer, linkedin_message_generator

# Load environment variables from .env file
load_dotenv()

# Setup logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Setup SQLite database for workflow sessions
sqlite_db_path = os.getenv("SQLITE_DB_PATH", "tmp/agno_sessions.db")
sqlite_dir = os.path.dirname(sqlite_db_path)
if sqlite_dir:
    os.makedirs(sqlite_dir, exist_ok=True)
db = SqliteDb(db_file=sqlite_db_path)

# Define workflow steps
data_enrichment_step = Step(
    name="Data Enrichment",
    agent=data_enricher,
    description="Search and enrich lead profiles with firmographics",
)

icp_scoring_step = Step(
    name="ICP Scoring",
    agent=icp_scorer,
    description="Score leads against ICP criteria with weighted analysis",
)

message_generation_step = Step(
    name="LinkedIn Message Generation",
    agent=linkedin_message_generator,
    description="Generate personalized LinkedIn messages for scored leads",
)

# Create the workflow
b2b_pipeline_workflow = Workflow(
    name="B2B Pipeline Builder",
    description="Multi-agent pipeline: Data Enrichment -> ICP Scoring -> LinkedIn Message Generation",
    db=db,
    steps=[
        data_enrichment_step,
        icp_scoring_step,
        message_generation_step,
    ],
)

# Initialize AgentOS with the workflow
agent_os = AgentOS(
    description="B2B Pipeline Builder - Enrich leads, score against ICP, generate LinkedIn messages",
    workflows=[b2b_pipeline_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    logger.info("🚀 Starting B2B Pipeline Builder AgentOS...")
    logger.info("📊 Access UI at: http://localhost:7777")
    logger.info("📝 API Docs at: http://localhost:7777/docs")
    logger.info("Example prompts:")
    logger.info('  - "Get me 5 sales directors in London"')
    logger.info('  - "Get me 5 Marketing Managers in New York"')
    agent_os.serve(app="main:app", reload=True)

