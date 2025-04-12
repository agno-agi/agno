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


def restart_agent():
    """Reset the agent and clear chat history"""
    logger.debug("---*--- Restarting LLM OS agent ---*---")
    st.session_state["llm_os_agent"] = None
    st.session_state["llm_os_team"] = None
    st.session_state["llm_os_session_id"] = None
    st.session_state["messages"] = []
    # Clear relevant config keys to force reinitialization with sidebar values
    # This ensures the new agent uses the current sidebar settings
    keys_to_clear = [
        "cb_calculator", "cb_ddg", "cb_file", "cb_shell",
        "cb_data", "cb_python", "cb_research", "cb_investment",
        "model_selector", "user_id_input" # Clear these to re-read on rerun
    ]
    # for key in keys_to_clear:
    #     if key in st.session_state:
    #         del st.session_state[key] # Consider if clearing is needed vs. just re-reading in app.py
    st.rerun()


def export_chat_history():
    """Export chat history as markdown"""
    if "messages" in st.session_state:
        chat_text = "# LLM OS - Chat History\n\n"
        for msg in st.session_state["messages"]:
            role = "🤖 Assistant" if msg["role"] == "assistant" else "👤 User" # Adjusted role check
            # Safely handle content, could be None
            content = msg.get('content', "*No content*")
            chat_text += f"### {role}\n{content}\n\n"
            # Optionally include tool calls (basic representation)
            if msg.get("tool_calls"):
                chat_text += "**Tool Calls:**\n"
                for tc in msg["tool_calls"]:
                    tool_name = tc.get("name", "Unknown Tool")
                    tool_args = tc.get("args", {})
                    chat_text += f"- `{tool_name}`: `{tool_args}`\n"
                chat_text += "\n"
        return chat_text
    return ""


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
    st.sidebar.markdown("Build your own agents using [Agno](https://github.com/agytech/agno)!")


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
        margin-bottom: 20px;
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


# ---- NEW SESSION MANAGEMENT WIDGETS ----

def session_selector_widget(agent_or_team: Any, config: Dict[str, Any], current_session_id_from_state: Optional[str]) -> None:
    """Display a session selector in the sidebar and handle session loading"""
    # Ensure storage is available
    if not hasattr(agent_or_team, 'storage') or not agent_or_team.storage:
        st.sidebar.warning("Session storage not configured.")
        return

    try:
        # Use storage object directly
        storage = agent_or_team.storage
        agent_sessions = storage.get_all_sessions()
        if not agent_sessions:
            st.sidebar.info("No previous sessions found.")
            return

        session_options = []
        for session in agent_sessions:
            session_id = session.session_id
            session_name = session.session_data.get("session_name", session_id) if session.session_data else session_id
            session_options.append({"id": session_id, "display": session_name})

        # Display session selector using the display names
        # Use the explicitly passed current_session_id_from_state for determining the index
        current_index = next((i for i, s in enumerate(session_options) if s["id"] == current_session_id_from_state), 0)

        selected_session_display = st.sidebar.selectbox(
            "Load Session",
            options=[s["display"] for s in session_options],
            index=current_index,
            key="session_selector",
            help="Select a previous chat session to load."
        )

        # Find the selected session ID based on the display name
        selected_session_id = next(
            (s["id"] for s in session_options if s["display"] == selected_session_display),
            None
        )

        # Add logging before the comparison
        logger.debug(f"Widget Check: Current Session ID from State = {current_session_id_from_state}")
        logger.debug(f"Widget Check: Selected Session Display = {selected_session_display}")
        logger.debug(f"Widget Check: Derived Selected Session ID = {selected_session_id}")

        # Use current_session_id_from_state for the comparison
        if selected_session_id and current_session_id_from_state != selected_session_id:
            logger.info(
                f"---*--- Triggering session load from widget. Current (from state): {current_session_id_from_state}, Selected: {selected_session_id} ---*---" # Updated log
            )
            # Re-initialize team with the selected session ID and current config
            st.session_state["llm_os_team"] = get_llm_os(
                model_id=config.get("model_id"),
                calculator=config.get("calculator"),
                ddg_search=config.get("ddg_search"),
                file_tools=config.get("file_tools"),
                shell_tools=config.get("shell_tools"),
                data_analyst=config.get("data_analyst"),
                python_agent_enable=config.get("python_agent_enable"),
                research_agent_enable=config.get("research_agent_enable"),
                investment_agent_enable=config.get("investment_agent_enable"),
                user_id=config.get("user_id"),
                session_id=selected_session_id,
                debug_mode=config.get("debug_mode", True)
            )
            # Update session ID in state
            st.session_state["llm_os_session_id"] = selected_session_id
            # Clear messages to load history from the new team
            st.session_state["messages"] = []
            # st.rerun() # Comment out rerun to break potential loop

    except Exception as e:
        logger.error(f"Error loading/displaying sessions: {e}")
        st.sidebar.error("Failed to load sessions.")


def rename_session_widget(agent_or_team: Any) -> None:
    """Allow renaming the current agent/team session"""
    # Ensure storage is available
    if not hasattr(agent_or_team, 'storage') or not agent_or_team.storage:
        return # Don't show if storage isn't used

    container = st.sidebar.container()
    session_row = container.columns([3, 1], vertical_alignment="bottom")

    if "session_edit_mode" not in st.session_state:
        st.session_state.session_edit_mode = False

    with session_row[0]:
        # Get current name/id (assuming team object has these via storage)
        current_session_id = agent_or_team.session_id
        current_name = agent_or_team.session_name if hasattr(agent_or_team, 'session_name') and agent_or_team.session_name else current_session_id

        if st.session_state.session_edit_mode:
            new_session_name = st.text_input(
                "Edit Session Name:",
                value=current_name,
                key="session_name_input",
                label_visibility="collapsed",
            )
        else:
            st.markdown(f"**Session:** `{current_name}`")

    with session_row[1]:
        if st.session_state.session_edit_mode:
            if st.button("💾", key="save_session_name", help="Save session name"):
                if new_session_name and new_session_name != current_name:
                    try:
                        # Use storage object to rename
                        storage = agent_or_team.storage
                        storage.rename_session(current_session_id, new_session_name) # Assumes rename_session method exists
                        st.session_state.session_edit_mode = False
                        st.toast(f"✅ Session renamed to '{new_session_name}'", icon="📝")
                        st.rerun()
                    except AttributeError:
                        logger.error(f"Storage object {type(storage)} does not have a rename_session method.")
                        st.toast("❌ Renaming not supported by storage.", icon="🔥")
                        st.session_state.session_edit_mode = False # Exit edit mode on error
                    except Exception as e:
                        logger.error(f"Error renaming session: {e}")
                        st.toast(f"❌ Error renaming session: {e}", icon="🔥")
                else:
                    st.session_state.session_edit_mode = False
                    st.rerun()
        else:
            if st.button("✏️", key="edit_session_name", help="Rename session"):
                st.session_state.session_edit_mode = True
                st.rerun()


# ---- END SESSION MANAGEMENT WIDGETS ----
