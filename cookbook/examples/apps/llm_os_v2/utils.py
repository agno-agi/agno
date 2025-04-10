import json
from dataclasses import asdict
from typing import Any, Dict, List, Optional

import streamlit as st
from agno.agent.agent import Agent
from agno.utils.log import logger
from os_agent import get_llm_os


def is_json(myjson):
    """Check if a string is valid JSON"""
    try:
        json.loads(myjson)
    except (ValueError, TypeError):
        return False
    return True


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


def display_tool_calls(tool_calls_container, tools):
    """Display tool calls in a streamlit container with expandable sections.

    Args:
        tool_calls_container: Streamlit container to display the tool calls
        tools: List of tool call dictionaries containing name, args, content, and metrics
    """
    try:
        with tool_calls_container.container():
            # Handle single tool_call dict case
            if isinstance(tools, dict):
                tools = [tools]
            elif not isinstance(tools, list):
                logger.warning(f"Unexpected tools format: {type(tools)}. Skipping display.")
                return

            for tool_call in tools:
                # Normalize access to tool details
                tool_name = tool_call.get("tool_name") or tool_call.get("name", "Unknown Tool")
                tool_args = tool_call.get("tool_args") or tool_call.get("args", {})
                content = tool_call.get("content", None)
                metrics = tool_call.get("metrics", None)

                # Add timing information safely
                execution_time_str = "N/A"
                try:
                    if metrics is not None and hasattr(metrics, "time"):
                        execution_time = metrics.time
                        if execution_time is not None:
                            execution_time_str = f"{execution_time:.4f}s"
                except Exception as e:
                    logger.error(f"Error getting tool metrics time: {str(e)}")
                    pass # Keep default "N/A"

                expander_title = f"🛠️ {tool_name.replace('_', ' ').title()}"
                if execution_time_str != "N/A":
                    expander_title += f" ({execution_time_str})"

                with st.expander(expander_title, expanded=False):
                    # Show query/code/command with syntax highlighting
                    if isinstance(tool_args, dict):
                        if "query" in tool_args:
                            st.code(tool_args["query"], language="sql")
                        elif "code" in tool_args:
                             st.code(tool_args["code"], language="python")
                        elif "command" in tool_args:
                             st.code(tool_args["command"], language="bash")

                    # Display arguments if they exist and are not just the code/query shown above
                    args_to_show = {k: v for k, v in tool_args.items() if k not in ['query', 'code', 'command']}
                    if args_to_show:
                        st.markdown("**Arguments:**")
                        try:
                            st.json(args_to_show)
                        except Exception:
                             st.write(args_to_show) # Fallback for non-serializable args

                    if content is not None:
                        try:
                            st.markdown("**Results:**")
                            if isinstance(content, str) and is_json(content):
                                st.json(content)
                            else:
                                st.write(content)
                        except Exception as e:
                            logger.debug(f"Could not display tool content: {e}")
                            st.error("Could not display tool content.")

    except Exception as e:
        logger.error(f"Error displaying tool calls: {str(e)}")
        tool_calls_container.error("Failed to display tool results")


