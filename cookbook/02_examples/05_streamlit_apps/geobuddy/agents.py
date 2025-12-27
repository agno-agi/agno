from pathlib import Path
from typing import Optional

from agno.agent import Agent
from agno.media import Image
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.streamlit import get_model_from_id


def get_geobuddy_agent(
    model_id: str = "gemini-2.0-flash-exp",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """Get a GeoBuddy Agent for geographical image analysis.

    Args:
        model_id: Model ID to use for analysis
        user_id: Optional user ID for session tracking
        session_id: Optional session ID for conversation continuity

    Returns:
        Agent instance configured for geographical analysis
    """

    model = get_model_from_id(model_id)

    # Create the geography analysis agent
    geobuddy_agent = Agent(
        name="GeoBuddy",
        model=model,
        id="geography-location-detective",
        user_id=user_id,
        session_id=session_id,
        tools=[DuckDuckGoTools()],
        role="Geography Location Detective",
        instructions="""
            You are GeoBuddy, a geography expert who helps identify locations from photos.
            
            When analyzing images, look for these clues:
            
            • **Architecture & Buildings**: What style? What materials? Modern or historic?
            • **Signs & Text**: Street names, store signs, billboards - any readable text
            • **Landmarks**: Famous buildings, monuments, or recognizable structures  
            • **Natural Features**: Mountains, coastlines, rivers, distinctive landscapes
            • **Cultural Details**: Clothing, vehicles, license plates, local customs
            • **Environment**: Weather, vegetation, lighting that hints at climate/region
            
            For each image, provide:
            
            **Location Guess**: Be as specific as possible (street, city, country)
            **Confidence**: How sure are you? (High/Medium/Low)
            **Key Clues**: What made you think of this location?
            **Reasoning**: Walk through your thought process
            **Other Possibilities**: If unsure, what else could it be?
            
            Keep your analysis clear and conversational. Focus on what you can actually see, not speculation.
            Use search when you need to verify landmarks or get more information.
        """,
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
        debug_mode=True,
    )

    return geobuddy_agent


def analyze_image_location(agent: Agent, image_path: Path) -> Optional[str]:
    """Analyze an image to predict its geographical location.

    Args:
        agent: The GeoBuddy agent instance
        image_path: Path to the image file

    Returns:
        Analysis result or None if failed
    """
    try:
        prompt = """
        Please analyze this image and predict its geographical location. Use your comprehensive 
        visual analysis framework to identify the location based on all available clues.
        
        Provide a detailed analysis following your structured response format with location prediction,
        visual analysis, reasoning process, and alternative possibilities.
        """

        response = agent.run(prompt, images=[Image(filepath=image_path)])
        return response.content
    except Exception as e:
        raise RuntimeError(f"Error analyzing image location: {str(e)}")
