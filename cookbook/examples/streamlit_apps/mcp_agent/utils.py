import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
from agents import get_mcp_agent
from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.utils.log import logger
from mcp_client import MCPServerConfig


def get_selected_model() -> str:
    """Return the selected model identifier based on user selection in the sidebar.

    Returns:
        str: The model identifier string in the format 'provider:model-name'
    """
    model_options = {
        "gpt-4o": "openai:gpt-4o",
        "gpt-4.5": "openai:gpt-4.5-preview",
        "gpt-4o-mini": "openai:gpt-4o-mini",
        "o3-mini": "openai:o3-mini",
        "sonnet-3-7": "anthropic:claude-3-7-sonnet-latest",
        "sonnet-3.7-thinking": "anthropic:claude-3-7-sonnet-thinking",
        "gemini-flash": "gemini:gemini-2.0-flash",
        "gemini-pro": "gemini:gemini-2.0-pro-exp-02-05",
        "llama-3.3-70b": "groq:llama-3.3-70b-versatile",
    }
    st.sidebar.markdown("#### :sparkles: Select a model")
    selected_model = st.sidebar.selectbox(
        "Select a model",
        options=list(model_options.keys()),
        index=list(model_options.keys()).index("gpt-4o"),
        key="selected_model",
        label_visibility="collapsed",
    )
    return model_options[selected_model]


def get_num_history_responses() -> int:
    """Return the number of messages from history to send to the LLM.

    Returns:
        int: The number of messages from history to include
    """
    num_history = st.sidebar.slider(
        "Number of previous messages to include",
        min_value=1,
        max_value=20,
        value=5,
        step=1,
        help="Controls how many previous messages are sent to the LLM for context",
    )
    return num_history


def get_mcp_server_config() -> Optional[MCPServerConfig]:
    """Get a single MCP server config to add to the agent.

    Returns:
        Optional[MCPServerConfig]: A single MCP server config, or None if none selected.
    """
    with st.sidebar:
        st.markdown("#### 🛠️ Select MCP Tool")

        # Use radio button for single selection
        selected_tool = st.radio(
            "Select a tool to use:",
            options=["GitHub", "Filesystem"],
            key="selected_mcp_tool",
            label_visibility="collapsed",
        )

        if selected_tool == "GitHub":
            github_token_from_env = os.getenv("GITHUB_TOKEN")
            github_token = st.text_input(
                "GitHub Token",
                type="password",
                help="Create a token with repo scope at github.com/settings/tokens",
                value=github_token_from_env,
            )
            if github_token:
                os.environ["GITHUB_TOKEN"] = github_token
                return MCPServerConfig(
                    id="github",
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-github"],
                    env_vars=["GITHUB_TOKEN"],
                )
            else:
                st.error("GitHub Token is required to use GitHub MCP Tools")

        elif selected_tool == "Filesystem":
            # Get the repository root
            cwd = Path(__file__).parent
            repo_root = cwd.parent.parent.parent.parent.resolve()
            st.info(f"Repository path: {repo_root}")
            return MCPServerConfig(
                id="filesystem",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem"]
                + [str(repo_root)],
            )

    return None


