from pathlib import Path

from agno.utils.log import logger
from sql_agent import sql_agent_knowledge

# ============================================================================
# Path to SQL Agent Knowledge
# ============================================================================
cwd = Path(__file__).parent
knowledge_dir = cwd.joinpath("knowledge")

# ============================================================================
# Load SQL Agent Knowledge
# ============================================================================
if __name__ == "__main__":
    logger.info(f"Loading SQL Agent Knowledge from {knowledge_dir}")
    sql_agent_knowledge.add_content(path=str(knowledge_dir))
    logger.info("SQL Agent Knowledge loaded.")
