import json
from typing import Any, Dict, List, Optional

import streamlit as st
from agno.utils.log import logger


def is_json(myjson: str) -> bool:
    """Check if a string is valid JSON"""
    try:
        json.loads(myjson)
    except (ValueError, TypeError):
        return False
    return True


def add_message(
    role: str,
    content: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Safely add a message to the session state"""
    if "messages" not in st.session_state or not isinstance(
        st.session_state["messages"], list
    ):
        st.session_state["messages"] = []
    st.session_state["messages"].append(
        {"role": role, "content": content, "tool_calls": tool_calls}
    )


def display_tool_calls(tool_calls_container: Any, tools: List[Dict[str, Any]]) -> None:
    """Display tool calls in a Streamlit container"""
    try:
        with tool_calls_container.container():
            for tool_call in tools:
                tool_name = tool_call.get("tool_name", "Unknown Tool")
                tool_args = tool_call.get("tool_args", {})
                content = tool_call.get("content")
                metrics = tool_call.get("metrics")

                execution_time_str = "N/A"
                if metrics is not None and hasattr(metrics, "time"):
                    t = metrics.time
                    execution_time_str = f"{t:.4f}s" if t else execution_time_str

                with st.expander(
                    f"🛠️ {tool_name.replace('_', ' ').title()} ({execution_time_str})",
                    expanded=False,
                ):
                    if isinstance(tool_args, dict) and "query" in tool_args:
                        st.code(tool_args["query"], language="sql")
                    if tool_args and tool_args != {"query": None}:
                        st.markdown("**Arguments:**")
                        st.json(tool_args)
                    if content is not None and is_json(content):
                        st.markdown("**Results:**")
                        st.json(content)
    except Exception as e:
        logger.error(f"Error displaying tool calls: {e}")
        tool_calls_container.error("Failed to display tool results")


def about_widget() -> None:
    """Display an about section in the sidebar"""
    with st.sidebar:
        st.markdown("### About Recipe Generator ✨")
        st.markdown(
            "Recipe Image Generator powered by Agno. Upload or use default recipe PDF and get step-by-step visual cooking instructions."
        )


# Added example inputs for recipe generation
def example_inputs() -> None:
    """Show example recipe inputs on the sidebar."""
    with st.sidebar:
        st.markdown("#### :sparkles: Try an example recipe")
        if st.button("Recipe for Pad Thai"):
            add_message("user", "Recipe for Pad Thai")
        if st.button("Recipe for Som Tum"):
            add_message("user", "Recipe for Som Tum / Papaya Salad")
        if st.button("Recipe for Massaman Curry"):
            add_message("user", "Recipe for Massaman Curry / Massaman Gai")
        if st.button("Recipe for Tom Kha Gai"):
            add_message("user", "Recipe for Tom Kha Gai")


CUSTOM_CSS = """
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
.chat-container {
    border-radius: 15px;
    padding: 1em;
    margin: 1em 0;
    background-color: #f5f5f5;
}
.success-message {
    background-color: #d4edda;
    color: #155724;
}
.error-message {
    background-color: #f8d7da;
    color: #721c24;
}
@media (prefers-color-scheme: dark) {
    .chat-container { background-color: #2b2b2b; }
}
</style>
"""
