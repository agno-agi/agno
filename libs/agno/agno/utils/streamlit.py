import json
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict, Union

try:
    import streamlit as st
    from streamlit.delta_generator import DeltaGenerator
except ImportError:
    raise ImportError("Streamlit is not installed. Please install it with `pip install streamlit`")

from agno.agent import Agent
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.utils.log import log_debug, log_error, log_warning


class SessionMessage(TypedDict):
    """Type definition for messages stored in Streamlit session state."""

    role: str
    content: str
    tool_calls: Optional[List[ToolExecution]]


def add_message(role: str, content: str, tool_calls: Optional[List[ToolExecution]] = None) -> None:
    """Add a message to the Streamlit session state."""
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    message: SessionMessage = {
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
    }
    st.session_state["messages"].append(message)


def display_tool_calls(container: DeltaGenerator, tools: List[Union[ToolExecution, Dict[str, Any]]]) -> None:
    """Display tool calls in expandable sections."""
    if not tools:
        log_debug("No tools calls to display")
        return None

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

                    # Try to parse and display as JSON first
                    try:
                        if isinstance(result, str):
                            # Try to parse string as JSON
                            parsed_result = json.loads(result)
                        elif isinstance(result, (list, dict)):
                            # Already a JSON-like structure
                            parsed_result = result
                        else:
                            # Convert to string for non-JSON data
                            raise ValueError("Not JSON data")

                        # Display as formatted JSON
                        st.json(parsed_result)

                    except (json.JSONDecodeError, ValueError, TypeError):
                        # Fallback to text display for non-JSON content
                        log_warning(f"Failed to parse tool result: {result}")


def export_chat_history(app_name: str = "Chat") -> str:
    if "messages" not in st.session_state or not st.session_state["messages"]:
        return "# Chat History\n\n*No messages to export*"

    chat_text = f"# Agentic RAG Chat\n\n"
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


def restart_st_session(**session_keys: str) -> None:
    for key in session_keys.values():
        if key in st.session_state:
            st.session_state[key] = None
    if "messages" in st.session_state:
        st.session_state["messages"] = []
    st.rerun()


def session_selector_widget(
    agent: Agent,
    model_id: str,
    agent_name: str = "agent",
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
        log_error(f"Error fetching sessions: {e}")
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
        selected_index = session_options.index(current_selection) if current_selection in session_options else 0
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

        _is_session_changed = (
            current_session_id is None or current_session_id == "" or selected_session_id != current_session_id
        )

        if _is_session_changed:
            _load_session(selected_session_id, agent, agent_name)

    # Rename session
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
            new_name = st.sidebar.text_input("Enter new name:", value=current_name, key="session_name_input")

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
                if st.button("❌ Cancel", use_container_width=True, key="cancel_session_rename"):
                    st.session_state.session_edit_mode = False
                    st.rerun()


def _load_session(
    session_id: str,
    agent: Agent,
    agent_name: str = "agent",
):
    try:
        # Use the existing agent and switch its session
        agent.session_id = session_id
        # Reset any session-specific state
        agent.reset_session_state()

        # Update session state
        st.session_state[agent_name] = agent
        st.session_state["session_id"] = session_id
        st.session_state["messages"] = []

        try:
            # Load chat history using the standard method
            chat_history = agent.get_messages_for_session(session_id)

            if chat_history:
                for message in chat_history:
                    if message.role == "user":
                        # Check if this is a tool result message disguised as a user message
                        content_str = str(message.content).strip()
                        if content_str.startswith("[{'type': 'tool_result'") or content_str.startswith(
                            '[{"type": "tool_result"'
                        ):
                            continue

                        add_message("user", str(message.content))
                    elif message.role == "assistant":
                        # Get tool executions for this specific message
                        tool_executions = get_tool_executions_for_message(agent, message)
                        add_message("assistant", str(message.content), tool_executions)
                    elif message.role == "tool":
                        # Skip tool messages - these are internal and shouldn't be shown to users
                        continue
                    elif message.role == "system":
                        # Skip system messages - these are internal prompts
                        continue

        except Exception as e:
            log_warning(f"Could not load chat history: {e}")

        st.rerun()
    except Exception as e:
        log_error(f"Error loading session {session_id}: {e}")
        st.error(f"Error loading session: {e}")


def get_tool_executions_for_message(agent: Agent, message: Message) -> Optional[List[ToolExecution]]:
    """Get tool executions for a message from the agent's session data."""
    if not hasattr(message, "tool_calls") or not message.tool_calls:
        return None

    # Extract tool call IDs from the message
    message_tool_call_ids = set()
    for tool_call in message.tool_calls:
        if isinstance(tool_call, dict) and "id" in tool_call:
            message_tool_call_ids.add(tool_call["id"])

    if not message_tool_call_ids:
        return None

    # Find matching tool executions from agent session
    if hasattr(agent, "agent_session") and agent.agent_session and agent.agent_session.runs:
        matching_tools = []

        # Search through runs to find tool executions that match this message's tool call IDs
        for run in agent.agent_session.runs:
            if hasattr(run, "tools") and run.tools:
                for tool_exec in run.tools:
                    # Match by tool_call_id to ensure we get the right tool execution
                    if (
                        hasattr(tool_exec, "tool_call_id")
                        and tool_exec.tool_call_id
                        and tool_exec.tool_call_id in message_tool_call_ids
                    ):
                        matching_tools.append(tool_exec)

        # Return only the tools that match this specific message
        return matching_tools if matching_tools else None

    return None


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
        log_error(f"Error getting knowledge base info: {e}")
        st.sidebar.warning("Could not retrieve knowledge base information")


COMMON_CSS: str = """
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
