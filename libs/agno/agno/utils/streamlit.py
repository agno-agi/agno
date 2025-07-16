"""
Shared utilities for Streamlit applications using Agno.

This module provides common functions used across multiple Streamlit apps
to avoid code duplication and ensure consistency.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.models.response import ToolExecution
from agno.utils.log import logger


def add_message(role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None, **kwargs) -> None:
    """
    Safely add a message to the session state.

    Args:
        role: The role of the message sender (user/assistant)
        content: The text content of the message
        tool_calls: Optional tool calls to include
        **kwargs: Additional message attributes (image, audio, video paths)
    """
    if "messages" not in st.session_state or not isinstance(st.session_state["messages"], list):
        st.session_state["messages"] = []

    message = {"role": role, "content": content, "tool_calls": tool_calls}

    # Add any additional attributes like image, audio, or video paths
    for key, value in kwargs.items():
        message[key] = value

    st.session_state["messages"].append(message)


def display_tool_calls(tool_calls_container, tools: List[ToolExecution]):
    """Display tool calls in a streamlit container with expandable sections."""
    if not tools:
        return

    with tool_calls_container.container():
        for tool_call in tools:
            # Get basic info from tool call
            if hasattr(tool_call, "tool_name"):
                # ToolExecution object
                tool_name = tool_call.tool_name or "Unknown Tool"
                tool_args = tool_call.tool_args or {}
                content = tool_call.result or ""
                metrics = tool_call.metrics or {}
            else:
                # Dictionary format
                tool_name = tool_call.get("tool_name") or tool_call.get("name") or "Unknown Tool"
                tool_args = tool_call.get("tool_args") or tool_call.get("args") or {}
                content = tool_call.get("result") or tool_call.get("content") or ""
                metrics = tool_call.get("metrics") or {}

            # Simple title
            title = f"🛠️ {tool_name.replace('_', ' ')}"

            with st.expander(title, expanded=False):
                if tool_args:
                    st.markdown("**Arguments:**")
                    st.json(tool_args)

                if content:
                    st.markdown("**Results:**")
                    if isinstance(content, (dict, list)):
                        st.json(content)
                    else:
                        st.markdown(content)

                if metrics:
                    st.markdown("**Metrics:**")
                    st.json(metrics if isinstance(metrics, dict) else metrics.to_dict())


def export_chat_history(app_name: str = "Chat", session_key: str = "messages") -> str:
    """
    Export chat history as markdown with professional formatting.

    Args:
        app_name: Name of the application for the footer
        session_key: Session state key containing messages

    Returns:
        Formatted markdown string of chat history
    """
    if session_key not in st.session_state or not st.session_state[session_key]:
        return f"# Chat History\n\n*No messages to export*"

    # Find the first user message to use as title
    title = "Chat History"  # Default fallback
    for msg in st.session_state[session_key]:
        if msg.get("role") == "user":
            user_content = msg.get("content", "").strip()
            if user_content:
                title = user_content[:100] + ("..." if len(user_content) > 100 else "")
                break

    # Create header with meaningful title
    chat_text = f"# {title}\n\n"

    # Add metadata
    export_time = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    chat_text += f"**Exported:** {export_time}\n"

    # Count meaningful messages (exclude empty/None responses)
    meaningful_messages = [
        msg
        for msg in st.session_state[session_key]
        if msg.get("content") and str(msg.get("content")).strip() and str(msg.get("content")).strip().lower() != "none"
    ]

    chat_text += f"**Messages:** {len(meaningful_messages)}\n\n"
    chat_text += "---\n\n"

    # Export messages with improved formatting
    for i, msg in enumerate(meaningful_messages, 1):
        role = msg.get("role", "unknown")
        content = str(msg.get("content", "")).strip()

        # Skip empty or "None" content
        if not content or content.lower() == "none":
            continue

        # Format role with better styling
        if role == "user":
            role_display = "## 🙋 User Query"
        elif role == "assistant":
            role_display = "## 🤖 Assistant Response"
        else:
            role_display = f"## {role.capitalize()}"

        chat_text += f"{role_display}\n\n"
        chat_text += f"{content}\n\n"

        # Add separator between exchanges (not after last message)
        if i < len(meaningful_messages):
            chat_text += "---\n\n"

    # Footer
    chat_text += f"\n*Generated by {app_name}*"
    return chat_text


def restart_agent_session(
    agent_session_key: str,
    session_id_key: Optional[str] = None,
    model_key: Optional[str] = None,
    messages_key: str = "messages",
) -> None:
    """
    Reset agent and clear chat history from session state.

    Args:
        agent_session_key: Session state key for the agent
        session_id_key: Optional session state key for session ID
        model_key: Optional session state key for current model
        messages_key: Session state key for messages
    """
    logger.debug("---*--- Restarting agent ---*---")
    st.session_state[agent_session_key] = None
    if session_id_key:
        st.session_state[session_id_key] = None
    if model_key:
        st.session_state[model_key] = None
    st.session_state[messages_key] = []
    st.rerun()


def rename_session_widget(agent: Agent, container: Optional[st.container] = None) -> None:
    """
    Render a session rename widget in the sidebar.

    Args:
        agent: The agent whose session to rename
        container: Optional container to render in (defaults to sidebar)
    """
    # Only show rename widget if there's an active session
    if not agent.session_id:
        return

    if container is None:
        container = st.sidebar.container()

    # Initialize session_edit_mode if needed
    if "session_edit_mode" not in st.session_state:
        st.session_state.session_edit_mode = False

    # Get current session name, default to session_id if no name is set
    current_name = agent.session_name or agent.session_id

    with container:
        if not st.session_state.session_edit_mode:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**Session:** {current_name}")
            with col2:
                if st.button("✎", help="Rename session", key="rename_button"):
                    st.session_state.session_edit_mode = True
                    st.rerun()
        else:
            st.write("**Rename Session:**")

            # Use current session name or session_id as default
            new_session_name = st.text_input(
                "Enter new name:",
                value=current_name,
                key="session_name_input",
                placeholder="Enter session name...",
            )

            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("💾 Save", type="primary", use_container_width=True):
                    if new_session_name and new_session_name.strip():
                        try:
                            agent.rename_session(new_session_name.strip())
                            logger.debug(f"Renamed session to: {new_session_name.strip()}")
                            st.session_state.session_edit_mode = False
                            st.sidebar.success("Session renamed!")
                            st.rerun()
                        except Exception as e:
                            logger.error(f"Error renaming session: {e}")
                            st.sidebar.error(f"Failed to rename session: {str(e)}")
                    else:
                        st.sidebar.error("Please enter a valid session name")

            with col2:
                if st.button("❌ Cancel", use_container_width=True):
                    st.session_state.session_edit_mode = False
                    st.rerun()


def knowledge_base_info_widget(agent: Agent, container: Optional[st.container] = None) -> None:
    """
    Display knowledge base information in a widget.

    Args:
        agent: The agent whose knowledge base to display
        container: Optional container to render in (defaults to sidebar)
    """
    if container is None:
        container = st.sidebar

    # Support both v1 (vector_db) and v2 (vector_store) knowledge systems
    vector_store = None
    if agent.knowledge:
        if hasattr(agent.knowledge, "vector_store") and agent.knowledge.vector_store:
            vector_store = agent.knowledge.vector_store
        elif hasattr(agent.knowledge, "vector_db") and agent.knowledge.vector_db:
            vector_store = agent.knowledge.vector_db

    if vector_store:
        try:
            # Try to get count from vector store
            doc_count = vector_store.get_count()

            container.markdown("### 📚 Knowledge Base")
            container.metric(
                label="Documents Loaded",
                value=doc_count,
                help="Number of documents in the knowledge base",
            )

            if doc_count == 0:
                container.info("💡 Upload documents to populate the knowledge base")

        except Exception as e:
            logger.error(f"Error getting knowledge base info: {e}")
            container.markdown("### 📚 Knowledge Base")
            container.warning("Could not retrieve knowledge base information")
    else:
        container.markdown("### 📚 Knowledge Base")
        container.info("No knowledge base configured")


def utilities_widget(
    agent_restart_callback: callable,
    export_filename: str = "chat_history.md",
    messages_key: str = "messages",
    container: Optional[st.container] = None,
) -> None:
    """
    Display a utilities widget with common actions.

    Args:
        agent_restart_callback: Function to call when restarting the agent
        export_filename: Default filename for chat export
        messages_key: Session state key for messages
        container: Optional container to render in (defaults to sidebar)
    """
    if container is None:
        container = st.sidebar

    container.markdown("#### 🛠️ Utilities")
    col1, col2 = container.columns([1, 1])

    with col1:
        if st.button("🔄 New Chat", use_container_width=True):
            agent_restart_callback()

    with col2:
        # Export chat functionality
        has_messages = st.session_state.get(messages_key) and len(st.session_state[messages_key]) > 0

        if has_messages:
            if st.download_button(
                "💾 Export Chat",
                export_chat_history(),
                file_name=export_filename,
                mime="text/markdown",
                use_container_width=True,
                help=f"Export {len(st.session_state[messages_key])} messages",
            ):
                container.success("Chat history exported!")
        else:
            st.button(
                "💾 Export Chat",
                disabled=True,
                use_container_width=True,
                help="No messages to export",
            )


def get_model_from_id(model_id: str):
    """Get the model instance based on the model ID.

    Args:
        model_id: Model ID in the format "provider:model_name"

    Returns:
        Model instance

    Example:
        >>> model = get_model_from_id("openai:gpt-4o")
        >>> model = get_model_from_id("anthropic:claude-3-5-sonnet")
        >>> model = get_model_from_id("google:gemini-2.0-flash")
        >>> model = get_model_from_id("groq:llama-3.3-70b")
    """
    if model_id.startswith("openai:"):
        model_name = model_id.split("openai:")[1]
        return OpenAIChat(id=model_name)
    elif model_id.startswith("anthropic:"):
        model_name = model_id.split("anthropic:")[1]
        return Claude(id=model_name)
    elif model_id.startswith("google:"):
        model_name = model_id.split("google:")[1]
        return Gemini(id=model_name)
    elif model_id.startswith("groq:"):
        model_name = model_id.split("groq:")[1]
        return Groq(id=model_name)
    else:
        return OpenAIChat(id="gpt-4o")


# Common CSS styles for Streamlit apps
COMMON_CSS = """
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
    .tool-result {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 1em;
        margin: 1em 0;
        border-left: 4px solid #3B82F6;
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
        .tool-result {
            background-color: #1e1e1e;
        }
    }
    </style>
"""
