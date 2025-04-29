import json
from typing import Any, Dict, List, Optional

import streamlit as st
from agno.utils.log import log_debug, log_error, log_info


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


def sidebar_widget() -> None:
    """Renders the sidebar for configuration and example queries."""
    with st.sidebar:
        # Configuration
        st.header("Configuration")

        st.markdown("**GitHub Token**")
        token_input = st.text_input(
            "Enter your GitHub Personal Access Token (required for most queries):",
            type="password",
            key="github_token_input",
            value=st.session_state.get("github_token", ""),
            help="Allows the agent to access GitHub API, including your private/org data.",
        )
        st.markdown(
            "[How to create a GitHub PAT?](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic)",
            unsafe_allow_html=True,
        )

        # Update session state if token input changes
        current_token_in_state = st.session_state.get("github_token")
        if token_input != current_token_in_state and (
            token_input or current_token_in_state is not None
        ):
            st.session_state.github_token = token_input if token_input else None
            log_info(
                f"GitHub token updated via sidebar input {'(cleared)' if not token_input else ''}."
            )
            st.session_state.github_agent = None
            st.rerun()

        st.markdown("---")

        st.markdown("#### 🏆 Sample Queries")
        if st.button("📋 Summarize 'agno-agi/agno'"):
            # Run this query in the current session
            add_message("user", "Summarize 'agno-agi/agno' repo")
        if st.button("🥇 List my recent repositories"):
            add_message("user", "List my recent repositories")
        if st.button("🏆 List latest issues in 'agno-agi/agno' "):
            add_message("user", "List latest issues in 'agno-agi/agno'")
        if st.button("🥇 List recent PRs in 'agno-agi/agno'"):
            add_message("user", "List recent PRs in 'agno-agi/agno' repo")
        # Chat controls
        st.header("Chat")
        if st.button("🆕 New Chat"):
            # Use restart logic to clear everything and rerun
            restart_agent()


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


def is_json(myjson):
    """Check if a string is valid JSON"""
    try:
        json.loads(myjson)
    except (ValueError, TypeError):
        return False
    return True


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
                    log_error(f"Error displaying tool calls: {str(e)}")
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
                            log_debug(f"Skipped tool call content: {e}")
    except Exception as e:
        log_error(f"Error displaying tool calls: {str(e)}")
        tool_calls_container.error("Failed to display tool results")


def restart_agent():
    """Reset the agent and clear chat history"""
    log_debug("---*--- Restarting agent ---*---")
    st.session_state["sql_agent"] = None
    st.session_state["sql_agent_session_id"] = None
    st.session_state["messages"] = []
    st.session_state["github_agent"] = None
    st.rerun()


# Keep only necessary CSS styles
CUSTOM_CSS = """
<style>
    .main-header {
        font-size: 2.5rem;
        margin-bottom: 1rem;
        color: #0366d6;
        font-weight: 600;
    }
    .sub-header {
        font-size: 1.5rem;
        margin-top: 1rem;
        margin-bottom: 0.5rem;
        color: #2f363d;
        font-weight: 500;
    }
    .metric-card {
        background-color: #f6f8fa;
        border-radius: 8px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        border-left: 5px solid #0366d6;
    }
    .pr-card {
        background-color: #f1f8ff;
        border-radius: 8px;
        padding: 1.2rem;
        margin-bottom: 1.2rem;
        border-left: 5px solid #6f42c1;
    }
</style>
"""