def about_widget() -> None:
    """Display an about section in the sidebar"""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.markdown("""
    LLM OS: Your versatile AI assistant.

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
    /* Minor style adjustments for consistency */
    .stChatMessage {
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    [data-testid="stChatMessageContent"] p {
        margin: 0;
        line-height: 1.6;
    }
     [data-testid="stChatMessageContent"] pre code {
        white-space: pre-wrap !important;
        word-wrap: break-word !important;
    }
    [data-testid="stChatMessageContent"] [data-testid="stExpander"] {
        border: 1px solid #D1D5DB; /* Light border for expanders */
        border-radius: 5px;
    }
    [data-testid="stChatMessageContent"] [data-testid="stExpander"] summary {
        font-weight: 500;
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
    /* Fix chat input to bottom */
    .stChatInputContainer {
        position: fixed;
        bottom: 0;
        width: calc(100% - 2rem); /* Adjust width considering potential padding */
        background-color: #ffffff; /* Match light theme background */
        padding: 1rem;
        border-top: 1px solid #e0e0e0; /* Add a subtle top border */
        z-index: 1000; /* Ensure it stays on top */
        margin-left: -1rem; /* Offset default padding if necessary */
    }
    /* Adjust main content padding to prevent overlap */
    .main .block-container {
        padding-bottom: 7rem;
    }

    /* Dark mode adjustments */
    @media (prefers-color-scheme: dark) {
        .stApp {
            background-color: #1F2937; /* Dark gray background */
            color: #D1D5DB;
        }
        .main-title {
            background: linear-gradient(45deg, #e98a79, #e78fa5);
            -webkit-background-clip: text;
        }
        .subtitle {
            color: #9CA3AF; /* Lighter gray */
        }
        .stChatMessage {
            background-color: #374151; /* Slightly lighter dark gray */
            box-shadow: none;
        }
         [data-testid="stChatMessageContent"] p {
            color: #D1D5DB;
        }
         [data-testid="stChatMessageContent"] [data-testid="stExpander"] {
            border: 1px solid #4B5563;
        }
         [data-testid="stChatMessageContent"] [data-testid="stExpander"] summary {
            color: #BFDBFE;
        }
        .chat-container {
            background-color: #2b2b2b;
        }
        .success-message {
             background-color: #1c3d24; /* Darker success */
             color: #a4edb5;
        }
        .error-message {
            background-color: #4a1c24; /* Darker error */
            color: #f8a7ae;
        }
        /* Dark mode chat input */
        .stChatInputContainer {
            background-color: #1F2937; /* Match dark theme background */
            border-top: 1px solid #4B5563;
        }
    }
    </style>
"""

def restart_agent():
    """Reset the agent and clear chat history, tailored for llm_os_agent"""
    logger.debug("---*--- Restarting LLM OS agent ---*---")
    st.session_state["llm_os_agent"] = None
    st.session_state["current_config"] = None # Reset config to trigger re-init
    st.session_state["messages"] = []
    st.rerun()

def export_chat_history():
    """Export chat history as markdown, tailored for llm_os_agent"""
    if "messages" in st.session_state:
        # Use LLM OS in title
        chat_text = "# LLM OS - Chat History\n\n"
        for msg in st.session_state["messages"]:
            role = "🤖 Assistant" if msg["role"] == "assistant" else "👤 User"
            chat_text += f"### {role}\n{msg['content']}\n\n"
            # Optionally include tool calls in export
            if msg.get("tool_calls"):
                # Use str() for safer representation instead of json.dumps
                # This avoids errors with non-serializable objects like MessageMetrics
                try:
                    tool_calls_repr = str(msg["tool_calls"])
                    chat_text += "```\nTool Calls:\n" + tool_calls_repr + "\n```\n\n"
                except Exception as e:
                    logger.error(f"Error representing tool_calls for export: {e}")
                    chat_text += "```\nError representing tool calls.\n```\n\n"
        return chat_text
    return ""

def session_selector_widget(agent: Agent, current_config: Dict[str, Any]) -> None:
    """Display a session selector in the sidebar for LLM OS"""
    if agent.storage:
        # Add user_id filter if available in current_config
        user_id_filter = current_config.get("user_id")
        agent_sessions = agent.storage.get_all_sessions(user_id=user_id_filter)

        if not agent_sessions:
             st.sidebar.caption("No sessions yet for this user.")
             return

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
        selected_session_display = st.sidebar.selectbox(
            "Select Session",
            options=[s["display"] for s in session_options],
            index=0, # Default to the first/most recent session
            key="session_selector",
        )
        # Find the selected session ID
        selected_session_id = next((
            s["id"] for s in session_options if s["display"] == selected_session_display
        ), None)

        # Only reload if the selected session ID is different from the current agent's
        if selected_session_id and agent.session_id != selected_session_id:
            logger.info(
                f"---*--- Session selection changed to: {selected_session_id} (User: {current_config.get('user_id')}) ---*---"
            )
            # Re-initialize the agent with the selected session ID (mirroring sql_agent pattern)
            try:
                logger.debug(f"[Widget] Attempting to re-initialize agent for selected session: {selected_session_id}")
                new_agent = get_llm_os(
                    session_id=selected_session_id,
                    **current_config # Pass other relevant config including user_id
                )
                logger.debug(f"[Widget] Re-initialized agent. New agent session_id: {new_agent.session_id}, Memory runs count: {len(new_agent.memory.runs) if hasattr(new_agent.memory, 'runs') else 'N/A'}")
                st.session_state["llm_os_agent"] = new_agent
                st.session_state["current_config"] = current_config # Ensure config remains consistent
                st.session_state["messages"] = [] # Clear messages for the new session
                logger.info(f"Session Selector: Re-initialized agent for session {selected_session_id}. Cleared UI messages. Triggering rerun.")
                if "llm_os_agent" in st.session_state and st.session_state["llm_os_agent"]:
                    agent_in_state = st.session_state['llm_os_agent']
                    logger.debug(f"[Widget] State before rerun - Agent ID: {agent_in_state.session_id}, Memory runs: {len(agent_in_state.memory.runs) if hasattr(agent_in_state.memory, 'runs') else 'N/A'}")
                else:
                    logger.debug("[Widget] State before rerun - Agent not found in session state.")
                st.rerun()
            except Exception as e:
                logger.error(f"Failed to re-initialize agent for session {selected_session_id}: {e}", exc_info=True)
                st.error(f"Failed to load session: {e}")

def rename_session_widget(agent: Agent) -> None:
    """Rename the current session of the agent and save to storage"""
    if not agent.session_id:
        st.sidebar.caption("Session not yet saved.")
        return

    container = st.sidebar.container()
    session_row = container.columns([3, 1], vertical_alignment="bottom")

    # Initialize session_edit_mode if needed
    if "session_edit_mode" not in st.session_state:
        st.session_state.session_edit_mode = False

    with session_row[0]:
        # Display current name or input field
        current_name = agent.session_name or agent.session_id
        if st.session_state.session_edit_mode:
            new_session_name = st.text_input(
                "Rename Session:",
                value=current_name, # Show current name/ID as default
                key="session_name_input",
                label_visibility="collapsed",
            )
        else:
            st.markdown(f"**Session:** {current_name}")

    with session_row[1]:
        if st.session_state.session_edit_mode:
            if st.button("✓", key="save_session_name", help="Save name"):
                if new_session_name and new_session_name != agent.session_id:
                    try:
                        agent.rename_session(new_session_name)
                        st.session_state.session_edit_mode = False
                        st.rerun() # Rerun to update display
                    except Exception as e:
                        logger.error(f"Failed to rename session: {e}")
                        st.error(f"Failed to rename: {e}")
                else:
                    # If name is empty or same as ID, just exit edit mode
                    st.session_state.session_edit_mode = False
                    st.rerun()
        else:
            if st.button("✎", key="edit_session_name", help="Rename session"):
                st.session_state.session_edit_mode = True
                st.rerun()
