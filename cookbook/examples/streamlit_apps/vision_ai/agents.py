from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools


def image_processing_agent(
    model,
) -> Agent:
    extraction_agent = Agent(
        name="image_analysis_agent",
        model=model,
        markdown=True,
    )

    return extraction_agent


def chat_followup_agent(
    model,
    enable_search: bool = False,
) -> Agent:
    tools = [DuckDuckGoTools()] if enable_search else []
    followup_agent = Agent(
        name="image_chat_followup_agent",
        model=model,
        tools=tools,
        read_chat_history=True,
        add_history_to_messages=True,
        num_history_responses=5,
        markdown=True,
        add_datetime_to_instructions=True,
    )

    return followup_agent
