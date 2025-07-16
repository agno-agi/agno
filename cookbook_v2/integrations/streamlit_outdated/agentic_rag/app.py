import os
import tempfile

import nest_asyncio
import streamlit as st
from agentic_rag import get_agentic_rag_agent
from agno.agent import Agent
from agno.utils.log import logger
from agno.utils.streamlit import (
    COMMON_CSS,
    add_message,
    display_tool_calls,
    export_chat_history,
    knowledge_base_info_widget,
    restart_agent_session,
    session_selector_widget,
)

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
    """Reset the agent and clear chat history"""
    restart_agent_session(
        agent="agent",
        session_id="session_id",
        current_model="current_model",
    )


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
    # Initialize Agent
    ####################################################################
    agent: Agent
    if (
        "agent" not in st.session_state
        or st.session_state["agent"] is None
        or st.session_state.get("current_model") != model_id
    ):
        logger.info("---*--- Creating new Agentic RAG Agent ---*---")

        session_id = st.session_state.get("session_id")
        agent = get_agentic_rag_agent(model_id=model_id, session_id=session_id)

        st.session_state["agent"] = agent
        st.session_state["current_model"] = model_id
    else:
        agent = st.session_state["agent"]

    ####################################################################
    # Initialize session tracking (let streamlit utilities handle loading)
    ####################################################################
    logger.info("---*--- Loading Agentic RAG session ---*---")
    if agent.session_id:
        logger.info(f"---*--- Agentic RAG session: {agent.session_id} ---*---")
        st.session_state["session_id"] = agent.session_id
    else:
        logger.info("---*--- Agentic RAG session: None (New Chat) ---*---")

    # Initialize messages if needed (streamlit utilities will populate them)
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    if prompt := st.chat_input("👋 Ask me anything!"):
        add_message("user", prompt)

    ####################################################################
    # Document Management
    ####################################################################
    st.sidebar.markdown("#### 📚 Document Management")
    st.sidebar.metric("Documents Loaded", agent.knowledge.vector_store.get_count())

    # URL input
    input_url = st.sidebar.text_input("Add URL to Knowledge Base")
    if input_url and not prompt:
        alert = st.sidebar.info("Processing URL...", icon="ℹ️")
        try:
            agent.knowledge.add_content(
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
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(
                suffix=f".{uploaded_file.name.split('.')[-1]}", delete=False
            ) as tmp_file:
                tmp_file.write(uploaded_file.read())
                tmp_path = tmp_file.name

            # Use the Knowledge system's add_content method
            agent.knowledge.add_content(
                name=uploaded_file.name,
                path=tmp_path,
                description=f"Uploaded file: {uploaded_file.name}",
            )

            # Clean up temporary file
            os.unlink(tmp_path)
            st.sidebar.success(f"{uploaded_file.name} added to knowledge base")
        except Exception as e:
            st.sidebar.error(f"Error processing file: {str(e)}")
        finally:
            alert.empty()

    # Clear knowledge base
    if st.sidebar.button("Clear Knowledge Base"):
        if agent.knowledge.vector_store:
            agent.knowledge.vector_store.delete()
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
    # Utility buttons (using streamlit utilities)
    ###############################################################
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns([1, 1])
    with col1:
        if st.sidebar.button("🔄 New Chat", use_container_width=True):
            restart_agent()
    with col2:
        # Export chat functionality (using streamlit utils)
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            # Generate filename
            session_id = st.session_state.get("session_id")
            if session_id and hasattr(agent, "session_name") and agent.session_name:
                clean_name = "".join(
                    c for c in agent.session_name if c.isalnum() or c in (" ", "-", "_")
                ).strip()
                clean_name = clean_name.replace(" ", "_")[:50]
                filename = f"agentic_rag_chat_{clean_name}.md"
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
    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            content = message["content"]
            if content is not None:
                with st.chat_message(message["role"]):
                    # Debug: Show what's in the session state message
                    if message["role"] == "assistant":
                        logger.debug(f"=== DISPLAYING MESSAGE ===")
                        logger.debug(f"Message keys: {list(message.keys())}")
                        logger.debug(f"Has tool_calls: {'tool_calls' in message}")
                        if "tool_calls" in message:
                            logger.debug(f"Tool_calls value: {message['tool_calls']}")
                            logger.debug(f"Tool_calls type: {type(message['tool_calls'])}")
                            if message["tool_calls"]:
                                logger.debug(f"Tool_calls length: {len(message['tool_calls'])}")
                    
                    # Display tool calls if they exist in the message
                    if "tool_calls" in message and message["tool_calls"]:
                        logger.debug(f"About to display {len(message['tool_calls'])} tool calls")
                        
                        # Convert OpenAI format to display format if needed
                        formatted_tools = []
                        for tool in message["tool_calls"]:
                            if isinstance(tool, dict):
                                if "function" in tool and "name" in tool.get("function", {}):
                                    # OpenAI format: convert to display format
                                    import json
                                    function_data = tool["function"]
                                    tool_name = function_data.get("name", "Unknown")
                                    
                                    # Parse arguments JSON string
                                    tool_args = {}
                                    try:
                                        if "arguments" in function_data:
                                            tool_args = json.loads(function_data["arguments"])
                                    except json.JSONDecodeError:
                                        tool_args = {"raw": function_data.get("arguments", "")}
                                    
                                    display_tool = {
                                        "tool_name": tool_name,
                                        "tool_args": tool_args,
                                        "result": "Result not stored in session history",
                                    }
                                    formatted_tools.append(display_tool)
                                elif "tool_name" in tool:
                                    # Already in display format
                                    formatted_tools.append(tool)
                                else:
                                    # Unknown format, try to display as-is
                                    formatted_tools.append(tool)
                            else:
                                formatted_tools.append(tool)
                        
                        display_tool_calls(st.empty(), formatted_tools)
                    else:
                        if message["role"] == "assistant":
                            logger.debug("Not displaying tool calls - either no key or empty value")

                    st.markdown(content)

    ####################################################################
    # Generate response for user message
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )
    if last_message and last_message.get("role") == "user":
        question = last_message["content"]
        with st.chat_message("assistant"):
            # Create container for tool calls
            tool_calls_container = st.empty()
            resp_container = st.empty()
            with st.spinner("🤔 Thinking..."):
                response = ""
                try:
                    # Run the agent and stream the response
                    run_response = agent.run(question, stream=True)
                    for resp_chunk in run_response:
                        # Display tool calls if available
                        if hasattr(resp_chunk, "tool") and resp_chunk.tool:
                            display_tool_calls(tool_calls_container, [resp_chunk.tool])

                        # Display response content
                        if resp_chunk.content is not None:
                            response += resp_chunk.content
                            resp_container.markdown(response)

                    add_message("assistant", response, agent.run_response.tools)
                except Exception as e:
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)

    ####################################################################
    # Session management widgets (using streamlit utilities)
    ####################################################################
    
    # Session selector with built-in rename functionality
    # Note: Rename option appears below when you have an active session
    session_selector_widget(agent, model_id, get_agentic_rag_agent)
    
    # Knowledge base information
    knowledge_base_info_widget(agent)

    ####################################################################
    # About section (inline instead of separate file)
    ####################################################################
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.markdown("""
    This Agentic RAG Assistant helps you analyze documents and web content using natural language queries.

    Built with:
    - 🚀 Agno
    - 💫 Streamlit
    """)


main()
