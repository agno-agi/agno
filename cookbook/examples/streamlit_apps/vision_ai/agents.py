from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.streamlit import get_model_with_provider

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

EXTRACTION_PROMPT = dedent("""
    Analyze this image thoroughly and provide detailed insights. Please include:

    1. **Objects & Elements**: Identify and describe all visible objects, people, animals, or items
    2. **Text Content**: Extract any readable text, signs, labels, or written content
    3. **Scene Description**: Describe the setting, environment, and overall scene
    5. **Context & Purpose**: Infer the likely purpose, context, or story behind the image
    6. **Technical Details**: Comment on image quality, style, or photographic aspects if relevant

    Provide a comprehensive analysis that would be useful for follow-up questions.
    Be specific and detailed in your observations.
""")


def get_vision_agent(
    model_id: str = "openai:gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """Get a Vision Analysis Agent"""

    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    agent = Agent(
        name="Vision Analysis Agent",
        model=get_model_with_provider(model_id),
        db=db,
        id="vision-analysis-agent",
        user_id=user_id,
        session_id=session_id,
        instructions=dedent("""
            You are an expert vision AI assistant specialized in image analysis and understanding.
            
            Your capabilities include:
            - Detailed visual analysis of images
            - Text extraction and OCR
            - Object and scene recognition
            - Context and purpose inference
            
            Always provide:
            - Comprehensive and accurate descriptions
            - Specific details rather than generic observations
            - Well-structured responses with clear sections
            - Professional and helpful tone
        """),
        markdown=True,
        debug_mode=True,
    )

    return agent


def get_chat_agent(
    model_id: str = "openai:gpt-4o",
    enable_search: bool = False,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """Get a Chat Follow-up Agent for Vision AI"""

    tools = [DuckDuckGoTools()] if enable_search else []

    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    agent = Agent(
        name="Vision Chat Agent",
        model=get_model_with_provider(model_id),
        db=db,
        id="vision-chat-agent",
        user_id=user_id,
        session_id=session_id,
        tools=tools,
        add_history_to_context=True,
        num_history_runs=5,
        instructions=dedent("""
            You are a helpful assistant that answers follow-up questions about images that have been analyzed.
            
            You will be provided with:
            1. Previous image analysis results
            2. User's follow-up questions
            
            Your role is to:
            - Answer questions based on the image analysis data
            - Provide additional insights when requested
            - Use web search (if enabled) for additional context
            - Maintain conversation flow and context
            
            Always:
            - Reference the specific image analysis when answering
            - Be accurate and detailed in your responses
            - Ask for clarification if questions are ambiguous
            - Suggest related questions that might be helpful
        """),
        markdown=True,
        debug_mode=True,
    )

    return agent
