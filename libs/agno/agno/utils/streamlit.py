from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

try:
    from agno.agent import Agent
    from agno.db.base import SessionType
    from agno.models.anthropic import Claude
    from agno.models.google import Gemini
    from agno.models.openai import OpenAIChat
    from agno.utils.log import logger
except ImportError:
    raise ImportError("`agno` not installed. Please install using `pip install agno`")

try:
    import streamlit as st
except ImportError:
    raise ImportError("`streamlit` not installed. Please install using `pip install streamlit`")


def add_message(role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None) -> None:
    """Add a message to the session state."""
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    message: Dict[str, Any] = {"role": role, "content": content}
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


def session_selector_widget(agent: Agent, model_id: str, agent_creation_callback: Callable[[str, str], Agent]) -> None:
    """Session selector widget"""
    if not agent.db:
        st.sidebar.info("💡 Database not configured. Sessions will not be saved.")
        return

    try:
        sessions = agent.db.get_sessions(
            session_type=SessionType.AGENT,
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

    # Filter session data
    session_options = []
    session_dict = {}

    for session in sessions:  # type: ignore
        if not hasattr(session, "session_id") or not session.session_id:
            continue

        session_id = session.session_id
        session_name = None

        # Extract session name from session_data
        if hasattr(session, "session_data") and session.session_data:
            session_name = session.session_data.get("session_name")

        name = session_name or session_id
        session_options.append(name)
        session_dict[name] = session_id

    current_session_id = st.session_state.get("session_id")
    current_selection = None

    if current_session_id and current_session_id not in [s_id for s_id in session_dict.values()]:
        logger.info(f"New session: {current_session_id}")
        if agent.get_session_name():
            current_display_name = agent.get_session_name()
        else:
            current_display_name = f"{current_session_id[:8]}..."
        session_options.insert(0, current_display_name)
        session_dict[current_display_name] = current_session_id
        current_selection = current_display_name
        st.session_state["is_new_session"] = True

    for display_name, session_id in session_dict.items():
        if session_id == current_session_id:
            current_selection = display_name
            break

    display_options = session_options
    selected_index = (
        session_options.index(current_selection)
        if current_selection and current_selection in session_options
        else 0
        if session_options
        else None
    )

    if not display_options:
        st.sidebar.info("🆕 Start your first conversation!")
        return

    selected = st.sidebar.selectbox(
        label="Session",
        options=display_options,
        index=selected_index,
        help="Select a session to continue",
    )

    if selected and selected in session_dict:
        selected_session_id = session_dict[selected]
        if selected_session_id != current_session_id:
            if not st.session_state.get("is_new_session", False):
                st.session_state["is_loading_session"] = True
                try:
                    _load_session(selected_session_id, model_id, agent_creation_callback)
                finally:
                    # Always clear the loading flag, even if there's an error
                    st.session_state["is_loading_session"] = False
            else:
                # Clear the new session flag since we're done with initialization
                st.session_state["is_new_session"] = False

    # Rename session
    if agent.session_id:
        if "session_edit_mode" not in st.session_state:
            st.session_state.session_edit_mode = False

        current_name = agent.get_session_name() or agent.session_id

        if not st.session_state.session_edit_mode:
            col1, col2 = st.sidebar.columns([3, 1])
            with col1:
                st.write(f"**Session:** {current_name}")
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
                            result = agent.set_session_name(session_name=new_name.strip())

                            if result:
                                logger.info(f"Session renamed to: {new_name.strip()}")
                                # Clear any cached session data to ensure fresh reload
                                if hasattr(agent, "_agent_session") and agent._agent_session:
                                    agent._agent_session = None
                            st.session_state.session_edit_mode = False
                            st.sidebar.success("Session renamed!")
                            st.rerun()
                        except Exception as e:
                            logger.error(f"Error renaming session: {e}")
                            st.sidebar.error(f"Error: {str(e)}")
                    else:
                        st.sidebar.error("Please enter a valid name")

            with col2:
                if st.button("❌ Cancel", use_container_width=True, key="cancel_session_rename"):
                    st.session_state.session_edit_mode = False
                    st.rerun()


def _load_session(session_id: str, model_id: str, agent_creation_callback: Callable[[str, str], Agent]):
    try:
        logger.info(f"Creating agent with session_id: {session_id}")
        new_agent = agent_creation_callback(model_id, session_id)

        st.session_state["agent"] = new_agent
        st.session_state["session_id"] = session_id
        st.session_state["messages"] = []
        st.session_state["current_model"] = model_id  # Keep current_model in sync

        try:
            if new_agent.db:
                selected_session = new_agent.db.get_session(
                    session_id=session_id, session_type=SessionType.AGENT, deserialize=True
                )
            else:
                selected_session = None

            # Recreate the chat history
            if selected_session:
                if hasattr(selected_session, "runs") and selected_session.runs:
                    for run_idx, run in enumerate(selected_session.runs):
                        messages = getattr(run, "messages", None)

                        if messages:
                            user_msg = None
                            assistant_msg = None
                            tool_calls = []

                            for msg_idx, message in enumerate(messages):
                                if not hasattr(message, "role") or not hasattr(message, "content"):
                                    continue

                                role = message.role
                                content = str(message.content) if message.content else ""

                                if role == "user":
                                    if content and content.strip():
                                        user_msg = content.strip()
                                elif role == "assistant":
                                    if content and content.strip() and content.strip().lower() != "none":
                                        assistant_msg = content

                            # Display tool calls for this run
                            if hasattr(run, "tools") and run.tools:
                                tool_calls = run.tools

                            # Add messages to chat history
                            if user_msg:
                                add_message("user", user_msg)
                            if assistant_msg:
                                add_message("assistant", assistant_msg, tool_calls)

            else:
                logger.warning(f"No session found in database for session_id: {session_id}")

        except Exception as e:
            logger.warning(f"Could not load chat history: {e}")

        st.rerun()

    except Exception as e:
        logger.error(f"Error loading session: {e}")
        st.sidebar.error(f"Error loading session: {str(e)}")


def display_response(agent: Agent, question: str) -> None:
    """Handle agent response with streaming and tool call display."""
    with st.chat_message("assistant"):
        tool_calls_container = st.empty()
        resp_container = st.empty()
        with st.spinner("🤔 Thinking..."):
            response = ""
            try:
                # Run the agent and stream the response
                run_response = agent.run(question, stream=True)
                for resp_chunk in run_response:
                    try:
                        # Display tool calls if available
                        if hasattr(resp_chunk, "tool") and resp_chunk.tool:
                            display_tool_calls(tool_calls_container, [resp_chunk.tool])
                    except Exception as tool_error:
                        logger.warning(f"Error displaying tool calls: {tool_error}")

                    if resp_chunk.content is not None:
                        content = str(resp_chunk.content)

                        if not (
                            content.strip().endswith("completed in") or "completed in" in content and "s." in content
                        ):
                            response += content
                            resp_container.markdown(response)

                try:
                    if hasattr(agent, "run_response") and agent.run_response and hasattr(agent.run_response, "tools"):
                        add_message("assistant", response, agent.run_response.tools)
                    else:
                        add_message("assistant", response)
                except Exception as add_msg_error:
                    logger.warning(f"Error adding message with tools: {add_msg_error}")
                    add_message("assistant", response)

            except Exception as e:
                st.error(f"Sorry, I encountered an error: {str(e)}")


def display_chat_messages() -> None:
    """Display all chat messages from session state."""
    if "messages" not in st.session_state:
        return

    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            content = message["content"]
            with st.chat_message(message["role"]):
                # Display tool calls
                if "tool_calls" in message and message["tool_calls"]:
                    display_tool_calls(st.container(), message["tool_calls"])

                if content is not None and str(content).strip() and str(content).strip().lower() != "none":
                    st.markdown(content)


def initialize_agent(model_id: str, agent_creation_callback: Callable[[str, Optional[str]], Agent]) -> Agent:
    """Initialize or get agent with proper session management."""
    if "agent" not in st.session_state or st.session_state["agent"] is None:
        # First time initialization - get existing session_id if any
        session_id = st.session_state.get("session_id")
        agent = agent_creation_callback(model_id, session_id)
        st.session_state["agent"] = agent
        st.session_state["current_model"] = model_id

        return agent
    else:
        return st.session_state["agent"]


def reset_session_state(agent: Agent) -> None:
    """Update session state."""
    print(f"Resetting session state for agent: {agent.session_id}")
    if agent.session_id is not None:
        st.session_state["session_id"] = agent.session_id

    if "messages" not in st.session_state:
        st.session_state["messages"] = []


def knowledge_base_info_widget(agent: Agent) -> None:
    """Display knowledge base information widget."""
    if not agent.knowledge:
        st.sidebar.info("No knowledge base configured")
        return

    vector_db = getattr(agent.knowledge, "vector_db", None)
    if not vector_db:
        st.sidebar.info("No vector db configured")
        return

    try:
        doc_count = vector_db.get_count()
        if doc_count == 0:
            st.sidebar.info("💡 Upload documents to populate the knowledge base")
        else:
            st.sidebar.metric("Documents Loaded", doc_count)
    except Exception as e:
        logger.error(f"Error getting knowledge base info: {e}")
        st.sidebar.warning("Could not retrieve knowledge base information")


def export_chat_history(app_name: str = "Chat") -> str:
    """Export chat history to markdown."""
    if "messages" not in st.session_state or not st.session_state["messages"]:
        return "# Chat History\n\n*No messages to export*"

    title = f"{app_name} Chat History"
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


def get_model_from_id(model_id: str):
    """Get a model instance from a model ID string."""
    if model_id.startswith("openai:"):
        return OpenAIChat(id=model_id.split("openai:")[1])
    elif model_id.startswith("anthropic:"):
        return Claude(id=model_id.split("anthropic:")[1])
    elif model_id.startswith("google:"):
        return Gemini(id=model_id.split("google:")[1])
    else:
        return OpenAIChat(id="gpt-4o")


def get_model_with_provider(model_name: str):
    """Get a model instance by inferring the correct provider from the model name.

    Args:
        model_name: Model name (e.g., "gpt-4o", "claude-4-sonnet", "gemini-2.5-pro")

    Returns:
        Model instance with correct provider
    """
    if ":" in model_name:
        return get_model_from_id(model_name)

    model_lower = model_name.lower()

    if any(pattern in model_lower for pattern in ["gpt", "o1", "o3"]):
        return get_model_from_id(f"openai:{model_name}")

    elif "claude" in model_lower:
        return get_model_from_id(f"anthropic:{model_name}")

    elif "gemini" in model_lower:
        return get_model_from_id(f"google:{model_name}")

    else:
        return get_model_from_id(f"openai:{model_name}")


def about_section(description: str):
    """About section"""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.markdown(f"""
    {description}

    Built with:
    - 🚀 Agno
    - 💫 Streamlit
    """)


MODELS = [
    "gpt-4o",
    "o3-mini",
    "gpt-5",
    "claude-sonnet-4-5-20250929",
    "gemini-2.5-pro",
]


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
