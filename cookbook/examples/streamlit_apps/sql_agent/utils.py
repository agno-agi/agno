import json
from dataclasses import asdict
from typing import Any, Dict, List, Optional

import streamlit as st
from agents import get_sql_agent
from agno.agent.agent import Agent
from agno.utils.log import logger


def is_json(myjson):
    """Check if a string is valid JSON"""
    try:
        json.loads(myjson)
    except (ValueError, TypeError):
        return False
    return True


def load_data_and_knowledge():
    """Load F1 data and knowledge base if not already done"""
    from load_f1_data import load_f1_data
    from load_knowledge import load_knowledge

    if "data_loaded" not in st.session_state:
        with st.spinner("🔄 Loading data into database..."):
            load_f1_data()
        with st.spinner("📚 Loading knowledge base..."):
            load_knowledge()
        st.session_state["data_loaded"] = True
        st.success("✅ Data and knowledge loaded successfully!")


def add_message(
    role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None
) -> None:
    """Safely add a message to the session state"""
    if "messages" not in st.session_state or not isinstance(
        st.session_state["messages"], list
    ):
        st.session_state["messages"] = []
    st.session_state["messages"].append(
        {"role": role, "content": content, "tool_calls": tool_calls}
    )


def restart_agent():
    """Reset the agent and clear chat history"""
    logger.debug("---*--- Restarting agent ---*---")
    st.session_state["sql_agent"] = None
    st.session_state["sql_agent_session_id"] = None
    st.session_state["messages"] = []
    st.rerun()


def export_chat_history():
    """Export chat history as markdown"""
    if "messages" in st.session_state:
        chat_text = "# Reasoning SQL Agent - Chat History\n\n"
        for msg in st.session_state["messages"]:
            role = "🤖 Assistant" if msg["role"] == "agent" else "👤 User"
            chat_text += f"### {role}\n{msg['content']}\n\n"
        return chat_text
    return ""


def display_tool_calls(tool_calls_container, tools):
    """Display tool calls in a streamlit container with expandable sections.

    Args:
        tool_calls_container: Streamlit container to display the tool calls
        tools: List of tool call dictionaries containing name, args, content, and metrics
    """
    try:
        with tool_calls_container.container():
            for tool_call in tools:
                tool_name = tool_call.get("tool_name", "Unknown Tool")
                tool_args = tool_call.get("tool_args", {})
                content = tool_call.get("content", None)
                metrics = tool_call.get("metrics", None)

                # Add timing information
                execution_time_str = "N/A"
                try:
                    if metrics is not None and hasattr(metrics, "time"):
                        execution_time = metrics.time
                        if execution_time is not None:
                            execution_time_str = f"{execution_time:.4f}s"
                except Exception as e:
                    logger.error(f"Error displaying tool calls: {str(e)}")
                    pass

                with st.expander(
                    f"🛠️ {tool_name.replace('_', ' ').title()} ({execution_time_str})",
                    expanded=False,
                ):
                    # Show query with syntax highlighting
                    if isinstance(tool_args, dict) and "query" in tool_args:
                        st.code(tool_args["query"], language="sql")

                    # Display arguments in a more readable format
                    if tool_args and tool_args != {"query": None}:
                        st.markdown("**Arguments:**")
                        st.json(tool_args)

                    if content is not None:
                        try:
                            if is_json(content):
                                st.markdown("**Results:**")
                                st.json(content)
                        except Exception as e:
                            logger.debug(f"Skipped tool call content: {e}")
    except Exception as e:
        logger.error(f"Error displaying tool calls: {str(e)}")
        tool_calls_container.error("Failed to display tool results")


