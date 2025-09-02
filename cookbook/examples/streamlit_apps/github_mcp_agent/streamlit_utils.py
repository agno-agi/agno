from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st


def add_message(
    role: str, content: str, tool_calls: Optional[List[Dict[str, Any]]] = None
) -> None:
    """Add a message to the session state."""
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    message = {"role": role, "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls

    st.session_state["messages"].append(message)


def display_chat_messages():
    """Display chat messages in the UI."""
    if "messages" not in st.session_state:
        return

    for message in st.session_state["messages"]:
        role = message.get("role", "user")
        content = message.get("content", "")
        
        if role == "user":
            with st.chat_message("user"):
                st.markdown(content)
        elif role == "agent":
            with st.chat_message("assistant"):
                st.markdown(content)


def display_response(response_container, response_content: str):
    """Display agent response in a container."""
    with response_container:
        st.markdown("### 🤖 Agent Response")
        st.markdown(response_content)


def export_chat_history():
    """Export chat history as markdown."""
    if "messages" not in st.session_state or not st.session_state["messages"]:
        return ""
    
    chat_text = "# GitHub MCP Agent - Chat History\n\n"
    chat_text += f"**Exported on:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    for msg in st.session_state["messages"]:
        role = "🤖 Assistant" if msg["role"] == "agent" else "👤 User"
        chat_text += f"### {role}\n{msg['content']}\n\n"
        
        if msg.get("tool_calls"):
            chat_text += "#### Tools Used:\n"
            for tool in msg["tool_calls"]:
                tool_name = tool.get("name", "GitHub MCP Tool")
                chat_text += f"- {tool_name}\n"
            chat_text += "\n"
    
    return chat_text


def reset_session_state():
    """Reset the session state."""
    keys_to_reset = ["messages", "agent", "session_id"]
    for key in keys_to_reset:
        if key in st.session_state:
            del st.session_state[key]


def about_section():
    """Display about section in sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.markdown("""
    This GitHub MCP Agent uses the Model Context Protocol to interact with GitHub repositories in real-time.

    **Features:**
    - Natural language queries
    - Real-time GitHub API access
    - Issues and PR analysis
    - Repository insights

    Built with:
    - 🚀 Agno
    - 💫 Streamlit
    - 🔗 Model Context Protocol
    """)


# Common CSS styles - simplified to match golden example
COMMON_CSS = """
    <style>
    .main-title {
        text-align: center;
        background: linear-gradient(45deg, #4285f4, #34a853);
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
