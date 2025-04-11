import nest_asyncio
import streamlit as st
import io
from os_agent import get_llm_os
from agno.agent import Agent
from agno.document import Document
from agno.document.reader.pdf_reader import PDFReader
from agno.document.reader.website_reader import WebsiteReader
from agno.utils.log import logger
from utils import (
    CUSTOM_CSS,
    about_widget,
    add_message,
    display_tool_calls,
    export_chat_history,
    restart_agent,
    session_selector_widget,
    rename_session_widget,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="LLM OS",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load custom CSS
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def main() -> None:
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>LLM OS</h1>", unsafe_allow_html=True
    )
    st.markdown(
        "<p class='subtitle'>Your versatile AI assistant powered by Agno</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Sidebar Configuration
    ####################################################################
    st.sidebar.header("Configuration")

    # Model selector
    model_options = {
        "GPT-4o": "openai:gpt-4o",
        "Claude 3.7 Sonnet": "anthropic:claude-3-7-sonnet-latest",
        "Gemini 2.5 Pro Exp": "google:gemini-2.5-pro-exp-03-25",
        "Llama 4 Scout": "groq:meta-llama/llama-4-scout-17b-16e-instruct",
        "Llama 4 Maverick": "groq:meta-llama/llama-4-maverick-17b-128e-instruct",
    }
    selected_model_key = st.sidebar.selectbox(
        "Select a model",
        options=list(model_options.keys()),
        index=0, # Default to gpt-4o
        key="model_selector",
    )
    model_id = model_options[selected_model_key]

    # Add User ID input
    st.sidebar.subheader("User")
    # Use st.session_state.get to avoid error on first run if key doesn't exist
    user_id_input = st.sidebar.text_input(
        "Set User ID (optional)",
        value=st.session_state.get("user_id_input_value", ""), # Use a separate key for the input value
        key="user_id_input")
    # Store/update User ID in session state only when input changes or on first load
    # This avoids overwriting it during session loading reruns
    if user_id_input != st.session_state.get("user_id_input_value"):
        st.session_state["user_id_input_value"] = user_id_input
        st.session_state["user_id"] = user_id_input if user_id_input else None
        # No rerun needed here, agent initialization handles it

    st.sidebar.subheader("Enable Tools")
    # Add checkboxes for LLM OS tools
    use_calculator = st.sidebar.checkbox("Calculator", value=st.session_state.get("cb_calculator", True), key="cb_calculator")
    use_ddg_search = st.sidebar.checkbox("Web Search (DDG)", value=st.session_state.get("cb_ddg", True), key="cb_ddg")
    use_file_tools = st.sidebar.checkbox("File I/O", value=st.session_state.get("cb_file", True), key="cb_file")
    use_shell_tools = st.sidebar.checkbox("Shell Access", value=st.session_state.get("cb_shell", True), key="cb_shell")

    st.sidebar.subheader("Enable Sub-Agents")
    # Add checkboxes for LLM OS sub-agents
    enable_data_analyst = st.sidebar.checkbox("Data Analyst", value=st.session_state.get("cb_data", False), key="cb_data")
    enable_python_agent = st.sidebar.checkbox("Python Agent", value=st.session_state.get("cb_python", False), key="cb_python")
    enable_research_agent = st.sidebar.checkbox("Research Agent", value=st.session_state.get("cb_research", False), key="cb_research")
    enable_investment_agent = st.sidebar.checkbox("Investment Agent", value=st.session_state.get("cb_investment", False), key="cb_investment")

    # Store current config from sidebar for potential agent re-initialization
    current_config = {
        "model_id": model_id,
        "calculator": use_calculator,
        "ddg_search": use_ddg_search,
        "file_tools": use_file_tools,
        "shell_tools": use_shell_tools,
        "data_analyst": enable_data_analyst,
        "python_agent_enable": enable_python_agent,
        "research_agent_enable": enable_research_agent,
        "investment_agent_enable": enable_investment_agent,
        "user_id": st.session_state.get("user_id"),
        "debug_mode": True # Or make this configurable
    }

    # Added section for Knowledge Base Management
    st.sidebar.subheader("Manage Knowledge Base")
    uploaded_file = st.sidebar.file_uploader(
        "Add PDF to Knowledge Base", type="pdf", key="pdf_uploader"
    )
    if uploaded_file is not None:
        # Use the persistent agent instance
        agent_for_kb = st.session_state.get("llm_os_agent")
        if st.sidebar.button("Add PDF", key="add_pdf_button"):
            if agent_for_kb:
                try:
                    with st.spinner(f"Processing {uploaded_file.name}..."):
                        file_bytes = uploaded_file.getvalue()
                        # Wrap bytes in BytesIO and use read() method
                        pdf_stream = io.BytesIO(file_bytes)
                        pdf_stream.name = uploaded_file.name # Optional: provide name for logging within reader
                        pdf_docs = PDFReader().read(pdf=pdf_stream)

                        # Access the vector_db from the agent's knowledge and insert documents
                        if agent_for_kb.knowledge and agent_for_kb.knowledge.vector_db:
                            if pdf_docs: # Ensure there are documents to add
                                agent_for_kb.knowledge.vector_db.insert(documents=pdf_docs)
                                st.toast(f"✅ Added {len(pdf_docs)} page(s) from {uploaded_file.name} to knowledge base.", icon="📄")
                            else:
                                st.toast(f"⚠️ No readable content found in {uploaded_file.name}.", icon="⚠️")
                        else:
                            st.toast("Knowledge base vector store not available.", icon="🔥")

                except Exception as e:
                    logger.error(f"Error adding PDF: {e}")
                    st.toast(f"❌ Error adding PDF: {e}", icon="🔥")
            else:
                st.toast("Agent not initialized. Please wait or refresh.", icon="⚠️")

    website_url = st.sidebar.text_input("Add Website URL to Knowledge Base", key="url_input")
    if website_url:
        # Use the persistent agent instance
        agent_for_kb = st.session_state.get("llm_os_agent")
        if st.sidebar.button("Add URL", key="add_url_button"):
            if agent_for_kb:
                try:
                    with st.spinner(f"Processing {website_url}..."):
                        # Use read() method instead of load
                        web_docs = WebsiteReader().read(url=website_url)

                        # Access the vector_db from the agent's knowledge and insert documents
                        if agent_for_kb.knowledge and agent_for_kb.knowledge.vector_db:
                            if web_docs: # Ensure there are documents to add
                                agent_for_kb.knowledge.vector_db.insert(documents=web_docs)
                                st.toast(f"✅ Added content from {website_url} to knowledge base.", icon="🔗")
                            else:
                                st.toast(f"⚠️ No readable content found at {website_url}.", icon="⚠️")
                        else:
                            st.toast("Knowledge base vector store not available.", icon="🔥")

                except Exception as e:
                    logger.error(f"Error adding URL: {e}")
                    st.toast(f"❌ Error adding URL: {e}", icon="🔥")
            else:
                st.toast("Agent not initialized. Please wait or refresh.", icon="⚠️")


    ####################################################################
    # Initialize Agent (with Session Management)
    ####################################################################
    # Remove detailed logging before the check
    # logger.debug(f"Checking agent initialization: has agent? {"llm_os_agent" in st.session_state and st.session_state["llm_os_agent"] is not None}")
    # logger.debug(f"Stored config: {st.session_state.get('current_config')}")
    # logger.debug(f"Current config: {current_config}")
    # config_comparison = st.session_state.get("current_config") != current_config
    # logger.debug(f"Config changed? {config_comparison}")

    llm_os_agent: Optional[Agent] = None
    # Simplify the re-initialization check: only re-init if agent doesn't exist or model changes
    agent_should_initialize = (
        "llm_os_agent" not in st.session_state
        or st.session_state["llm_os_agent"] is None
        or st.session_state.get("current_model_id") != model_id
    )

    # Also consider other critical config changes if needed, but start simple
    # agent_config_changed = (
    #     st.session_state.get("current_config") != current_config
    # )

    if agent_should_initialize:
        # logger.info(f"---*--- Creating/Re-initializing LLM OS agent (Config changed: {agent_config_changed}) ---*---")
        logger.info(f"---*--- Creating/Re-initializing LLM OS agent (Model changed or first run) ---*---")
        # Always create a new agent instance if config changes or no agent exists
        # We pass the full current_config here, but the trigger is simplified
        llm_os_agent = get_llm_os(**current_config) # Pass current config
        st.session_state["llm_os_agent"] = llm_os_agent
        st.session_state["current_model_id"] = model_id # Store the model ID used
        # st.session_state["current_config"] = current_config # Store the config used (optional, maybe remove if comparison is simplified)
        st.session_state["messages"] = [] # Clear UI messages on re-init
        logger.info(f"New LLM OS Agent created/re-initialized. Instance: {id(llm_os_agent)}")
        # Attempt to load session after creating agent
        try:
            if hasattr(llm_os_agent, 'load_session') and callable(llm_os_agent.load_session):
                session_id = llm_os_agent.load_session()
                st.session_state["llm_os_session_id"] = session_id
                logger.info(f"Loaded session ID: {session_id}")
            else:
                 logger.warning("Agent does not have a load_session method.")
                 st.session_state["llm_os_session_id"] = None # Ensure it's set
        except Exception as e:
            logger.error(f"Could not load agent session: {e}")
            st.warning(f"Could not load agent session: {e}")
            st.session_state["llm_os_session_id"] = None # Ensure it's set
    else:
        # Use existing agent from session state
        llm_os_agent = st.session_state["llm_os_agent"]
        logger.debug(f"Using existing LLM OS agent. Instance: {id(llm_os_agent)}, Session ID: {llm_os_agent.session_id}")


    ####################################################################
    # Load runs from memory IF messages list is empty (e.g., after session load/app restart)
    ####################################################################
    logger.debug(f"Checking history load: Agent exists? {llm_os_agent is not None}. Messages empty? {not st.session_state.get('messages')}")
    if llm_os_agent and not st.session_state.get("messages"): # Only load if messages are empty
        logger.info("Attempting to load chat history from agent memory...")
        try:
            if hasattr(llm_os_agent, 'memory') and hasattr(llm_os_agent.memory, 'runs'):
                agent_runs = llm_os_agent.memory.runs
                if agent_runs:
                    logger.info(f"Loading {len(agent_runs)} runs from agent memory into UI history.")
                    st.session_state["messages"] = [] # Ensure it's clear before loading
                    for _run in agent_runs:
                        if _run.message is not None:
                            add_message(_run.message.role, _run.message.content)
                            logger.debug(f"Loaded user message: {_run.message.content[:50]}...")
                        if _run.response is not None:
                            # Use 'assistant' role for agent responses in UI
                            add_message("assistant", _run.response.content, _run.response.tools)
                            logger.debug(f"Loaded assistant message: {_run.response.content[:50]}...")
                    # Temporarily comment out the rerun to see if it helps
                    logger.info(f"Finished loading {len(st.session_state['messages'])} messages into UI state. Triggering rerun.")
                    st.rerun() # Rerun to display loaded history immediately
                else:
                    logger.debug("Agent memory has no runs to load.")
                    st.session_state["messages"] = [] # Ensure messages is an empty list
            else:
                logger.warning("Agent has no memory or runs attribute.")
                st.session_state["messages"] = [] # Ensure messages is an empty list
        except Exception as e:
            logger.error(f"Error loading runs from agent memory: {e}")
            st.session_state["messages"] = [] # Reset messages on error


    # Initialize messages list in session state if it doesn't exist (fallback)
    if "messages" not in st.session_state:
        st.session_state["messages"] = []


    ####################################################################
    # Sidebar - Utilities & Session Management
    ####################################################################
    st.sidebar.markdown("---")
    st.sidebar.markdown("#### 🛠️ Utilities & Sessions")

    # Add New Chat button
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🔄 New Chat", key="new_chat_button", help="Start a new chat session"):
            restart_agent() # This function handles clearing state and rerun

    # Export Chat button using the persistent agent's session ID
    with col2:
        export_filename = "llm_os_chat_history.md"
        if llm_os_agent and hasattr(llm_os_agent, 'session_id') and llm_os_agent.session_id:
             export_filename = f"llm_os_chat_{llm_os_agent.session_id}.md"

        st.download_button(
            "💾 Export Chat",
            export_chat_history(), # Reads from st.session_state["messages"]
            file_name=export_filename,
            mime="text/markdown",
            key="export_chat_button",
            help="Download the current chat history as a markdown file."
        )

    # Add Session Selector and Renamer Widgets
    if llm_os_agent:
        # Pass the current config needed by the session_selector_widget for re-initialization
        session_selector_widget(llm_os_agent, current_config)
        rename_session_widget(llm_os_agent)
    else:
        st.sidebar.warning("Agent not ready for session management.")


    # --- REMOVED Simplified Agent Initialization ---
    # logger.info("---*--- Creating new LLM OS agent (No Session Management) ---*---")
    # llm_os_agent_temp = get_llm_os(...)
    # st.session_state["llm_os_agent_temp"] = llm_os_agent_temp
    # logger.info(f"New LLM OS Agent created. Instance: {id(llm_os_agent_temp)}")
    # --- REMOVED Temporary Agent Usage ---

    # --- REMOVED Simplified History Management ---
    # if "messages" not in st.session_state:
    #     logger.debug("Initializing st.session_state['messages'] for UI display.")
    #     st.session_state["messages"] = []
    # logger.debug("Chat history is now managed solely by st.session_state['messages'] for the UI session.")


    ####################################################################
    # Get user input
    ####################################################################
    # Updated chat input prompt
    if prompt := st.chat_input("🧠 Ask LLM OS anything!"):
        add_message("user", prompt)
        # Rerun needed to process the new message immediately
        st.rerun()


    ####################################################################
    # Display chat history
    ####################################################################
    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            _content = message.get("content") # Use .get for safety
            if _content is not None:
                with st.chat_message(message["role"]):
                    # Display tool calls if they exist in the message
                    if "tool_calls" in message and message["tool_calls"]:
                        # Pass the existing container creation function
                        display_tool_calls(st.empty(), message["tool_calls"]) # Create new container each time
                    st.markdown(_content)


    ####################################################################
    # Generate response for user message
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )
    # Ensure agent is initialized before attempting to run
    if llm_os_agent and last_message and last_message.get("role") == "user":
        question = last_message["content"]
        # Use the persistent agent instance from session state
        # current_run_agent = st.session_state.get("llm_os_agent") # Redundant check, use llm_os_agent directly

        with st.chat_message("assistant"):
            # Create container for tool calls *before* the streaming loop
            tool_calls_container = st.empty()
            resp_container = st.empty()
            with st.spinner("🤔 Thinking..."):
                response = ""
                try:
                    # Use the persistent agent instance
                    run_response = llm_os_agent.run(
                        question, stream=True, stream_intermediate_steps=True
                    )
                    for _resp_chunk in run_response:
                        # Display tool calls if available, updating the single container
                        if _resp_chunk.tools and len(_resp_chunk.tools) > 0:
                            display_tool_calls(tool_calls_container, _resp_chunk.tools)

                        # Display response if available and event is RunResponse
                        if (
                            _resp_chunk.event == "RunResponse"
                            and _resp_chunk.content is not None
                        ):
                            response += _resp_chunk.content
                            resp_container.markdown(response)

                    # Add final message with tool calls from the persistent agent's last run
                    add_message("assistant", response, llm_os_agent.run_response.tools)
                    # No explicit rerun needed here, message added to state, Streamlit handles update.
                except Exception as e:
                    logger.exception(e)
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    resp_container.error(error_message) # Display error in response container

    elif not llm_os_agent and last_message and last_message.get("role") == "user":
         st.error("Agent not initialized. Please wait or refresh the page.")


    ####################################################################
    # About section
    ####################################################################
    about_widget() # Keep if desired


if __name__ == "__main__":
    main()
