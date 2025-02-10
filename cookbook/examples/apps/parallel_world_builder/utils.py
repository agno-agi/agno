from typing import Any, Dict, List, Optional

import streamlit as st
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


def restart_agent():
    """Reset the agent and clear chat history"""
    logger.debug("---*--- Restarting agent ---*---")
    st.session_state["world_builder"] = None
    st.session_state["world"] = None
    st.session_state["messages"] = []
    st.rerun()


def sidebar_widget() -> None:
    """Display a sidebar with sample user queries"""
    with st.sidebar:
        # Basic Information
        st.markdown("#### Sample Queries")
        if st.button(
            "An advanced futuristic city on distant planet with only 1 island. Dark history. Population 1 trillion."
        ):
            add_message(
                "user",
                "An advanced futuristic city on distant planet with only 1 island. Dark history. Population 1 trillion.",
            )
        if st.button("A medieval fantasy world with dragons, castles, and knights."):
            add_message(
                "user",
                "A medieval fantasy world with dragons, castles, and knights.",
            )
        if st.button(
            "A post-apocalyptic world with a nuclear wasteland and a small community living in a dome."
        ):
            add_message(
                "user",
                "A post-apocalyptic world with a nuclear wasteland and a small community living in a dome.",
            )
        if st.button(
            "A world with a mix of ancient and modern civilizations, where magic and technology coexist."
        ):
            add_message(
                "user",
                "A world with a mix of ancient and modern civilizations, where magic and technology coexist.",
            )

        st.markdown("---")
        if st.button("🔄 New World"):
            restart_agent()


def display_tool_calls(tool_calls_container, tools):
    """Display tool calls in a streamlit container with expandable sections.

    Args:
        tool_calls_container: Streamlit container to display the tool calls
        tools: List of tool call dictionaries containing name, args, content, and metrics
    """
    with tool_calls_container.container():
        for tool_call in tools:
            _tool_name = tool_call.get("tool_name")
            _tool_args = tool_call.get("tool_args")
            _content = tool_call.get("content")
            _metrics = tool_call.get("metrics")

            with st.expander(
                f"🛠️ {_tool_name.replace('_', ' ').title()}", expanded=False
            ):
                if isinstance(_tool_args, dict) and "query" in _tool_args:
                    st.code(_tool_args["query"], language="sql")

                if _tool_args and _tool_args != {"query": None}:
                    st.markdown("**Arguments:**")
                    st.json(_tool_args)

                if _content:
                    st.markdown("**Results:**")
                    try:
                        st.json(_content)
                    except Exception as e:
                        st.markdown(_content)

                if _metrics:
                    st.markdown("**Metrics:**")
                    st.json(_metrics)