def add_message(
    role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None
) -> None:
    """Safely add a message to the session state."""
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
    if not tools:
        return

    try:
        with tool_calls_container.container():
            for tool_call in tools:
                tool_name = tool_call.get("tool_name", "Unknown Tool")
                tool_args = tool_call.get("tool_args", {})
                content = tool_call.get("content")
                metrics = tool_call.get("metrics", {})

                # Add timing information
                execution_time_str = "N/A"
                if metrics and isinstance(metrics, dict):
                    execution_time = metrics.get("time")
                    if execution_time is None:
                        execution_time_str = "N/A"
                    else:
                        execution_time_str = f"{execution_time:.2f}s"

                with st.expander(
                    f"🛠️ {tool_name.replace('_', ' ').title()} ({execution_time_str})",
                    expanded=False,
                ):
                    # Show query with syntax highlighting
                    if isinstance(tool_args, dict) and tool_args.get("query"):
                        st.code(tool_args["query"], language="sql")

                    # Display arguments in a more readable format
                    if tool_args and tool_args != {"query": None}:
                        st.markdown("**Arguments:**")
                        st.json(tool_args)

                    if content:
                        st.markdown("**Results:**")
                        try:
                            # Check if content is already a dictionary or can be parsed as JSON
                            if isinstance(content, dict) or (
                                isinstance(content, str)
                                and content.strip().startswith(("{", "["))
                            ):
                                st.json(content)
                            else:
                                # If not JSON, show as markdown
                                st.markdown(content)
                        except Exception:
                            # If JSON display fails, show as markdown
                            st.markdown(content)

    except Exception as e:
        logger.error(f"Error displaying tool calls: {str(e)}")
        tool_calls_container.error(f"Failed to display tool results: {str(e)}")


def example_inputs(server_id: str) -> None:
    """Show example inputs for the MCP Agent."""
    with st.sidebar:
        st.markdown("#### :thinking_face: Try me!")
        if st.button("Who are you?"):
            add_message(
                "user",
                "Who are you?",
            )
        if st.button("What is your purpose?"):
            add_message(
                "user",
                "What is your purpose?",
            )
        # Common examples for all server types
        if st.button("What can you help me with?"):
            add_message(
                "user",
                "What can you help me with?",
            )
        if st.button("How do MCP tools work?"):
            add_message(
                "user",
                "How do MCP tools work? Explain the Model Context Protocol.",
            )

        # Server-specific examples
        if server_id == "github":
            if st.button("Tell me about Agno"):
                add_message(
                    "user",
                    "Tell me about Agno. Github repo: https://github.com/agno-agi/agno. You can read the README for more information.",
                )
            if st.button("Find issues in the Agno repo"):
                add_message(
                    "user",
                    "Find open issues in the agno-agi/agno repository and summarize the top 3 most recent ones.",
                )
        elif server_id == "filesystem":
            if st.button("Summarize the README"):
                add_message(
                    "user",
                    "If there is a README file in the current directory, summarize it.",
                )


def session_selector_widget(
    agent: Agent,
    model_str: str,
    num_history_responses: int,
    mcp_tools: List[MCPTools],
    mcp_server_ids: List[str],
) -> None:
    """Display a session selector in the sidebar, if a new session is selected, the agent is restarted with the new session."""

    if not agent.storage:
        return

    try:
        # -*- Get all agent sessions.
        agent_sessions = agent.storage.get_all_sessions()

        if not agent_sessions:
            st.sidebar.info("No saved sessions found.")
            return

        # -*- Get session names if available, otherwise use IDs.
        sessions_list = []
        for session in agent_sessions:
            session_id = session.session_id
            session_name = (
                session.session_data.get("session_name", None)
                if session.session_data
                else None
            )
            display_name = session_name if session_name else session_id
            sessions_list.append({"id": session_id, "display_name": display_name})

        # -*- Display session selector.
        st.sidebar.markdown("#### 💬 Session")
        selected_session = st.sidebar.selectbox(
            "Session",
            options=[s["display_name"] for s in sessions_list],
            key="session_selector",
            label_visibility="collapsed",
        )
        # -*- Find the selected session ID.
        selected_session_id = next(
            s["id"] for s in sessions_list if s["display_name"] == selected_session
        )
        # -*- Update the selected session if it has changed.
        if st.session_state.get("mcp_agent_session_id") != selected_session_id:
            logger.info(
                f"---*--- Loading {model_str} run: {selected_session_id} ---*---"
            )
            st.session_state["mcp_agent"] = get_mcp_agent(
                model_str=model_str,
                session_id=selected_session_id,
                num_history_responses=num_history_responses,
                mcp_tools=mcp_tools,
                mcp_server_ids=mcp_server_ids,
            )
            st.rerun()

        # -*- Show the rename session widget.
        container = st.sidebar.container()
        session_row = container.columns([3, 1], vertical_alignment="center")

        # -*- Initialize session_edit_mode if needed.
        if "session_edit_mode" not in st.session_state:
            st.session_state.session_edit_mode = False

        # -*- Show the session name.
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

        # -*- Show the rename session button.
        with session_row[1]:
            if st.session_state.session_edit_mode:
                if st.button("✓", key="save_session_name", type="primary"):
                    if new_session_name:
                        agent.rename_session(new_session_name)
                        st.session_state.session_edit_mode = False
                        container.success("Renamed!")
                        # Trigger a rerun to refresh the sessions list
                        st.rerun()
            else:
                if st.button("✎", key="edit_session_name"):
                    st.session_state.session_edit_mode = True
    except Exception as e:
        logger.error(f"Error in session selector: {str(e)}")
        st.sidebar.error("Failed to load sessions")


