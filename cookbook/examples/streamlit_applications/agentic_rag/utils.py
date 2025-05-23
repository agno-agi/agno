from typing import Any, Dict, List, Optional

import streamlit as st
from agentic_rag import get_agentic_rag_agent
from agno.agent import Agent
from agno.utils.log import logger


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


def export_chat_history():
    """Export chat history as markdown"""
    if "messages" in st.session_state:
        chat_text = "# Auto RAG Agent - Chat History\n\n"
        for msg in st.session_state["messages"]:
            role = "🤖 Assistant" if msg["role"] == "agent" else "👤 User"
            chat_text += f"### {role}\n{msg['content']}\n\n"
            if msg.get("tool_calls"):
                chat_text += "#### Tools Used:\n"
                for tool in msg["tool_calls"]:
                    if isinstance(tool, dict):
                        tool_name = tool.get("name", "Unknown Tool")
                    else:
                        tool_name = getattr(tool, "name", "Unknown Tool")
                    chat_text += f"- {tool_name}\n"
        return chat_text
    return ""


def display_tool_calls(tool_calls_container, tools):
    """Display tool calls in a streamlit container with expandable sections.

    Args:
        tool_calls_container: Streamlit container to display the tool calls
        tools: List of tool call dictionaries containing name, args, content, and metrics
    """
    if not tools:
        return

    with tool_calls_container.container():
        for tool_call in tools:
            # Handle different tool call formats
            _tool_name = (
                tool_call.get("tool_name") or tool_call.get("name") or "Unknown Tool"
            )
            _tool_args = tool_call.get("tool_args") or tool_call.get("arguments") or {}
            _content = tool_call.get("content") or tool_call.get("result", "")
            _metrics = tool_call.get("metrics", {})

            # Handle function objects
            if hasattr(tool_call, "function") and tool_call.function:
                if hasattr(tool_call.function, "name"):
                    _tool_name = tool_call.function.name
                if hasattr(tool_call.function, "arguments"):
                    _tool_args = tool_call.function.arguments

            # Safely create the title with a default if tool name is None
            title = f"🛠️ {_tool_name.replace('_', ' ').title() if _tool_name else 'Tool Call'}"

            with st.expander(title, expanded=False):
                if isinstance(_tool_args, dict) and "query" in _tool_args:
                    st.code(_tool_args["query"], language="sql")
                # Handle string arguments
                elif isinstance(_tool_args, str) and _tool_args:
                    try:
                        # Try to parse as JSON
                        import json

                        args_dict = json.loads(_tool_args)
                        st.markdown("**Arguments:**")
                        st.json(args_dict)
                    except:
                        # If not valid JSON, display as string
                        st.markdown("**Arguments:**")
                        st.markdown(f"```\n{_tool_args}\n```")
                # Handle dict arguments
                elif _tool_args and _tool_args != {"query": None}:
                    st.markdown("**Arguments:**")
                    st.json(_tool_args)

                if _content:
                    st.markdown("**Results:**")
                    if isinstance(_content, (dict, list)):
                        st.json(_content)
                    else:
                        try:
                            st.json(_content)
                        except Exception:
                            st.markdown(_content)

                if _metrics:
                    st.markdown("**Metrics:**")
                    st.json(_metrics)


def rename_session_widget(agent: Agent) -> None:
    """Rename the current session of the agent and save to storage"""

    container = st.sidebar.container()

    # Initialize session_edit_mode if needed
    if "session_edit_mode" not in st.session_state:
        st.session_state.session_edit_mode = False

    if st.sidebar.button("✎ Rename Session"):
        st.session_state.session_edit_mode = True
        st.rerun()

    if st.session_state.session_edit_mode:
        new_session_name = st.sidebar.text_input(
            "Enter new name:",
            value=agent.session_name,
            key="session_name_input",
        )
        if st.sidebar.button("Save", type="primary"):
            if new_session_name:
                agent.rename_session(new_session_name)
                st.session_state.session_edit_mode = False
                st.rerun()


def session_selector_widget(agent: Agent, model_id: str) -> None:
    """Display a session selector in the sidebar"""

    if agent.storage:
        agent_sessions = agent.storage.get_all_sessions()
        # print(f"Agent sessions: {agent_sessions}")

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

        if session_options:
            selected_session = st.sidebar.selectbox(
                "Session",
                options=[s["display"] for s in session_options],
                key="session_selector",
            )
            # Find the selected session ID
            selected_session_id = next(
                s["id"] for s in session_options if s["display"] == selected_session
            )

            if (
                st.session_state.get("agentic_rag_agent_session_id")
                != selected_session_id
            ):
                logger.info(
                    f"---*--- Loading {model_id} run: {selected_session_id} ---*---"
                )

                try:
                    new_agent = get_agentic_rag_agent(
                        model_id=model_id,
                        session_id=selected_session_id,
                    )

                    st.session_state["agentic_rag_agent"] = new_agent
                    st.session_state["agentic_rag_agent_session_id"] = (
                        selected_session_id
                    )

                    st.session_state["messages"] = []

                    selected_session_obj = next(
                        (
                            s
                            for s in agent_sessions
                            if s.session_id == selected_session_id
                        ),
                        None,
                    )

                    if (
                        selected_session_obj
                        and selected_session_obj.memory
                        and "runs" in selected_session_obj.memory
                    ):
                        seen_messages = set()

                        for run in selected_session_obj.memory["runs"]:
                            if "messages" in run:
                                for msg in run["messages"]:
                                    msg_role = msg.get("role")
                                    msg_content = msg.get("content")

                                    if not msg_content or msg_role == "system":
                                        continue

                                    msg_id = f"{msg_role}:{msg_content}"

                                    if msg_id in seen_messages:
                                        continue

                                    seen_messages.add(msg_id)

                                    if msg_role == "assistant":
                                        tool_calls = None
                                        if "tool_calls" in msg:
                                            tool_calls = msg["tool_calls"]
                                        elif "metrics" in msg and msg.get("metrics"):
                                            tools = run.get("tools")
                                            if tools:
                                                tool_calls = tools

                                        add_message(msg_role, msg_content, tool_calls)
                                    else:
                                        add_message(msg_role, msg_content)

                            elif (
                                "message" in run
                                and isinstance(run["message"], dict)
                                and "content" in run["message"]
                            ):
                                user_msg = run["message"]["content"]
                                msg_id = f"user:{user_msg}"

                                if msg_id not in seen_messages:
                                    seen_messages.add(msg_id)
                                    add_message("user", user_msg)

                                if "content" in run and run["content"]:
                                    asst_msg = run["content"]
                                    msg_id = f"assistant:{asst_msg}"

                                    if msg_id not in seen_messages:
                                        seen_messages.add(msg_id)
                                        add_message(
                                            "assistant", asst_msg, run.get("tools")
                                        )

                    st.rerun()
                except Exception as e:
                    logger.error(f"Error switching sessions: {str(e)}")
                    st.sidebar.error(f"Error loading session: {str(e)}")
        else:
            st.sidebar.info("No saved sessions available.")


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
