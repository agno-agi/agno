"""
Simple streamlit utilities for Agno applications.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.utils.log import logger


def add_message(role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None) -> None:
    """Add a message to session state."""
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
            # Handle both ToolExecution objects and dicts
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
                    if isinstance(result, (dict, list)):
                        st.json(result)
                    else:
                        st.markdown(result)


def export_chat_history(app_name: str = "Chat") -> str:
    """Export chat history as markdown."""
    if "messages" not in st.session_state or not st.session_state["messages"]:
        return "# Chat History\n\n*No messages to export*"

    # Get first user message as title
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
    """Clear session state keys and restart."""
    for key in session_keys.values():
        if key in st.session_state:
            st.session_state[key] = None
    if "messages" in st.session_state:
        st.session_state["messages"] = []
    st.rerun()


def knowledge_base_info_widget(agent: Agent) -> None:
    """Display knowledge base info."""
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


def session_selector_widget(agent: Agent, model_id: str, agent_creation_callback: callable) -> None:
    """Simple session selector widget with integrated rename functionality."""
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

    # Build session options
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
        
        # Handle timestamp - could be datetime object or integer timestamp
        if hasattr(session, "created_at") and session.created_at:
            try:
                if hasattr(session.created_at, "strftime"):
                    # It's already a datetime object
                    time_str = session.created_at.strftime("%m/%d %H:%M")
                else:
                    # It's an integer timestamp - convert to datetime
                    dt = datetime.fromtimestamp(session.created_at)
                    time_str = dt.strftime("%m/%d %H:%M")
                display_name = f"{name} ({time_str})"
            except (ValueError, TypeError, OSError) as e:
                logger.debug(f"Error formatting timestamp for session {session_id}: {e}")
                display_name = name
        else:
            display_name = name
            
        session_options.append(display_name)
        session_dict[display_name] = session_id

    # Current session handling
    current_session_id = st.session_state.get("session_id")
    current_selection = None
    
    for display_name, session_id in session_dict.items():
        if session_id == current_session_id:
            current_selection = display_name
            break

    # Session selector
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
        help="Select a session to continue or start new chat"
    )

    # Handle selection
    if selected != "🆕 New Chat" and selected in session_dict:
        selected_session_id = session_dict[selected]
        if selected_session_id != current_session_id:
            _load_session(selected_session_id, model_id, agent_creation_callback)

    # Session rename functionality - only show if there's an active session
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
                if st.button("💾 Save", type="primary", use_container_width=True, key="save_session_name"):
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


def _load_session(session_id: str, model_id: str, agent_creation_callback: callable):
    """Load a specific session."""
    try:
        new_agent = agent_creation_callback(model_id=model_id, session_id=session_id)
        st.session_state["agent"] = new_agent
        st.session_state["session_id"] = session_id
        st.session_state["messages"] = []

        # Load chat history
        try:
            chat_history = new_agent.get_messages_for_session(session_id)
            if chat_history:
                logger.debug(f"Loading {len(chat_history)} messages from session")
                for message in chat_history:
                    if message.role == "user":
                        add_message("user", str(message.content))
                    elif message.role == "assistant":
                        # Check multiple possible sources for tool calls
                        tool_calls = None
                        
                        # Try to get tool calls from various sources
                        if hasattr(message, "tool_calls") and message.tool_calls:
                            tool_calls = message.tool_calls
                            logger.debug(f"Found tool_calls: {type(tool_calls)} with {len(tool_calls)} items")
                        elif hasattr(message, "tools") and message.tools:
                            tool_calls = message.tools
                            logger.debug(f"Found tools: {type(tool_calls)} with {len(tool_calls)} items")
                        
                        # If we found tool calls, ensure they're in the right format
                        if tool_calls:
                            # Convert to list of dicts if they're not already
                            formatted_tools = []
                            for tool in tool_calls:
                                if hasattr(tool, "to_dict"):
                                    # ToolExecution object with to_dict method
                                    formatted_tools.append(tool.to_dict())
                                elif hasattr(tool, "tool_name"):
                                    # ToolExecution-like object
                                    tool_dict = {
                                        "tool_name": getattr(tool, "tool_name", "Unknown"),
                                        "tool_args": getattr(tool, "tool_args", {}),
                                        "result": getattr(tool, "result", ""),
                                    }
                                    formatted_tools.append(tool_dict)
                                elif isinstance(tool, dict):
                                    # Already a dictionary
                                    formatted_tools.append(tool)
                                else:
                                    logger.debug(f"Unknown tool format: {type(tool)} - {tool}")
                            
                            tool_calls = formatted_tools if formatted_tools else None
                            logger.debug(f"Formatted {len(formatted_tools)} tool calls for display")
                        
                        add_message("assistant", str(message.content), tool_calls)
        except Exception as e:
            logger.warning(f"Could not load chat history: {e}")

        st.rerun()
    except Exception as e:
        logger.error(f"Error loading session: {e}")
        st.sidebar.error(f"Error loading session: {str(e)}")


def get_model_from_id(model_id: str):
    """Get model instance from ID."""
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


# Common CSS for streamlit apps
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
