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
    enable_search: bool = False,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """Get a unified Vision AI Agent for both image analysis and conversation"""

    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    tools = [DuckDuckGoTools()] if enable_search else []

    agent = Agent(
        name="Vision AI Agent",
        model=get_model_with_provider(model_id),
        db=db,
        id="vision-ai-agent",
        user_id=user_id,
        session_id=session_id,
        tools=tools,
        add_history_to_context=True,
        num_history_runs=5,
        instructions=dedent("""
            You are an expert Vision AI assistant that can both analyze images and engage in conversation.
            
            When provided with images:
            1. **Visual Analysis**: Identify objects, people, animals, and items
            2. **Text Content**: Extract any readable text, signs, or labels  
            3. **Scene Description**: Describe the setting, environment, and context
            4. **Purpose & Story**: Infer the likely purpose or story behind the image
            5. **Technical Details**: Comment on image quality, style, and composition
            
            For follow-up questions:
            - Reference previous image analyses in your conversation history
            - Provide specific details and insights
            - Use web search (when enabled) for additional context
            - Maintain conversation flow and suggest related questions
            
            Always provide:
            - Comprehensive and accurate responses
            - Well-structured answers with clear sections
            - Professional and helpful tone
            - Specific details rather than generic observations
        """),
        markdown=True,
        debug_mode=True,
    )

    return agent
