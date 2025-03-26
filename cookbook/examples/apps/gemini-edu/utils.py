"""
Utility functions for Gemini Tutor
"""

import streamlit as st
from typing import Any, Dict, List, Optional
from agno.agent.agent import Agent
from agno.utils.log import logger
from agents import tutor_agent

# Custom CSS for the app
CUSTOM_CSS = """
<style>
    .main-title {
        font-size: 3rem;
        font-weight: 700;
        color: #1a73e8;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-size: 1.2rem;
        color: #5f6368;
        margin-bottom: 2rem;
    }
    .stChat {
        background-color: #f8f9fa;
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .stChatMessage {
        background-color: white;
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 0.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .tool-call {
        background-color: #e8f0fe;
        border-radius: 0.5rem;
        padding: 0.5rem;
        margin: 0.5rem 0;
        font-family: monospace;
    }
    .stButton>button {
        background-color: #1a73e8;
        color: white;
        border: none;
        border-radius: 0.5rem;
        padding: 0.5rem 1rem;
        font-weight: 500;
    }
    .stButton>button:hover {
        background-color: #1557b0;
    }
    .stSelectbox>div>div>select {
        background-color: white;
        border: 1px solid #dadce0;
        border-radius: 0.5rem;
        padding: 0.5rem;
    }
    .stTextInput>div>div>input {
        background-color: white;
        border: 1px solid #dadce0;
        border-radius: 0.5rem;
        padding: 0.5rem;
    }
</style>
"""

def add_message(
    role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None, **kwargs
) -> None:
    """
    Safely add a message to the session state.

    Args:
        role: The role of the message sender (user/assistant)
        content: The text content of the message
        tool_calls: Optional tool calls to include
        **kwargs: Additional message attributes (image, audio, video paths)
    """
    if "messages" not in st.session_state or not isinstance(
        st.session_state["messages"], list
    ):
        st.session_state["messages"] = []

    message = {"role": role, "content": content, "tool_calls": tool_calls}

    # Add any additional attributes like image, audio, or video paths
    for key, value in kwargs.items():
        message[key] = value

    st.session_state["messages"].append(message)

def display_tool_calls(container: Any, tool_calls: List[Dict[str, Any]]) -> None:
    """Display tool calls in a formatted way."""
    if not tool_calls:
        return

    for tool_call in tool_calls:
        tool_name = tool_call.get("name", "Unknown Tool")
        tool_args = tool_call.get("arguments", {})
        container.markdown(
            f"""
            <div class="tool-call">
                <strong>Tool:</strong> {tool_name}<br>
                <strong>Arguments:</strong> {tool_args}
            </div>
            """,
            unsafe_allow_html=True,
        )

def sidebar_widget() -> None:
    """Display sidebar widgets."""
    st.sidebar.markdown("### 🎓 Learning Settings")
    st.sidebar.markdown("---")

def session_selector_widget(agent: Agent, model_id: str) -> None:
    """Display a session selector in the sidebar."""
    if agent.storage:
        agent_sessions = agent.storage.get_all_sessions()
        # Get session names if available, otherwise use IDs.
        session_options = []
        for session in agent_sessions:
            session_id = session.session_id
            session_name = (
                session.session_data.get("session_name", None)
                if session.session_data
                else None
            )
            display_name = session_name if session_name else session_id
            session_options.append({"id": session_id, "display": display_name})

        # Display session selector.
        selected_session = st.sidebar.selectbox(
            "Session",
            options=[s["display"] for s in session_options],
            key="session_selector",
        )
        # Find the selected session ID.
        selected_session_id = next(
            s["id"] for s in session_options if s["display"] == selected_session
        )

        if st.session_state.get("gemini_tutor_session_id") != selected_session_id:
            logger.info(
                f"---*--- Loading {model_id} run: {selected_session_id} ---*---"
            )
            st.session_state["gemini_tutor"] = tutor_agent(
                model_id=model_id,
                session_id=selected_session_id,
            )
            st.rerun()

def rename_session_widget(agent: Agent) -> None:
    """Display a widget to rename the current session."""
    if agent.storage:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 📝 Rename Session")
        new_name = st.sidebar.text_input(
            "New Session Name",
            key="session_rename_input",
            placeholder="Enter a name for this session",
        )
        if new_name:
            try:
                agent.storage.rename_session(
                    agent.session_id,
                    new_name,
                )
                st.sidebar.success("Session renamed successfully!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Failed to rename session: {str(e)}")

def about_widget() -> None:
    """Display an about section in the sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About Gemini Tutor")
    st.sidebar.markdown(
        """
        Gemini Tutor is an advanced educational AI assistant powered by Google's Gemini 2.5 Pro Experimental.

        Features:
        - 🧠 Advanced reasoning and thinking capabilities
        - 🔢 Expert at math, science, and coding problems
        - 📝 Step-by-step problem solving with detailed explanations
        - 🎨 Visual explanations and diagrams
        - 📊 1 million token context for comprehensive learning
        - 🔍 Real-time information retrieval
        - 📚 Personalized learning experiences
        - 💻 Advanced code generation and explanation
        - 💾 Save lessons for future reference

        Built with:
        - 🤖 Gemini 2.5 Pro Experimental (March 2025)
        - 🚀 Agno framework
        - 💫 Streamlit
        """
    )
