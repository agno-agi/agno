from typing import Any, Dict, List, Optional

import streamlit as st
from agentic_rag import get_agentic_rag_agent
from agno.agent import Agent
from agno.utils.log import logger
from agno.utils.streamlit import add_message


def session_selector_widget(agent: Agent, model_id: str) -> None:
    try:
        agent_sessions = agent.memory.db.get_sessions(
            session_type="agent",
            deserialize=True,
            sort_by="created_at",
            sort_order="desc",
        )
        logger.debug(f"Found {len(agent_sessions)} agent sessions in database")
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        st.sidebar.error("Could not load sessions from database")
        return
    
    if agent_sessions:
        logger.debug(f"Found {len(agent_sessions)} agent sessions")
        session_dict = {}
        session_options = []
        for session in agent_sessions:
            if hasattr(session, "session_id") and session.session_id:
                session_id = session.session_id
                try:
                    session_name = None
                    if hasattr(session, "session_data") and session.session_data:
                        session_name = session.session_data.get("session_name")
                    name_to_display = session_name if session_name else session_id
                    created_at = getattr(session, "created_at", None)
                    if created_at:
                        if hasattr(created_at, "strftime"):
                            time_str = created_at.strftime("%m/%d %H:%M")
                        else:
                            time_str = str(created_at)[:16]
                        display_name = f"{name_to_display} ({time_str})"
                    else:
                        display_name = name_to_display
                    session_options.append(display_name)
                    session_dict[display_name] = session_id
                except Exception as e:
                    logger.debug(f"Error formatting session {session_id}: {e}")
                    continue
        current_session_id = st.session_state.get("agentic_rag_agent_session_id")
        current_selection = None
        if current_session_id:
            for display_name, session_id in session_dict.items():
                if session_id == current_session_id:
                    current_selection = display_name
                    break
        if session_options:
            if not current_session_id:
                display_options = ["🆕 New Chat"] + session_options
                selected_index = 0
            else:
                display_options = session_options
                selected_index = (
                    session_options.index(current_selection)
                    if current_selection and current_selection in session_options
                    else 0
                )
            selected_option = st.sidebar.selectbox(
                "💬 Chat Sessions",
                options=display_options,
                index=selected_index,
                help="Select a session to continue a previous conversation or start new chat",
            )

            if selected_option == "🆕 New Chat":
                pass
            else:
                selected_session_id = session_dict.get(selected_option)
                if (
                    selected_session_id
                    and selected_session_id != current_session_id
                ):
                    logger.debug(f"Switching to session: {selected_session_id}")
                    load_session_messages(selected_session_id, model_id)
                    st.rerun()
        else:
            current_session_id = st.session_state.get(
                "agentic_rag_agent_session_id"
            )
            if not current_session_id:
                st.sidebar.info("🆕 New Chat - Start your conversation!")
            else:
                st.sidebar.info(
                    "💡 No previous sessions found. Click 'New Chat' to start."
                )

def load_session_messages(session_id: str, model_id: str) -> None:
    """Load messages for a specific session"""
    try:
        new_agent = get_agentic_rag_agent(
            model_id=model_id,
            session_id=session_id,
        )

        st.session_state["agentic_rag_agent"] = new_agent
        st.session_state["agentic_rag_agent_session_id"] = session_id

        st.session_state["messages"] = []

        try:
            chat_history = new_agent.get_messages_for_session(session_id)

            if chat_history:
                logger.debug(
                    f"Loading {len(chat_history)} messages from session history"
                )
                for message in chat_history:
                    if message.role == "user":
                        add_message("user", str(message.content))
                    elif message.role == "assistant":
                        tool_calls = (
                            getattr(message, "tool_calls", None)
                            if hasattr(message, "tool_calls")
                            else None
                        )
                        add_message("assistant", str(message.content), tool_calls)
            else:
                logger.debug("No chat history found for this session")
        except Exception as e:
            logger.warning(f"Could not load chat history: {e}")

    except Exception as e:
        logger.error(f"Error switching sessions: {str(e)}")
        st.sidebar.error(f"Error loading session: {str(e)}")


def about_widget() -> None:
    """Display an about section in the sidebar"""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.markdown("""
    This Agentic RAG Assistant helps you analyze documents and web content using natural language queries.

    Built with:
    - 🚀 Agno
    - 💫 Streamlit
    """)
