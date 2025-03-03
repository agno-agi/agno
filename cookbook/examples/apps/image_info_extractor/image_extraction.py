from typing import Optional

from agno.agent import Agent
from agno.storage.agent.postgres import PostgresAgentStorage

# ************* Database Connection *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
# *******************************


def image_processing_agent(
    model,
    user_id: Optional[str] = None,
) -> Agent:
    extraction_agent = Agent(
        name="image_analysis_agent",
        model=model,
        user_id=user_id,
        storage=PostgresAgentStorage(db_url=db_url, table_name="image_analysis_runs_2"),
        read_chat_history=True,
        add_history_to_messages=True,
        num_history_responses=5,
        markdown=True,
        add_datetime_to_instructions=True,
    )

    return extraction_agent
