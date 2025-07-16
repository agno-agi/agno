from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.utils.log import logger


def add_message(
    role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None
) -> None:
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    message = {"role": role, "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls

    st.session_state["messages"].append(message)


def display_tool_calls(container, tools: List[Any]):
    """Display tool calls in expandable sections."""
    if not tools:
        return

    with container.container():
        for tool in tools:
            if hasattr(tool, "tool_name"):
                name = tool.tool_name or "Tool"
                args = tool.tool_args or {}
                result = tool.result or ""
            else:
                name = tool.get("tool_name") or tool.get("name") or "Tool"
                args = tool.get("tool_args") or tool.get("args") or {}
                result = tool.get("result") or tool.get("content") or ""

            with st.expander(f"🛠️ {name.replace('_', ' ')}", expanded=False):
                if args:
                    st.markdown("**Arguments:**")
                    st.json(args)
                if result:
                    st.markdown("**Result:**")
                    st.json(result)


def export_chat_history(app_name: str = "Chat") -> str:
    if "messages" not in st.session_state or not st.session_state["messages"]:
        return "# Chat History\n\n*No messages to export*"

    title = "Chat History"
    for msg in st.session_state["messages"]:
        if msg.get("role") == "user" and msg.get("content"):
            title = msg["content"][:100]
            if len(msg["content"]) > 100:
                title += "..."
            break

    chat_text = f"# {title}\n\n"
    chat_text += f"**Exported:** {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n\n"
    chat_text += "---\n\n"

    for msg in st.session_state["messages"]:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if not content or str(content).strip().lower() == "none":
            continue

        role_display = "## 🙋 User" if role == "user" else "## 🤖 Assistant"
        chat_text += f"{role_display}\n\n{content}\n\n---\n\n"
    return chat_text


def restart_agent_session(**session_keys) -> None:
    for key in session_keys.values():
        if key in st.session_state:
            st.session_state[key] = None
    if "messages" in st.session_state:
        st.session_state["messages"] = []
    st.rerun()


def session_selector_widget(
    agent: Agent, model_id: str, agent_creation_callback: callable
) -> None:
    if not agent.memory or not agent.memory.db:
        st.sidebar.info("💡 Memory not configured. Sessions will not be saved.")
        return

    try:
        sessions = agent.memory.db.get_sessions(
            session_type="agent",
            deserialize=True,
            sort_by="created_at",
            sort_order="desc",
        )
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        st.sidebar.error("Could not load sessions")
        return

    if not sessions:
        st.sidebar.info("🆕 New Chat - Start your conversation!")
        return

    session_options = []
    session_dict = {}

    for session in sessions:
        if not hasattr(session, "session_id") or not session.session_id:
            continue

        session_id = session.session_id
        session_name = None

        if hasattr(session, "session_data") and session.session_data:
            session_name = session.session_data.get("session_name")

        name = session_name or session_id

        if hasattr(session, "created_at") and session.created_at:
            try:
                if hasattr(session.created_at, "strftime"):
                    time_str = session.created_at.strftime("%m/%d %H:%M")
                    display_name = f"{name} ({time_str})"
                else:
                    display_name = name
            except (ValueError, TypeError, OSError):
                display_name = name
        else:
            display_name = name

        session_options.append(display_name)
        session_dict[display_name] = session_id

    current_session_id = st.session_state.get("session_id")
    current_selection = None

    for display_name, session_id in session_dict.items():
        if session_id == current_session_id:
            current_selection = display_name
            break

    if current_session_id:
        display_options = session_options
        selected_index = (
            session_options.index(current_selection)
            if current_selection in session_options
            else 0
        )
    else:
        display_options = ["🆕 New Chat"] + session_options
        selected_index = 0

    selected = st.sidebar.selectbox(
        label="Session Name",
        options=display_options,
        index=selected_index,
        help="Select a session to continue or start new chat",
    )

    if selected != "🆕 New Chat" and selected in session_dict:
        selected_session_id = session_dict[selected]
        if selected_session_id != current_session_id:
            _load_session(selected_session_id, model_id, agent_creation_callback)

    if agent.session_id:
        if "session_edit_mode" not in st.session_state:
            st.session_state.session_edit_mode = False

        current_name = agent.session_name or agent.session_id

        if not st.session_state.session_edit_mode:
            col1, col2 = st.sidebar.columns([3, 1])
            with col1:
                st.write(f"**Session Name:** {current_name}")
            with col2:
                if st.button("✎", help="Rename session", key="rename_session_button"):
                    st.session_state.session_edit_mode = True
                    st.rerun()
        else:
            new_name = st.sidebar.text_input(
                "Enter new name:", value=current_name, key="session_name_input"
            )

            col1, col2 = st.sidebar.columns([1, 1])
            with col1:
                if st.button(
                    "💾 Save",
                    type="primary",
                    use_container_width=True,
                    key="save_session_name",
                ):
                    if new_name and new_name.strip():
                        try:
                            agent.rename_session(new_name.strip())
                            st.session_state.session_edit_mode = False
                            st.sidebar.success("Session renamed!")
                            st.rerun()
                        except Exception as e:
                            st.sidebar.error(f"Error: {str(e)}")
                    else:
                        st.sidebar.error("Please enter a valid name")

            with col2:
                if st.button(
                    "❌ Cancel", use_container_width=True, key="cancel_session_rename"
                ):
                    st.session_state.session_edit_mode = False
                    st.rerun()


def _load_session(session_id: str, model_id: str, agent_creation_callback: callable):
    try:
        new_agent = agent_creation_callback(model_id=model_id, session_id=session_id)
        st.session_state["agent"] = new_agent
        st.session_state["session_id"] = session_id
        st.session_state["messages"] = []

        try:
            # Load chat history - let the agent handle the session format
            chat_history = new_agent.get_messages_for_session(session_id)
            if chat_history:
                for message in chat_history:
                    if message.role == "user":
                        add_message("user", str(message.content))
                    elif message.role == "assistant":
                        # For stored sessions, get tool executions from agent session
                        tool_executions = get_tool_executions_for_message(
                            new_agent, message
                        )
                        add_message("assistant", str(message.content), tool_executions)
        except Exception as e:
            logger.warning(f"Could not load chat history: {e}")

        st.rerun()
    except Exception as e:
        logger.error(f"Error loading session: {e}")
        st.sidebar.error(f"Error loading session: {str(e)}")


def get_tool_executions_for_message(agent: Agent, message) -> Optional[List[Any]]:
    """Get tool executions for a message from the agent's session data."""
    if not hasattr(message, "tool_calls") or not message.tool_calls:
        return None

    # For stored sessions, find matching tool executions from runs
    if (
        hasattr(agent, "agent_session")
        and agent.agent_session
        and agent.agent_session.runs
    ):
        # Find tools from runs that match this message's tool calls
        for run in agent.agent_session.runs:
            if hasattr(run, "tools") and run.tools:
                # Check if any tool in this run matches the message's tool calls
                for tool_exec in run.tools:
                    if hasattr(tool_exec, "tool_name") and tool_exec.tool_name:
                        # Check if this tool matches any tool call in the message
                        for tool_call in message.tool_calls:
                            if (
                                isinstance(tool_call, dict)
                                and "function" in tool_call
                                and tool_call["function"].get("name")
                                == tool_exec.tool_name
                            ):
                                # Found matching tools for this message
                                return run.tools

    return None


def get_model_from_id(model_id: str):
    if model_id.startswith("openai:"):
        return OpenAIChat(id=model_id.split("openai:")[1])
    elif model_id.startswith("anthropic:"):
        return Claude(id=model_id.split("anthropic:")[1])
    elif model_id.startswith("google:"):
        return Gemini(id=model_id.split("google:")[1])
    elif model_id.startswith("groq:"):
        return Groq(id=model_id.split("groq:")[1])
    else:
        return OpenAIChat(id="gpt-4o")


def knowledge_base_info_widget(agent: Agent) -> None:
    """Display knowledge base information widget."""
    if not agent.knowledge:
        st.sidebar.info("No knowledge base configured")
        return

    vector_store = getattr(agent.knowledge, "vector_store", None)
    if not vector_store:
        st.sidebar.info("No vector store configured")
        return

    try:
        doc_count = vector_store.get_count()
        if doc_count == 0:
            st.sidebar.info("💡 Upload documents to populate the knowledge base")
        else:
            st.sidebar.metric("Documents Loaded", doc_count)
    except Exception as e:
        logger.error(f"Error getting knowledge base info: {e}")
        st.sidebar.warning("Could not retrieve knowledge base information")


COMMON_CSS = """
    <style>
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
    </style>
"""
