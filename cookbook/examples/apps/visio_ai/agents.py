from typing import Optional

from agno.agent import Agent
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from config import db_url


def image_processing_agent(
    model,
    user_id: Optional[str] = None,
    enable_search: bool = False,
) -> Agent:
    tools = [DuckDuckGoTools()] if enable_search else []
    extraction_agent = Agent(
        name="image_analysis_agent",
        model=model,
        user_id=user_id,
        tools=tools,
        storage=PostgresAgentStorage(db_url=db_url, table_name="image_analysis_runs"),
        markdown=True,
    )

    return extraction_agent


def chat_followup_agent(
    model,
    user_id: Optional[str] = None,
    enable_search: bool = False,
) -> Agent:
    tools = [DuckDuckGoTools()] if enable_search else []
    followup_agent = Agent(
        name="image_chat_followup_agent",
        model=model,
        user_id=user_id,
        tools=tools,
        storage=PostgresAgentStorage(
            db_url=db_url, table_name="image_analysis_followup"
        ),
        read_chat_history=True,
        add_history_to_messages=True,
        num_history_responses=5,
        markdown=True,
        add_datetime_to_instructions=True,
    )

    return followup_agent
