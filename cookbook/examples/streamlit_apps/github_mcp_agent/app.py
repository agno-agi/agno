import asyncio
import os

import streamlit as st
from agents import run_github_agent
from agno.utils.streamlit import (
    COMMON_CSS,
    MODELS,
    about_section,
    add_message,
    display_chat_messages,
    export_chat_history,
)

st.set_page_config(
    page_title="GitHub MCP Agent",
    page_icon="🐙",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def restart_agent():
    """Reset the agent session"""
    st.session_state["messages"] = []
    st.session_state["is_new_session"] = True


def on_model_change():
    """Handle model selection change"""
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        if selected_model in MODELS:
            current_model = st.session_state.get("current_model")
            if current_model and current_model != selected_model:
                st.session_state["current_model"] = selected_model
                restart_agent()
        else:
            st.sidebar.error(f"Unknown model: {selected_model}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>GitHub MCP Agent</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Explore GitHub repositories with natural language using the Model Context Protocol</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Sidebar - Authentication
    ####################################################################
    st.sidebar.header("🔑 Authentication")
    github_token = st.sidebar.text_input(
        "GitHub Token",
        type="password",
        help="Create a token with repo scope at github.com/settings/tokens",
    )

    if github_token:
        os.environ["GITHUB_TOKEN"] = github_token
        st.sidebar.success("✅ GitHub token configured")
    else:
        st.sidebar.warning("⚠️ GitHub token required")

    ####################################################################
    # Model selector
    ####################################################################
    st.sidebar.markdown("---")
    selected_model = st.sidebar.selectbox(
        "Select Model",
        options=MODELS,
        index=0,
        key="model_selector",
        on_change=on_model_change,
    )

    ####################################################################
    # Repository and Query Input
    ####################################################################
    col1, col2 = st.columns([3, 1])

    with col1:
        repo = st.text_input(
            "Repository", value="agno-agi/agno", help="Format: owner/repo", key="repo"
        )

    with col2:
        st.selectbox(
            "Query Type",
            ["Issues", "Pull Requests", "Repository Activity", "Custom"],
            key="query_type",
        )

    ####################################################################
    # Sample Questions
    ####################################################################
    st.sidebar.markdown("#### ❓ Sample Questions")
    if st.sidebar.button("🔍 Issues by label"):
        add_message("user", f"Show me issues by label in {repo}")
    if st.sidebar.button("📝 Recent PRs"):
        add_message("user", f"Show me recent merged PRs in {repo}")
    if st.sidebar.button("📊 Repository health"):
        add_message("user", f"Show repository health metrics for {repo}")

    ####################################################################
    # Utility buttons
    ####################################################################
    st.sidebar.markdown("#### 🛠️ Utilities")

    col1, col2 = st.sidebar.columns([1, 1])
    with col1:
        if st.sidebar.button("🔄 New Chat", use_container_width=True):
            restart_agent()
            st.rerun()

    with col2:
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )
        if has_messages:
            if st.sidebar.download_button(
                "💾 Export Chat",
                export_chat_history("GitHub Agent"),
                file_name=f"github_mcp_chat_{repo.replace('/', '_')}.md",
                mime="text/markdown",
                use_container_width=True,
            ):
                st.sidebar.success("Chat history exported!")

    # About section
    about_section(
        "This GitHub MCP Agent helps you analyze repositories using natural language queries."
    )

    ####################################################################
    # Chat input and processing
    ####################################################################
    if prompt := st.chat_input("Ask me anything about this GitHub repository!"):
        add_message("user", prompt)

    ####################################################################
    # Process user input or button queries
    ####################################################################
    if st.session_state.get("messages"):
        last_message = st.session_state["messages"][-1]
        if last_message["role"] == "user":
            user_query = last_message["content"]

            # Ensure repo is mentioned in query
            if repo and repo not in user_query:
                full_query = f"{user_query} in {repo}"
            else:
                full_query = user_query

            with st.spinner("Analyzing GitHub repository..."):
                try:
                    result = asyncio.run(run_github_agent(full_query, selected_model))
                    add_message("assistant", result)
                except Exception as e:
                    error_msg = f"Error: {str(e)}"
                    add_message("assistant", error_msg)
            st.rerun()

    ####################################################################
    # Display chat messages
    ####################################################################
    display_chat_messages()


if __name__ == "__main__":
    main()
