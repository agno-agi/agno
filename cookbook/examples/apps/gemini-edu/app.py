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
    /* Target images within Streamlit's chat message content */
    /* Adjust the max-width percentage or pixel value as needed */
    [data-testid="stChatMessageContent"] img {
        max-width: 350px; /* Limit image width */
        max-height: 300px; /* Optional: Limit image height */
        display: block; /* Ensure image is block level */
        margin-top: 10px; /* Add some space above the image */
        margin-bottom: 10px; /* Add some space below the image */
        border-radius: 5px; /* Optional: rounded corners */
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
    "High School",
    "College",
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
    st.markdown('<p class="subtitle">Your AI-powered guide for exploring any topic</p>', unsafe_allow_html=True)

    # Check for API key
    if not check_api_key():
        st.stop()

    # Initialize agent in session state if not already present
    if "tutor_agent" not in st.session_state:
        st.session_state.tutor_agent = None
        st.session_state.model_id = MODEL_OPTIONS["Gemini 2.5 Pro Experimental (Recommended)"]
        st.session_state.education_level = "High School"
        st.session_state.messages = [] # Initialize chat history
        st.session_state.processing = False # Flag to track if we're currently processing a request

    # Sidebar for configuration
    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Gemini_logo.svg/1200px-Google_Gemini_logo.svg.png", width=100)
        st.header("Configuration")

        selected_model_name = st.selectbox(
            "Select Gemini Model",
            options=list(MODEL_OPTIONS.keys()),
            index=0, # Default to recommended
            key="selected_model_name",
        )
        st.session_state.model_id = MODEL_OPTIONS[selected_model_name]

        st.session_state.education_level = st.selectbox(
            "Select Education Level",
            options=EDUCATION_LEVELS,
            index=EDUCATION_LEVELS.index(st.session_state.education_level), # Maintain selected level
            key="education_level_selector",
        )

        if st.button("Apply & Reset", key="apply_reset"):
            # Re-initialize the agent with new settings and clear history
            try:
                st.session_state.tutor_agent = TutorAppAgent(
                    model_id=st.session_state.model_id,
                    education_level=st.session_state.education_level,
                )
                st.session_state.messages = [] # Clear history on reset
                st.success("Settings applied. Agent reset.")
                st.rerun() # Rerun to reflect changes immediately
            except Exception as e:
                st.error(f"Failed to initialize agent: {e}")
                st.session_state.tutor_agent = None

    # Ensure agent is initialized if not already
    if st.session_state.tutor_agent is None:
        try:
            st.session_state.tutor_agent = TutorAppAgent(
                model_id=st.session_state.model_id,
                education_level=st.session_state.education_level,
            )
        except Exception as e:
            st.error(f"Failed to initialize agent: {e}")
            st.stop()

    # Display chat history FIRST, before the form
    st.markdown("### Learning Session")

    # Display previous messages
    for message in st.session_state.messages:
        # Skip empty messages if any occurred
        if not message.get("content"):
            continue
        with st.chat_message(message["role"]):
            # Display content
            st.markdown(message["content"])

            # If assistant message, display tools and citations *within the same bubble*
            if message["role"] == "assistant":
                if message.get("tools"):
                    # Display tools here, potentially collapsed
                     with st.expander("🛠️ Tool Calls", expanded=False):
                         display_tool_calls(message["tools"]) # Pass tools from message

                if message.get("citations"):
                    # Display citations here
                    display_grounding_metadata(message["citations"]) # Pass Citations object

    # Use st.form to handle Enter key submission
    with st.form(key="topic_form"):
        search_topic = st.text_input(
            "What would you like to learn about?",
            key="search_topic_input",
            placeholder="e.g., Quantum Physics, History of Rome, Python programming"
        )
        submitted = st.form_submit_button("Start Learning", type="primary")

        if submitted and search_topic and not st.session_state.processing:
            # Set processing flag to prevent duplicate execution
            st.session_state.processing = True

            # Add user message to history
            user_message = {"role": "user", "content": f"Teach me about: {search_topic}"}
            st.session_state.messages.append(user_message)

            # Rerun to display message before starting the processing
            st.rerun()

    # Process the query outside the form - this runs after the rerun
    # if processing flag is set and there's a user message
    if st.session_state.processing and st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        try:
            # Extract the search topic from the last user message
            search_topic = st.session_state.messages[-1]["content"].replace("Teach me about: ", "")

            # Create a placeholder for the thinking indicator (outside chat bubbles)
            thinking_placeholder = st.empty()
            thinking_placeholder.info("🧠 Thinking...")

            # Stream response
            response_stream = st.session_state.tutor_agent.create_learning_experience(
                search_topic=search_topic,
                education_level=st.session_state.education_level
            )

            # Stream and accumulate the response content and metadata
            full_response = ""
            stream_error = None
            final_tools = None
            final_citations = None

            for chunk in response_stream:
                # Check for content
                if hasattr(chunk, "content") and chunk.content:
                    full_response += chunk.content
                    # Don't update the placeholder here - let history display handle it

                # Accumulate tools
                if hasattr(chunk, "tools") and chunk.tools:
                    final_tools = chunk.tools

                # Accumulate citations
                if hasattr(chunk, "citations") and chunk.citations:
                    final_citations = chunk.citations

            # Clear thinking indicator
            thinking_placeholder.empty()

            # Prepare the assistant message dictionary with content, tools, and citations
            assistant_message = {"role": "assistant"}
            if stream_error:
                logger.error(f"Stream ended with error: {stream_error}")
                assistant_message["content"] = f"An error occurred: {stream_error}"
            elif full_response:
                assistant_message["content"] = full_response
                if final_tools:
                    assistant_message["tools"] = final_tools
                if final_citations:
                    assistant_message["citations"] = final_citations
            else:
                logger.warning("Stream finished with no content.")
                assistant_message["content"] = "[No content received]"

            # Add the complete assistant message to history
            st.session_state.messages.append(assistant_message)

        except Exception as e:
            # Log error but only show it once
            logger.error(f"Error during agent run: {e}", exc_info=True)

            # Add error message to history
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"An error occurred: {e}"
            })

        # Reset processing flag
        st.session_state.processing = False

        # Rerun to display the results and reset the form
        st.rerun()


if __name__ == "__main__":
    main()
