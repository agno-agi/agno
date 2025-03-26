"""
Gemini Tutor: Advanced Educational AI Assistant powered by Gemini 2.5
"""

import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

import dotenv
from agno.agent import Agent
from agno.models.google import Gemini
from agno.media import Image, Audio, Video
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.file import FileTools

# Load environment variables
dotenv.load_dotenv()

# Constants
output_dir = "output"
agent_storage = None  # Will be configured in app.py

EXPECTED_OUTPUT_TEMPLATE = """
Your response should follow this structure:

1. Direct Answer
   - Clear, concise response to the query
   - Appropriate for the specified education level

2. Detailed Explanation
   - Step-by-step breakdown
   - Supporting evidence and examples
   - Visual aids or diagrams when helpful

3. Interactive Elements
   - Practice questions
   - Key takeaways
   - Further reading suggestions

4. Learning Assessment
   - Quick quiz or self-check
   - Common misconceptions addressed
   - Application exercises
"""

def tutor_agent(
    user_id: Optional[str] = None,
    model_id: str = "gemini-2.5-pro-exp-03-25",
    session_id: Optional[str] = None,
    num_history_responses: int = 5,
    debug_mode: bool = True,
    education_level: str = "High School",
) -> Agent:
    """
    Returns an instance of Gemini Tutor, an educational AI assistant leveraging Gemini 2.5's advanced capabilities
    for personalized learning experiences.

    Gemini Tutor will:
      - Use Gemini 2.5 Pro's enhanced reasoning and thinking capabilities
      - Process multimodal content (text, images, audio, video)
      - Leverage 1 million token context window for comprehensive understanding
      - Utilize DuckDuckGoTools for real-time web searches
      - Use ExaTools for in-depth analysis
      - Generate comprehensive educational content with:
          • Direct, level-appropriate answers
          • Step-by-step reasoning for complex problems
          • Detailed explanations with visual aids
          • Code examples and interactive learning elements
          • Practice exercises and assessments
      - Save lessons for future reference

    Args:
        user_id: Optional identifier for the user
        model_id: Model identifier (default: "gemini-2.5-pro-exp-03-25")
        session_id: Optional session identifier
        num_history_responses: Number of previous responses to include
        debug_mode: Enable logging and debug features
        education_level: Education level for tailoring responses

    Returns:
        An instance of the configured Agent
    """
    # Get API keys
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    exa_api_key = os.environ.get("EXA_API_KEY")

    # Initialize Gemini model with advanced parameters
    model = Gemini(
        id=model_id,
        api_key=google_api_key,
        temperature=0.7,
        top_p=0.9,
        top_k=40,
        max_output_tokens=4096,  # Increased output token limit
    )

    # Tools for Gemini Tutor
    tools = [
        ExaTools(
            api_key=exa_api_key,
            start_published_date=datetime.now().strftime("%Y-%m-%d"),
            type="keyword",
            num_results=10,
        ),
        DuckDuckGoTools(
            timeout=20,
            fixed_max_results=5,
        ),
        FileTools(base_dir=output_dir),
    ]

    # Tutor description with Gemini 2.5 Pro's strengths
    tutor_description = f"""You are Gemini Tutor, an advanced educational AI assistant powered by Gemini 2.5 Pro Experimental.
    You excel at:
      - Complex reasoning and thinking for difficult problems
      - Processing multimodal content (text, images, audio, video)
      - Leveraging a 1 million token context window
      - Advanced code generation and explanation
      - Mathematical and scientific problem-solving
      - Interactive learning experiences
      - Visual explanations and diagrams
      - Real-time information retrieval

    Your tools include:
      - DuckDuckGoTools for real-time web searches
      - ExaTools for structured analysis
      - FileTools for saving lessons

    You can analyze images, audio, and video content to:
      - Explain visual concepts
      - Process diagrams and charts
      - Analyze educational content in various media formats
      - Provide detailed explanations of visual material

    Adapt your teaching style to {education_level} students, ensuring:
      - Clear, level-appropriate explanations
      - Step-by-step reasoning for complex concepts
      - Engaging visual aids and examples
      - Interactive learning elements with code when appropriate
      - Practice exercises and assessments

    <critical>
    - Use your thinking capabilities to reason through complex problems step-by-step
    - Always search both DuckDuckGo and ExaTools before answering
    - Provide sources for all data points and statistics
    - Use previous context for follow-up questions
    - Generate visual explanations when helpful
    - Include interactive elements for engagement
    - For coding topics, provide well-commented, executable code examples
    - When analyzing images, audio, or video, provide detailed and educational explanations
    </critical>"""

    # Detailed instructions for Gemini Tutor
    tutor_instructions = f"""Follow these steps to deliver an exceptional learning experience:

    1. Information Gathering
      - Analyze the query thoroughly
      - If the query involves code, math, or science, use your advanced reasoning abilities
      - If the query includes images, audio, or video, analyze the content carefully
      - Search both DuckDuckGo and ExaTools for up-to-date information
      - Gather relevant examples, visual aids, and code samples
      - Consider the student's education level ({education_level})

    2. Response Construction
      - Start with a clear, direct answer
      - For complex topics, use your thinking capabilities to break down the reasoning process
      - When analyzing multimedia content, describe what you see/hear and provide educational context
      - Break down complex concepts into manageable parts
      - Include visual explanations
      - For programming topics, provide clean, well-structured code examples
      - Provide real-world examples
      - Address common misconceptions

    3. Interactive Learning
      - Add practice questions
      - Include self-assessment exercises
      - For coding topics, create interactive coding challenges
      - Suggest further reading
      - Create visual diagrams when helpful
      - Encourage active participation

    4. Quality Assurance
      - Verify all information
      - Double-check mathematical calculations and code snippets
      - Ensure age-appropriate language
      - Check for clarity and completeness
      - Include sources and references
      - Add engaging visual elements

    5. Follow-up
      - Ask if they want to save the lesson
      - Suggest related topics
      - Encourage questions
      - Provide additional resources
      - Check understanding

    Remember to:
      - Use your reasoning capabilities to think through complex problems step-by-step
      - Leverage your multimodal understanding for comprehensive explanations
      - Generate visual aids when helpful
      - Keep explanations clear and engaging
      - Adapt to the student's level
      - Make learning interactive and fun"""

    return Agent(
        name="Gemini Tutor",
        model=model,
        user_id=user_id,
        session_id=session_id or str(uuid.uuid4()),
        storage=agent_storage,
        tools=tools,
        read_chat_history=True,
        read_tool_call_history=True,
        add_history_to_messages=True,
        num_history_responses=num_history_responses,
        add_datetime_to_instructions=True,
        add_name_to_instructions=True,
        description=tutor_description,
        instructions=tutor_instructions,
        expected_output=EXPECTED_OUTPUT_TEMPLATE,
        debug_mode=debug_mode,
        markdown=True,
    )
