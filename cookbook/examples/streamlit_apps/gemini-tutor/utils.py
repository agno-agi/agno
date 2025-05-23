"""
Utility functions for Gemini Tutor
"""

import json
from typing import Any, Dict, List, Optional

import streamlit as st
from agno.models.message import Citations
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


def display_grounding_metadata(citations: Optional[Citations]) -> None:
    """
    Display search grounding metadata (sources) if available.

    Args:
        citations: Citations object from the agent response chunk or final message.
    """
    # Check if citations object exists and has the 'urls' attribute and it's not empty
    if not citations or not hasattr(citations, "urls") or not citations.urls:
        return

    try:
        st.markdown("---")
        st.markdown("### 🌐 Sources")

        # Display grounding sources from the pre-parsed list
        for citation_url in citations.urls:
            # Ensure url and title exist
            if (
                hasattr(citation_url, "url")
                and citation_url.url
                and hasattr(citation_url, "title")
                and citation_url.title
            ):
                st.markdown(f"- [{citation_url.title}]({citation_url.url})")
            elif (
                hasattr(citation_url, "url") and citation_url.url
            ):  # Fallback if title is missing
                st.markdown(f"- [{citation_url.url}]({citation_url.url})")

        # Optionally, display raw metadata in an expander for debugging if needed
        # if hasattr(citations, 'raw') and citations.raw:
        #     with st.expander("Raw Grounding Metadata (Debug)"):
        #         st.json(citations.raw)

    except Exception as e:
        logger.error(f"Error displaying grounding metadata: {e}", exc_info=True)
        st.warning("Could not display sources.")
