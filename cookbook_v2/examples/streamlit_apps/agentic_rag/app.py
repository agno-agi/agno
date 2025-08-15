import os
import tempfile

import nest_asyncio
import streamlit as st
from agentic_rag import get_agentic_rag_agent
from streamlit_utils import (
    COMMON_CSS,
    add_message,
    display_chat_messages,
    export_chat_history,
    display_response,
    initialize_agent,
    knowledge_base_info_widget,
    reset_session_state,
    session_selector_widget,
)
from utils import about_section

nest_asyncio.apply()
st.set_page_config(
    page_title="Agentic RAG",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def restart_agent():
    """Reset the agent"""
    current_model = st.session_state.get("current_model", "openai:gpt-4o")
    new_agent = get_agentic_rag_agent(model_id=current_model, debug_mode=True)
    new_agent.new_session()
    
    st.session_state["agent"] = new_agent
    st.session_state["session_id"] = new_agent.session_id
    st.session_state["messages"] = []
    
    st.rerun()


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>Agentic RAG </h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Your intelligent research assistant powered by Agno</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    model_options = {
        "gpt-5": "openai:gpt-5",
        "o3-mini": "openai:o3-mini",
        "kimi-k2-instruct": "groq:moonshotai/kimi-k2-instruct",
        "gpt-4o": "openai:gpt-4o",
        "gemini-2.5-pro": "google:gemini-2.5-pro",
        "claude-4-sonnet": "anthropic:claude-sonnet-4-0",
    }
    selected_model = st.sidebar.selectbox(
        "Select a model",
        options=list(model_options.keys()),
        index=0,
        key="model_selector",
    )
    model_id = model_options[selected_model]

    ####################################################################
    # Initialize Agent and Session
    ####################################################################
    agentic_rag_agent = initialize_agent(model_id, get_agentic_rag_agent)
    reset_session_state(agentic_rag_agent)

    if prompt := st.chat_input("👋 Ask me anything!"):
        add_message("user", prompt)

    ####################################################################
    # Document Management
    ####################################################################
    st.sidebar.markdown("#### 📚 Document Management")
    st.sidebar.metric(
        "Documents Loaded", agentic_rag_agent.knowledge.vector_db.get_count()
    )

    # URL input
    input_url = st.sidebar.text_input("Add URL to Knowledge Base")
    if input_url and not prompt:
        alert = st.sidebar.info("Processing URL...", icon="ℹ️")
        try:
            agentic_rag_agent.knowledge.add_content_sync(
                name=f"URL: {input_url}",
                url=input_url,
                description=f"Content from {input_url}",
            )
            st.sidebar.success("URL added to knowledge base")
        except Exception as e:
            st.sidebar.error(f"Error processing URL: {str(e)}")
        finally:
            alert.empty()

    # File upload
    uploaded_file = st.sidebar.file_uploader(
        "Add a Document (.pdf, .csv, or .txt)", key="file_upload"
    )
    if uploaded_file and not prompt:
        alert = st.sidebar.info("Processing document...", icon="ℹ️")
        try:
            with tempfile.NamedTemporaryFile(
                suffix=f".{uploaded_file.name.split('.')[-1]}", delete=False
            ) as tmp_file:
                tmp_file.write(uploaded_file.read())
                tmp_path = tmp_file.name

            agentic_rag_agent.knowledge.add_content_sync(
                name=uploaded_file.name,
                path=tmp_path,
                description=f"Uploaded file: {uploaded_file.name}",
            )

            os.unlink(tmp_path)
            st.sidebar.success(f"{uploaded_file.name} added to knowledge base")
        except Exception as e:
            st.sidebar.error(f"Error processing file: {str(e)}")
        finally:
            alert.empty()

    if st.sidebar.button("Clear Knowledge Base"):
        if agentic_rag_agent.knowledge.vector_db:
            agentic_rag_agent.knowledge.vector_db.delete()
        st.sidebar.success("Knowledge base cleared")

    ###############################################################
    # Sample Question
    ###############################################################
    st.sidebar.markdown("#### ❓ Sample Questions")
    if st.sidebar.button("📝 Summarize"):
        add_message(
            "user",
            "Can you summarize what is currently in the knowledge base (use `search_knowledge_base` tool)?",
        )

    ###############################################################
    # Utility buttons
    ###############################################################
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns([1, 1])
    with col1:
        if st.sidebar.button("🔄 New Chat", use_container_width=True):
            restart_agent()
    with col2:
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            session_id = st.session_state.get("session_id")
            if (
                session_id
                and hasattr(agentic_rag_agent, "session_name")
                and agentic_rag_agent.session_name
            ):
                filename = f"agentic_rag_chat_{agentic_rag_agent.session_name}.md"
            elif session_id:
                filename = f"agentic_rag_chat_{session_id}.md"
            else:
                filename = "agentic_rag_chat_new.md"

            if st.sidebar.download_button(
                "💾 Export Chat",
                export_chat_history("Agentic RAG"),
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
        display_response(agentic_rag_agent, question)

    ####################################################################
    # Session management widgets 
    ####################################################################
    session_selector_widget(agentic_rag_agent, model_id, get_agentic_rag_agent)

    # Knowledge base info
    knowledge_base_info_widget(agentic_rag_agent)

   ####################################################################
    # About section
    ####################################################################
    about_section()

main()
