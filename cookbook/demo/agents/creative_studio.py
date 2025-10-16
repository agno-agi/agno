"""
Creative Studio - Multimodal Agent with Guardrails and Memory
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.guardrails import PIIDetectionGuardrail, PromptInjectionGuardrail
from agno.models.openai.chat import OpenAIChat
from agno.tools.dalle import DalleTools
from agno.tools.duckduckgo import DuckDuckGoTools

# ============================================================================
# Database Configuration
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url, id="creative_studio_db")

# ============================================================================
# Multimodal Agent with Guardrails
# ============================================================================

creative_studio = Agent(
    name="Creative Studio",
    model=OpenAIChat(id="gpt-4o"),  # Vision-capable model for image analysis
    description="AI-powered creative studio that generates and analyzes images with built-in privacy protection and usage monitoring",
    instructions=[
        "You are a creative AI assistant specializing in visual content",
        "You can generate images using DALL-E based on descriptions",
        "You can analyze and describe images provided by users",
        "You can search for creative inspiration and references",
        "Always be creative, helpful, and professional",
        "When generating images, ALWAYS include the image URL in your response and provide detailed descriptions of what was created",
        "When analyzing images, provide comprehensive descriptions including:",
        "  - Main subjects and composition",
        "  - Colors, lighting, and mood",
        "  - Style and artistic elements",
        "  - Potential use cases or applications",
        "Remember past conversations to maintain creative consistency",
        "Track creative preferences and styles over time",
    ],
    tools=[
        DalleTools(),  # MULTIMODAL: Image generation
        DuckDuckGoTools(),  # TOOL HOOKS: Search with built-in monitoring via guardrails
    ],
    pre_hooks=[
        # GUARDRAILS: Security and privacy protection
        PIIDetectionGuardrail(),  # Catch sensitive personal information
        PromptInjectionGuardrail(),  # Prevent prompt injection attacks
    ],
    # Memory and context management
    enable_user_memories=True,  # Remember user preferences
    add_history_to_context=True,  # Maintain conversation history
    num_history_runs=5,  # Keep last 5 interactions in the messages sent to the model
    add_datetime_to_context=True,  # Include timestamps
    db=db,  # Persistent storage
    markdown=True,  # Format responses with markdown
)
