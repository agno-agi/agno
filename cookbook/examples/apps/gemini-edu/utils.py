"""
Utility functions for Gemini Tutor
"""

import json
from typing import Any, Dict, List, Optional

import streamlit as st
from agno.utils.log import logger


def add_message(
    role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None, **kwargs
) -> None:
    """
    Safely add a message to the session state.

    Args:
        role: The role of the message sender (user/assistant)
        content: The text content of the message
        tool_calls: Optional tool calls to include
        **kwargs: Additional message attributes (image, audio, video paths)
    """
    if "messages" not in st.session_state or not isinstance(
        st.session_state["messages"], list
    ):
        st.session_state["messages"] = []

    message = {"role": role, "content": content, "tool_calls": tool_calls}

    # Add any additional attributes like image, audio, or video paths
    for key, value in kwargs.items():
        message[key] = value

    st.session_state["messages"].append(message)


def display_tool_calls(container: Any, tool_calls: List[Dict[str, Any]]) -> None:
    """
    Display tool calls in a formatted way.

    Args:
        container: Streamlit container to display the tool calls
        tool_calls: List of tool call dictionaries
    """
    if not tool_calls:
        return

    with container:
        st.markdown("**Tool Calls:**")

        for i, tool_call in enumerate(tool_calls):
            # Format the tool call name
            tool_name = tool_call.get("name", "Unknown Tool")

            # Format the args as pretty JSON
            args = tool_call.get("arguments", {})
            formatted_args = json.dumps(args, indent=2)

            expander_label = f"📋 Tool Call {i + 1}: {tool_name}"
            with st.expander(expander_label, expanded=False):
                st.code(formatted_args, language="json")


def display_grounding_metadata(grounding_metadata: Any) -> None:
    """
    Display search grounding metadata if available.

    Args:
        grounding_metadata: Grounding metadata from agent response
    """
    if not grounding_metadata:
        return

    try:
        st.markdown("---")
        st.markdown("### 🌐 Sources")

        # Display grounding sources if available
        if (
            hasattr(grounding_metadata, "search_entry_point")
            and grounding_metadata.search_entry_point
        ):
            if hasattr(grounding_metadata.search_entry_point, "rendered_content"):
                grounding_content = (
                    grounding_metadata.search_entry_point.rendered_content
                )
                st.markdown(grounding_content)

        # Display search suggestions if available
        if (
            hasattr(grounding_metadata, "search_suggestions")
            and grounding_metadata.search_suggestions
        ):
            st.markdown("### 🔍 Related Searches")
            for suggestion in grounding_metadata.search_suggestions:
                st.markdown(f"- {suggestion}")
    except Exception as e:
        logger.warning(f"Error displaying grounding metadata: {str(e)}")
