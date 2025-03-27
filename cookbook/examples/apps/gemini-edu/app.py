"""
Gemini Tutor: Advanced Educational AI Assistant with Multimodal Learning
"""

import os

import nest_asyncio
import streamlit as st
from agents import TutorAppAgent
from agno.utils.log import logger
from utils import display_grounding_metadata, display_tool_calls

# Initialize asyncio support
nest_asyncio.apply()

# Page configuration
st.set_page_config(
    page_title="Gemini Multimodal Tutor",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS with dark mode support
CUSTOM_CSS = """
<style>
    .main-title {
        font-size: 2.5rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
        color: #5186EC;
    }
    .subtitle {
        font-size: 1.2rem;
        font-weight: 400;
        margin-bottom: 2rem;
        opacity: 0.8;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Model and education options
MODEL_OPTIONS = {
    "Gemini 2.5 Pro Experimental (Recommended)": "gemini-2.5-pro-exp-03-25",
    "Gemini 2.0 Pro": "gemini-2.0-pro",
    "Gemini 1.5 Pro": "gemini-1.5-pro",
}

EDUCATION_LEVELS = [
    "Elementary School",
    "Middle School",
    "High School",
    "College",
    "Undergrad",
    "Graduate",
    "PhD",
]


def check_api_key():
    """Check if API key is set and valid."""
    if not os.environ.get("GOOGLE_API_KEY"):
        st.error("""
        **ERROR: Missing Gemini API Key**

        Please set up your Gemini API key in the .env file.

        1. Create a `.env` file in this directory if it doesn't exist
        2. Add your API key: `GOOGLE_API_KEY=your_gemini_api_key_here`
        3. Restart the application

        You can get a Gemini API key from: https://makersuite.google.com/app/apikey
        """)
        return False
    return True


def handle_streaming_response(learning_generator):
    """
    Handle a streaming response by consuming the generator.

    Args:
        learning_generator: Generator from the agent.run call

    Returns:
        Accumulated content string and grounding metadata
    """
    response_placeholder = st.empty()
    tool_calls_container = st.empty()

    # Initialize variables to accumulate content
    accumulated_content = ""
    grounding_metadata = None

    # Process the streamed response
    for chunk in learning_generator:
        # Display tool calls if available
        if hasattr(chunk, "tools") and chunk.tools and len(chunk.tools) > 0:
            display_tool_calls(tool_calls_container, chunk.tools)

        # Display response with proper markdown formatting
        if hasattr(chunk, "content") and chunk.content is not None:
            accumulated_content += chunk.content
            response_placeholder.markdown(accumulated_content)

        # Capture grounding metadata if available
        if hasattr(chunk, "grounding_metadata") and chunk.grounding_metadata:
            grounding_metadata = chunk.grounding_metadata

    # Return the accumulated content and metadata
    return accumulated_content, grounding_metadata


def main():
    """Main application entry point"""
    st.title("🔍 Gemini Tutor 📚")
    st.markdown(
        "A streamlined AI tutor that creates personalized learning experiences on any topic."
    )

    # Check for API key
    if not check_api_key():
        return

    # Setup sidebar
    st.sidebar.title("Settings")
    education_level = st.sidebar.selectbox(
        "Education Level", EDUCATION_LEVELS, index=EDUCATION_LEVELS.index("High School")
    )

    model_name = st.sidebar.selectbox("Model", list(MODEL_OPTIONS.keys()), index=0)
    model_id = MODEL_OPTIONS[model_name]

    # Initialize TutorAppAgent if needed
    if "tutor_agent" not in st.session_state:
        st.session_state.tutor_agent = TutorAppAgent(
            model_id=model_id, education_level=education_level
        )

    # Search interface
    search_topic = st.text_input(
        "What would you like to learn about?",
        placeholder="e.g., quantum physics, French Revolution, machine learning",
        key="search_box",
    )

    if st.button("Search & Create Learning Experience", key="search_button"):
        if not search_topic:
            st.warning("Please enter a search topic")
            return

        with st.spinner("Creating learning experience..."):
            try:
                # Display learning experience header
                st.markdown("## 📚 Learning Experience")

                # Offload all processing to the agent (returns a generator)
                learning_generator = (
                    st.session_state.tutor_agent.create_learning_experience(
                        search_topic=search_topic, education_level=education_level
                    )
                )

                # Handle the streaming response
                content, metadata = handle_streaming_response(learning_generator)

                # Display grounding metadata if available
                if metadata:
                    display_grounding_metadata(metadata)

            except Exception as e:
                st.error(f"Error: {str(e)}")
                logger.error(f"Application error: {str(e)}")

    # Show about information
    st.sidebar.markdown("---")
    st.sidebar.markdown("### About Gemini Tutor")
    st.sidebar.markdown(
        """
        Gemini Tutor is an AI-powered educational tool that helps you learn about any topic.

        Features:
        - Personalized learning experiences for your education level
        - Fact-checked information with live web search
        - Interactive content with examples and exercises
        """
    )


if __name__ == "__main__":
    main()