def sidebar_widget() -> None:
    """Display a sidebar with sample user queries"""
    with st.sidebar:
        st.markdown("#### 🏆 Sample Queries")
        if st.button("📋 Show Tables"):
            add_message("user", "Which tables do you have access to?")
        if st.button("🥇 Most Race Wins"):
            add_message("user", "Which driver has the most race wins?")

        if st.button("🏆 Constructor Champs"):
            add_message("user", "Which team won the most Constructors Championships?")

        if st.button("⏳ Longest Career"):
            add_message(
                "user",
                "Tell me the name of the driver with the longest racing career? Also tell me when they started and when they retired.",
            )
        if st.button("📈 Races per Year"):
            add_message("user", "Show me the number of races per year.")

        if st.button("🔍 Team Performance"):
            add_message(
                "user",
                "Write a query to identify the drivers that won the most races per year from 2010 onwards and the position of their team that year.",
            )

        st.markdown("---")
        st.markdown("#### 🛠️ Utilities")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 New Chat"):
                restart_agent()
        with col2:
            fn = "sql_agent_chat_history.md"
            if "sql_agent_session_id" in st.session_state:
                fn = f"sql_agent_{st.session_state.sql_agent_session_id}.md"
            if st.download_button(
                "💾 Export Chat",
                export_chat_history(),
                file_name=fn,
                mime="text/markdown",
            ):
                st.sidebar.success("Chat history exported!")

        if st.sidebar.button("🚀 Load Data & Knowledge"):
            load_data_and_knowledge()


def session_selector_widget(agent: Agent, model_id: str) -> None:
    """Display a session selector in the sidebar"""
    if agent.storage:
        agent_sessions = agent.storage.get_all_sessions()
        # Get session names if available, otherwise use IDs
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

        # Display session selector
        selected_session = st.sidebar.selectbox(
            "Session",
            options=[s["display"] for s in session_options],
            key="session_selector",
        )
        # Find the selected session ID
        selected_session_id = next(
            s["id"] for s in session_options if s["display"] == selected_session
        )

        if st.session_state["sql_agent_session_id"] != selected_session_id:
            logger.info(
                f"---*--- Loading {model_id} run: {selected_session_id} ---*---"
            )
            st.session_state["sql_agent"] = get_sql_agent(
                model_id=model_id,
                session_id=selected_session_id,
            )
            st.rerun()


def rename_session_widget(agent: Agent) -> None:
    """Rename the current session of the agent and save to storage"""
    container = st.sidebar.container()
    session_row = container.columns([3, 1], vertical_alignment="center")

    # Initialize session_edit_mode if needed
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
    """Display an about section in the sidebar"""
    with st.sidebar:
        st.markdown("### About Agno ✨")
        st.markdown("""
        Agno is a lightweight library for building Reasoning Agents.

        [GitHub](https://github.com/agno-agi/agno) | [Docs](https://docs.agno.com)
        """)

        st.markdown("### Need Help?")
        st.markdown(
            "If you have any questions, catch us on [discord](https://agno.link/discord) or post in the community [forum](https://agno.link/community)."
        )


CUSTOM_CSS = """
    <style>
    /* Main Styles */
    .main-title {
        text-align: center;
        background: linear-gradient(45deg, #FF4B2B, #FF416C);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3em;
        font-weight: bold;
        padding: 1em 0;
    }
    .subtitle {
        text-align: center;
        color: #666;
        margin-bottom: 2em;
    }
    .stButton button {
        width: 100%;
        border-radius: 20px;
        margin: 0.2em 0;
        transition: all 0.3s ease;
    }
    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 15px rgba(0,0,0,0.1);
    }
    .chat-container {
        border-radius: 15px;
        padding: 1em;
        margin: 1em 0;
        background-color: #f5f5f5;
    }
    .sql-result {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 1em;
        margin: 1em 0;
        border-left: 4px solid #FF4B2B;
    }
    .status-message {
        padding: 1em;
        border-radius: 10px;
        margin: 1em 0;
    }
    .success-message {
        background-color: #d4edda;
        color: #155724;
    }
    .error-message {
        background-color: #f8d7da;
        color: #721c24;
    }
    /* Dark mode adjustments */
    @media (prefers-color-scheme: dark) {
        .chat-container {
            background-color: #2b2b2b;
        }
        .sql-result {
            background-color: #1e1e1e;
        }
    }
    </style>
"""
