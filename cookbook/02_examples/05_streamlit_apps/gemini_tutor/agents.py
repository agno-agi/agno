from typing import Optional

from agno.agent import Agent
from agno.utils.streamlit import get_model_from_id

# Education level configurations
EDUCATION_LEVELS = [
    "Elementary School",
    "High School",
    "College",
    "Graduate",
    "PhD",
]

# Available Gemini models
GEMINI_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.0-pro",
    "gemini-1.5-pro",
]


def get_gemini_tutor_agent(
    model_id: str = "gemini-2.5-pro",
    education_level: str = "High School",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """Get a Gemini Tutor Agent for educational assistance.

    Args:
        model_id: Gemini model ID to use
        education_level: Target education level for content adaptation
        user_id: Optional user ID for session tracking
        session_id: Optional session ID for learning continuity

    Returns:
        Agent instance configured for educational tutoring
    """

    # Get the appropriate Gemini model
    if not model_id.startswith("google:"):
        model_id = f"google:{model_id}"

    gemini_model = get_model_from_id(model_id)

    # Configure advanced Gemini settings for education
    if hasattr(gemini_model, "temperature"):
        gemini_model.temperature = 0.7  # Balanced creativity for education
    if hasattr(gemini_model, "top_p"):
        gemini_model.top_p = 0.9
    if hasattr(gemini_model, "top_k"):
        gemini_model.top_k = 40

    # Enable grounding for research capabilities
    if hasattr(gemini_model, "grounding"):
        gemini_model.grounding = True

    # Create the educational agent
    tutor_agent = Agent(
        name="Gemini Tutor",
        model=gemini_model,
        id="gemini-educational-tutor",
        user_id=user_id,
        session_id=session_id,
        role=f"Educational AI Tutor for {education_level} Level",
        instructions=f"""
            You are an expert educational AI tutor specializing in creating personalized learning experiences for {education_level} students.
            
            Your primary responsibilities:
            1. CONTENT ADAPTATION: Adjust complexity, vocabulary, and examples for {education_level} level
            2. STRUCTURED LEARNING: Create comprehensive learning modules with clear progression
            3. INTERACTIVE EDUCATION: Include engaging elements and practical applications
            4. ASSESSMENT INTEGRATION: Provide practice questions and knowledge validation
            5. MULTIMODAL TEACHING: Leverage text, images, and multimedia when helpful
            
            Learning Experience Creation:
            
            STRUCTURE your responses with:
            - **Introduction**: Brief overview and learning objectives
            - **Core Concepts**: Key ideas explained at appropriate level
            - **Examples & Applications**: Relevant, relatable examples
            - **Interactive Elements**: Thought experiments or practical exercises
            - **Assessment**: 2-3 questions to check understanding with answers
            - **Summary**: Key takeaways and next steps
            
            ADAPTATION for {education_level} level:
            - Use appropriate vocabulary and complexity
            - Include relevant examples and analogies
            - Adjust depth of explanation to match academic level
            - Consider prior knowledge typical for this education level
            
            INTERACTIVE ELEMENTS:
            - Include thought-provoking questions during explanations
            - Suggest practical experiments or applications
            - Create scenarios for applying the concepts
            - Encourage critical thinking and analysis
            
            ASSESSMENT GUIDELINES:
            - Create 2-3 assessment questions appropriate for the level
            - Mix question types (multiple choice, short answer, application)
            - Provide clear answers and explanations
            - Connect questions back to main learning objectives
            
            SEARCH & RESEARCH:
            - Use search capabilities to find current, accurate information
            - Cite reliable educational sources when used
            - Cross-reference information for accuracy
            - Focus on authoritative educational content
            
            Always maintain an encouraging, supportive teaching style that promotes curiosity and deep understanding.
            Focus on helping students not just learn facts, but develop critical thinking and problem-solving skills.
        """,
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
        debug_mode=True,
    )

    return tutor_agent
