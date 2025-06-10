import streamlit as st
from agents import image_processing_agent
from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.utils.log import logger


def add_message(role: str, content: str) -> None:
    """Safely add a message to the session state."""
    if "messages" not in st.session_state or not isinstance(
        st.session_state["messages"], list
    ):
        st.session_state["messages"] = []
    st.session_state["messages"].append({"role": role, "content": content})


def restart_agent():
    """Reset the agent and clear chat history."""
    logger.debug("---*--- Restarting Image Agent ---*---")
    st.session_state["image_agent"] = None
    st.session_state["image_agent_session_id"] = None
    st.session_state["messages"] = []
    st.rerun()


def clear_chat():
    """Clear chat history and reset relevant session state variables
    while preserving model settings"""

    # Clear chat and extraction data
    st.session_state["messages"] = []
    st.session_state["last_image_response"] = None
    st.session_state["last_extracted_image"] = None
    st.session_state["extract_triggered"] = False

    # Remove agents so they'll be reinitialized
    if "image_agent" in st.session_state:
        del st.session_state["image_agent"]
    if "chat_agent" in st.session_state:
        del st.session_state["chat_agent"]

    st.rerun()


def export_chat_history():
    """Export chat history as markdown."""
    if "messages" in st.session_state:
        chat_text = "# VisioAI - Chat History\n\n"
        for msg in st.session_state["messages"]:
            role = "🤖 Assistant" if msg["role"] == "assistant" else "👤 User"
            chat_text += f"### {role}\n{msg['content']}\n\n"
        return chat_text
    return ""


def session_selector_widget(agent: Agent) -> None:
    """Display a session selector in the sidebar and reinitialize the agent if needed."""

    if agent.storage:
        agent_sessions = agent.storage.get_all_sessions()
        session_options = [
            {
                "id": session.session_id,
                "display": session.session_data.get("session_name", session.session_id),
            }
            for session in agent_sessions
        ]

        # Ensure we have sessions before showing the selector
        if not session_options:
            st.sidebar.warning("⚠️ No previous sessions found. Starting a new session.")
            return

        selected_session = st.sidebar.selectbox(
            "Session",
            options=[s["display"] for s in session_options],
            key="session_selector",
        )

        # Safely find the selected session ID
        selected_session_id = next(
            (s["id"] for s in session_options if s["display"] == selected_session),
            None,  # Default to None if not found
        )

        if not selected_session_id:
            st.sidebar.warning(
                "⚠️ Selected session not found. Please restart or choose another session."
            )
            return

        if st.session_state.get("image_agent_session_id") != selected_session_id:
            logger.info(f"---*--- Loading session: {selected_session_id} ---*---")

            # Retrieve Model Choice & API Key
            model_choice = st.session_state.get("model_choice")
            api_key = st.session_state.get("api_key")

            if model_choice == "OpenAI":
                model = OpenAIChat(id="gpt-4o", api_key=api_key)
            else:
                model = Gemini(id="gemini-2.0-flash", api_key=api_key)

            # Reload the agent with the selected session
            st.session_state["image_agent"] = image_processing_agent(model=model)
            st.session_state["image_agent"].load_session(selected_session_id)
            st.session_state["image_agent_session_id"] = selected_session_id
            st.rerun()


def rename_session_widget(agent: Agent) -> None:
    """Rename the current session of the agent and save to storage."""

    container = st.sidebar.container()
    session_row = container.columns([3, 1], vertical_alignment="center")

    if "session_edit_mode" not in st.session_state:
        st.session_state.session_edit_mode = False

    with session_row[0]:
        if st.session_state.session_edit_mode:
            new_session_name = st.text_input(
                "Session Name",
                value=agent.session_name,
                key="session_name_input",
                label_visibility="collapsed",
            )
        else:
            st.markdown(f"Session Name: **{agent.session_name}**")

    with session_row[1]:
        if st.session_state.session_edit_mode:
            if st.button("✓", key="save_session_name", type="primary"):
                if new_session_name:
                    agent.rename_session(new_session_name)
                    st.session_state.session_edit_mode = False
                    container.success("Renamed!")
        else:
            if st.button("✎", key="edit_session_name"):
                st.session_state.session_edit_mode = True


def about_widget() -> None:
    """Display an about section in the sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.markdown("""
    VisioAI helps you analyze images and extract insights using AI-powered object detection,
    OCR, and scene recognition.

    Built with:
    - 🚀 Agno
    - 💫 Streamlit
    """)
