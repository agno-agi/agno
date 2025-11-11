import nest_asyncio
import streamlit as st
from agents import get_github_agent
from agno.utils.streamlit import (
    COMMON_CSS,
    MODELS,
    about_section,
    add_message,
    display_chat_messages,
    display_response,
    export_chat_history,
    initialize_agent,
    reset_session_state,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="GitHub Repository Analyzer",
    page_icon="👨‍💻",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def restart_agent(model_id: str = None):
    target_model = model_id or st.session_state.get("current_model", MODELS[0])

    new_agent = get_github_agent(model_id=target_model, session_id=None)

    st.session_state["agent"] = new_agent
    st.session_state["session_id"] = new_agent.session_id
    st.session_state["messages"] = []
    st.session_state["current_model"] = target_model
    st.session_state["is_new_session"] = True


def on_model_change():
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        if selected_model in MODELS:
            new_model_id = selected_model
            current_model = st.session_state.get("current_model")

            if current_model and current_model != new_model_id:
                try:
                    st.session_state["is_loading_session"] = False
                    # Start new chat
                    restart_agent(model_id=new_model_id)

                except Exception as e:
                    st.sidebar.error(f"Error switching to {selected_model}: {str(e)}")
        else:
            st.sidebar.error(f"Unknown model: {selected_model}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>GitHub Repository Analyzer</h1>", unsafe_allow_html=True
    )
    st.markdown(
        "<p class='subtitle'>Your intelligent GitHub analysis assistant powered by Agno</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    selected_model = st.sidebar.selectbox(
        "Select Model",
        options=MODELS,
        index=0,
        key="model_selector",
        on_change=on_model_change,
    )

    ####################################################################
    # Initialize Agent and Session
    ####################################################################
    github_analyzer_agent = initialize_agent(selected_model, get_github_agent)
    reset_session_state(github_analyzer_agent)

    if prompt := st.chat_input("👨‍💻 Ask me about GitHub repositories!"):
        add_message("user", prompt)

    ####################################################################
    # GitHub Configuration
    ####################################################################
    st.sidebar.markdown("#### 🔑 Configuration")

    github_token = st.sidebar.text_input(
        "GitHub Personal Access Token",
        type="password",
        help="Optional: Provides access to private repositories and higher rate limits",
        placeholder="ghp_xxxxxxxxxxxx",
    )

    if github_token:
        st.sidebar.success("✅ GitHub token configured")
    else:
        st.sidebar.info("💡 Add your GitHub token for enhanced access")

    st.sidebar.markdown(
        "[How to create a GitHub PAT?](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic)"
    )

    ###############################################################
    # Sample Questions
    ###############################################################
    st.sidebar.markdown("#### ❓ Sample Questions")

    if st.sidebar.button("📊 Analyze agno-agi/agno"):
        add_message(
            "user",
            "Analyze the repository 'agno-agi/agno' - show me the structure, main languages, and recent activity",
        )

    if st.sidebar.button("🔍 Latest Issues"):
        add_message(
            "user",
            "Show me the latest issues in 'microsoft/vscode'",
        )

    if st.sidebar.button("📝 Review Latest PR"):
        add_message(
            "user",
            "Find and review the latest pull request in 'facebook/react'",
        )

    if st.sidebar.button("📚 Repository Stats"):
        add_message(
            "user",
            "What are the repository statistics for 'tensorflow/tensorflow'?",
        )

    ###############################################################
    # Utility buttons
    ###############################################################
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
            session_id = st.session_state.get("session_id")
            if session_id:
                try:
                    session_name = github_analyzer_agent.get_session_name()
                    if session_name:
                        filename = f"github_analyzer_chat_{session_name}.md"
                    else:
                        filename = f"github_analyzer_chat_{session_id}.md"
                except Exception:
                    filename = f"github_analyzer_chat_{session_id}.md"
            else:
                filename = "github_analyzer_chat_new.md"

            if st.sidebar.download_button(
                "💾 Export Chat",
                export_chat_history("GitHub Repository Analyzer"),
                file_name=filename,
                mime="text/markdown",
                use_container_width=True,
                help=f"Export {len(st.session_state['messages'])} messages",
            ):
                st.sidebar.success("Chat history exported!")
        else:
            st.sidebar.button(
                "💾 Export Chat",
                disabled=True,
                use_container_width=True,
                help="No messages to export",
            )

    ####################################################################
    # Display Chat Messages
    ####################################################################
    display_chat_messages()

    ####################################################################
    # Generate response for user message
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )
    if last_message and last_message.get("role") == "user":
        question = last_message["content"]
        display_response(github_analyzer_agent, question)

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This GitHub Repository Analyzer helps you analyze code repositories, review pull requests, and understand project structures using natural language queries."
    )


if __name__ == "__main__":
    main()
