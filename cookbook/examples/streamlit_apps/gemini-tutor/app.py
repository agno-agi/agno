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

# --- Constants ---
MODEL_OPTIONS = {
    "Gemini 2.5 Pro Experimental (Recommended)": "gemini-2.5-pro-exp-03-25",
    "Gemini 2.0 Pro": "gemini-2.0-pro",
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


def initialize_session_state():
    """Initialize Streamlit session state variables if they don't exist."""
    if "tutor_agent" not in st.session_state:
        st.session_state.tutor_agent = None
    if "model_id" not in st.session_state:
        st.session_state.model_id = MODEL_OPTIONS[
            "Gemini 2.5 Pro Experimental (Recommended)"
        ]
    if "education_level" not in st.session_state:
        st.session_state.education_level = "High School"
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "processing" not in st.session_state:
        st.session_state.processing = False
    if "agent_needs_reset" not in st.session_state:
        st.session_state.agent_needs_reset = True  # Start needing initialization


def render_sidebar():
    """Render the sidebar for configuration and reset."""
    with st.sidebar:
        st.header("Configuration")

        # Store previous values to detect changes
        prev_model_id = st.session_state.model_id
        prev_education_level = st.session_state.education_level

        selected_model_name = st.selectbox(
            "Select Gemini Model",
            options=list(MODEL_OPTIONS.keys()),
            index=list(MODEL_OPTIONS.values()).index(
                st.session_state.model_id
            ),  # Maintain selection
            key="selected_model_name",
        )
        st.session_state.model_id = MODEL_OPTIONS[selected_model_name]

        st.session_state.education_level = st.selectbox(
            "Select Education Level",
            options=EDUCATION_LEVELS,
            index=EDUCATION_LEVELS.index(
                st.session_state.education_level
            ),  # Maintain selection
            key="education_level_selector",
        )

        # Check if settings changed
        if (
            st.session_state.model_id != prev_model_id
            or st.session_state.education_level != prev_education_level
        ):
            st.session_state.agent_needs_reset = True
            st.info(
                "Settings changed. Agent will be updated on next interaction or reset."
            )

        if st.button("New chat", key="apply_reset"):
            st.session_state.agent_needs_reset = True
            st.session_state.messages = []  # Clear history on reset
            st.toast("Settings applied. Agent updated and chat reset.")


def initialize_or_update_agent():
    """Initialize or update the agent if settings have changed."""
    if st.session_state.agent_needs_reset or st.session_state.tutor_agent is None:
        logger.info(
            f"Initializing/Updating Tutor Agent: Model={st.session_state.model_id}, Level={st.session_state.education_level}"
        )
        try:
            st.session_state.tutor_agent = TutorAppAgent(
                model_id=st.session_state.model_id,
                education_level=st.session_state.education_level,
            )
            st.session_state.agent_needs_reset = False
        except Exception as e:
            st.error(f"Failed to initialize agent: {e}")
            st.session_state.tutor_agent = None
            st.stop()


def render_chat_history():
    """Display the chat messages stored in session state."""
    st.markdown("### Learning Session")
    for message in st.session_state.messages:
        # Skip empty messages if any occurred (e.g., during stream error)
        if (
            not message.get("content")
            and not message.get("tools")
            and not message.get("citations")
        ):
            continue
        with st.chat_message(message["role"]):
            # Display content if it exists
            if message.get("content"):
                st.markdown(message["content"])

            # If assistant message, display tools and citations *within the same bubble*
            if message["role"] == "assistant":
                if message.get("tools"):
                    with st.expander("🛠️ Tool Calls", expanded=False):
                        display_tool_calls(message["tools"])
                if message.get("citations"):
                    display_grounding_metadata(message["citations"])


def handle_user_input():
    """Render the chat input form and handle submission."""
    with st.form(key="topic_form"):
        search_topic = st.text_input(
            "What would you like to learn about?",
            key="search_topic_input",
            placeholder="e.g., Quantum Physics, History of Rome, Python programming",
        )
        submitted = st.form_submit_button("Start Learning", type="primary")

        if submitted and search_topic and not st.session_state.processing:
            st.session_state.processing = True
            user_message = {
                "role": "user",
                "content": f"Teach me about: {search_topic}",
            }
            st.session_state.messages.append(user_message)
            st.rerun()  # Rerun to display user message immediately


def process_agent_response():
    """Process the agent response if the last message was from the user."""
    if (
        st.session_state.processing
        and st.session_state.messages
        and st.session_state.messages[-1]["role"] == "user"
    ):
        if st.session_state.tutor_agent is None:
            st.error("Agent is not initialized. Cannot process request.")
            st.session_state.processing = False
            return

        try:
            search_topic = st.session_state.messages[-1]["content"].replace(
                "Teach me about: ", ""
            )

            with st.spinner("🤔 Thinking..."):
                response_stream = (
                    st.session_state.tutor_agent.create_learning_experience(
                        search_topic=search_topic,
                        education_level=st.session_state.education_level,
                    )
                )

                st.session_state.current_tools = None
                st.session_state.current_citations = None

                def stream_handler(stream_generator):
                    logger.info("Starting stream processing...")
                    full_content = ""
                    for chunk in stream_generator:
                        content_delta = getattr(chunk, "content", None)
                        if content_delta:
                            full_content += content_delta
                            yield content_delta
                        tools = getattr(chunk, "tools", None)
                        if tools:
                            st.session_state.current_tools = tools
                        citations = getattr(chunk, "citations", None)
                        if citations:
                            st.session_state.current_citations = citations
                    logger.info("Finished stream processing.")
                    st.session_state.full_content_from_stream = full_content

                with st.chat_message("assistant"):
                    st.write_stream(stream_handler(response_stream))

                assistant_message = {"role": "assistant"}
                full_content = st.session_state.pop(
                    "full_content_from_stream", "[No content received]"
                )
                assistant_message["content"] = (
                    full_content if full_content else "[No content received]"
                )
                if not full_content:
                    logger.warning("Stream finished with no content.")

                # --- Post-processing to remove duplicate grounding sources ---
                grounding_marker = "\n🌐 Sources"
                if grounding_marker in full_content:
                    logger.info("Removing duplicate grounding sources section.")
                    full_content = full_content.split(grounding_marker)[0].rstrip()
                # -------------------------------------------------------------

                final_tools = st.session_state.pop("current_tools", None)
                final_citations = st.session_state.pop("current_citations", None)
                if final_tools:
                    assistant_message["tools"] = final_tools
                if final_citations:
                    assistant_message["citations"] = final_citations

                st.session_state.final_assistant_message = assistant_message

            if "final_assistant_message" in st.session_state:
                st.session_state.messages.append(
                    st.session_state.pop("final_assistant_message")
                )

        except Exception as e:
            logger.error(f"Error during agent run: {e}", exc_info=True)
            st.session_state.messages.append(
                {"role": "assistant", "content": f"An error occurred: {e}"}
            )
        finally:
            st.session_state.processing = False
            st.rerun()


# Custom CSS
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
    [data-testid="stChatMessageContent"] img {
        max-width: 350px;
        max-height: 300px;
        display: block;
        margin-top: 10px;
        margin-bottom: 10px;
        border-radius: 5px;
    }
</style>
"""


st.title("🔍 Gemini Tutor 📚")
st.markdown(
    '<p class="subtitle">Your AI-powered guide for exploring any topic</p>',
    unsafe_allow_html=True,
)
initialize_session_state()
render_sidebar()
initialize_or_update_agent()
render_chat_history()
handle_user_input()
process_agent_response()
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