def restart_agent():
    """Reset the agent and clear chat history."""
    logger.debug("---*--- Restarting agent ---*---")
    st.session_state["mcp_agent"] = None
    st.session_state["mcp_agent_session_id"] = None
    st.session_state["messages"] = []
    st.rerun()


def export_chat_history():
    """Export chat history as markdown.

    Returns:
        str: Formatted markdown string of the chat history
    """
    if "messages" not in st.session_state or not st.session_state["messages"]:
        return "# MCP Agent - Chat History\n\nNo messages to export."

    chat_text = "# MCP Agent - Chat History\n\n"
    for msg in st.session_state["messages"]:
        role_label = "🤖 Assistant" if msg["role"] == "assistant" else "👤 User"
        chat_text += f"### {role_label}\n{msg['content']}\n\n"

        # Include tool calls if present
        if msg.get("tool_calls"):
            chat_text += "#### Tool Calls:\n"
            for i, tool_call in enumerate(msg["tool_calls"]):
                tool_name = tool_call.get("name", "Unknown Tool")
                chat_text += f"**{i + 1}. {tool_name}**\n\n"
                if "arguments" in tool_call:
                    chat_text += (
                        f"Arguments: ```json\n{tool_call['arguments']}\n```\n\n"
                    )
                if "content" in tool_call:
                    chat_text += f"Results: ```\n{tool_call['content']}\n```\n\n"

    return chat_text


def utilities_widget(agent: Agent) -> None:
    """Display a utilities widget in the sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🔄 New Chat"):
            restart_agent()
    with col2:
        fn = "mcp_agent_chat_history.md"
        if "mcp_agent_session_id" in st.session_state:
            fn = f"mcp_agent_{st.session_state.mcp_agent_session_id}.md"
        if st.download_button(
            ":file_folder: Export Chat",
            export_chat_history(),
            file_name=fn,
            mime="text/markdown",
        ):
            st.sidebar.success("Chat history exported!")
    if agent is not None and agent.knowledge is not None:
        if st.sidebar.button("📚 Load Knowledge"):
            agent.knowledge.load()
            st.sidebar.success("Knowledge loaded!")


def about_widget() -> None:
    """Display an about section in the sidebar."""
    st.sidebar.markdown("#### ℹ️ About")
    st.sidebar.markdown(
        """
        The Universal MCP Agent lets you interact with MCP servers using a chat interface.

        Built with:
        - 🚀 [Agno](https://github.com/agno-agi/agno)
        - 💫 [Streamlit](https://streamlit.io)
        """
    )


CUSTOM_CSS = """
    <style>
    /* Main Styles */
    .main-title {
        text-align: center;
        background: linear-gradient(45deg, #FF4B2B, #FF416C);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
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


# Add a function to handle theme customization
def apply_theme():
    """Apply custom theme settings to the Streamlit app."""
    # Set page configuration
    st.set_page_config(
        page_title="Universal MCP Agent",
        page_icon=":crystal_ball:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Apply custom CSS
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
