import os
import tempfile

import nest_asyncio
import streamlit as st
from agentic_rag import get_agentic_rag_agent
from agno.utils.log import logger
from agno.utils.streamlit import (
    COMMON_CSS,
    add_message,
    display_tool_calls,
    export_chat_history,
    restart_agent_session,
    session_selector_widget,
)
from utils import knowledge_base_info_widget

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
    agentic_rag_agent: Agent
    if (
        "agent" not in st.session_state
        or st.session_state["agent"] is None
        or st.session_state.get("current_model") != model_id
    ):
        session_id = st.session_state.get("session_id")
        agentic_rag_agent = get_agentic_rag_agent(
            model_id=model_id, session_id=session_id
        )

        st.session_state["agent"] = agentic_rag_agent
        st.session_state["current_model"] = model_id
    else:
        agentic_rag_agent = st.session_state["agent"]

    ####################################################################
    # Session management
    ####################################################################
    if agentic_rag_agent.session_id:
        st.session_state["session_id"] = agentic_rag_agent.session_id

    # Initialize messages if needed (streamlit utilities will populate them)
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    if prompt := st.chat_input("👋 Ask me anything!"):
        add_message("user", prompt)

    ####################################################################
    # Document Management
    ####################################################################
    st.sidebar.markdown("#### 📚 Document Management")
    st.sidebar.metric(
        "Documents Loaded", agentic_rag_agent.knowledge.vector_store.get_count()
    )

    # URL input
    input_url = st.sidebar.text_input("Add URL to Knowledge Base")
    if input_url and not prompt:
        alert = st.sidebar.info("Processing URL...", icon="ℹ️")
        try:
            agentic_rag_agent.knowledge.add_content(
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
            agentic_rag_agent.knowledge.add_content(
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
        if agentic_rag_agent.knowledge.vector_store:
            agentic_rag_agent.knowledge.vector_store.delete()
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
        # Export chat
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            # Generate filename
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
    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            content = message["content"]
            if content is not None:
                with st.chat_message(message["role"]):
                    if "tool_calls" in message and message["tool_calls"]:
                        # Try to get tool executions with results from agent session
                        tool_executions_with_results = []
                        
                        # Get tool executions from the agent's session runs
                        if hasattr(agentic_rag_agent, 'agent_session') and agentic_rag_agent.agent_session and agentic_rag_agent.agent_session.runs:
                            for run in agentic_rag_agent.agent_session.runs:
                                if hasattr(run, 'tools') and run.tools:
                                    for tool_exec in run.tools:
                                        if hasattr(tool_exec, 'tool_name') and hasattr(tool_exec, 'tool_args') and hasattr(tool_exec, 'result'):
                                            # Try to parse result as JSON if it's a string
                                            result = tool_exec.result
                                            if isinstance(result, str):
                                                try:
                                                    import json
                                                    result = json.loads(result)
                                                except (json.JSONDecodeError, TypeError):
                                                    # Keep as string if not valid JSON
                                                    pass
                                            
                                            tool_executions_with_results.append({
                                                "tool_name": tool_exec.tool_name,
                                                "tool_args": tool_exec.tool_args,
                                                "result": result
                                            })
                        
                        # If we found tool executions with results, use them
                        if tool_executions_with_results:
                            display_tool_calls(st.empty(), tool_executions_with_results)
                        else:
                            # Fallback: Convert tool calls to display format if needed
                            formatted_tools = []
                            for tool in message["tool_calls"]:
                                if isinstance(tool, dict):
                                    # Check if it's already in display format
                                    if "tool_name" in tool:
                                        formatted_tools.append(tool)
                                    # Convert from OpenAI format
                                    elif "function" in tool and "name" in tool.get("function", {}):
                                        import json
                                        function_data = tool["function"]
                                        tool_name = function_data.get("name", "Unknown")
                                        
                                        tool_args = {}
                                        try:
                                            if "arguments" in function_data:
                                                tool_args = json.loads(function_data["arguments"]) if isinstance(function_data["arguments"], str) else function_data["arguments"]
                                        except json.JSONDecodeError:
                                            tool_args = {"raw": function_data.get("arguments", "")}
                                        
                                        display_tool = {
                                            "tool_name": tool_name,
                                            "tool_args": tool_args,
                                            "result": "Tool result not available in session history",
                                        }
                                        formatted_tools.append(display_tool)
                                    else:
                                        # Unknown format, try to display as-is
                                        formatted_tools.append(tool)
                                else:
                                    formatted_tools.append(tool)
                            
                            display_tool_calls(st.empty(), formatted_tools)
                    else:
                        if message["role"] == "assistant":
                            pass

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
                    run_response = agentic_rag_agent.run(question, stream=True)
                    for resp_chunk in run_response:
                        # Display tool calls if available
                        if hasattr(resp_chunk, "tool") and resp_chunk.tool:
                            display_tool_calls(tool_calls_container, [resp_chunk.tool])

                        # Display response content
                        if resp_chunk.content is not None:
                            response += resp_chunk.content
                            resp_container.markdown(response)

                    add_message(
                        "assistant", response, agentic_rag_agent.run_response.tools
                    )
                except Exception as e:
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)

    ####################################################################
    # Session management widgets (using streamlit utilities)
    ####################################################################

    # Session selector with built-in rename functionality
    # Note: Rename option appears below when you have an active session
    session_selector_widget(agentic_rag_agent, model_id, get_agentic_rag_agent)

    # Knowledge base information
    knowledge_base_info_widget(agentic_rag_agent)

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
