import nest_asyncio
import streamlit as st
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
    restart_agent,
    export_chat_history,
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
        "GPT-4o": "gpt-4o",
        "Claude 3 Sonnet": "claude-3-sonnet-20240229",
        "Gemini 1.5 Pro": "gemini-1.5-pro-latest",
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
    user_id_input = st.sidebar.text_input("Set User ID (optional)", value=st.session_state.get("user_id", ""), key="user_id_input")
    # Store User ID in session state immediately
    st.session_state["user_id"] = user_id_input if user_id_input else None

    st.sidebar.subheader("Enable Tools")
    # Add checkboxes for LLM OS tools
    use_calculator = st.sidebar.checkbox("Calculator", value=True, key="cb_calculator")
    use_ddg_search = st.sidebar.checkbox("Web Search (DDG)", value=True, key="cb_ddg")
    use_file_tools = st.sidebar.checkbox("File I/O", value=True, key="cb_file")
    use_shell_tools = st.sidebar.checkbox("Shell Access", value=True, key="cb_shell")

    st.sidebar.subheader("Enable Sub-Agents")
    # Add checkboxes for LLM OS sub-agents
    enable_data_analyst = st.sidebar.checkbox("Data Analyst", value=False, key="cb_data")
    enable_python_agent = st.sidebar.checkbox("Python Agent", value=False, key="cb_python")
    enable_research_agent = st.sidebar.checkbox("Research Agent", value=False, key="cb_research")
    enable_investment_agent = st.sidebar.checkbox("Investment Agent", value=False, key="cb_investment")

    # Added section for Knowledge Base Management
    st.sidebar.subheader("Manage Knowledge Base")
    uploaded_file = st.sidebar.file_uploader(
        "Add PDF to Knowledge Base", type="pdf", key="pdf_uploader"
    )
    if uploaded_file is not None:
        if st.sidebar.button("Add PDF", key="add_pdf_button"):
            agent = st.session_state.get("llm_os_agent")
            if agent:
                try:
                    with st.spinner(f"Processing {uploaded_file.name}..."):
                        # Save temp file path or use bytes directly
                        file_bytes = uploaded_file.getvalue()
                        pdf_doc = PDFReader().load(file_bytes)
                        agent.add_knowledge(documents=pdf_doc)
                        st.toast(f"✅ Added {uploaded_file.name} to knowledge base.", icon="📄")
                        # Clear the uploader after processing
                        # st.session_state.pdf_uploader = None # May cause issues, test needed
                except Exception as e:
                    logger.error(f"Error adding PDF: {e}")
                    st.toast(f"❌ Error adding PDF: {e}", icon="🔥")
            else:
                st.toast("Agent not initialized.", icon="⚠️")

    website_url = st.sidebar.text_input("Add Website URL to Knowledge Base", key="url_input")
    if website_url:
        if st.sidebar.button("Add URL", key="add_url_button"):
            agent = st.session_state.get("llm_os_agent")
            if agent:
                try:
                    with st.spinner(f"Processing {website_url}..."):
                        web_doc = WebsiteReader().load(website_url)
                        agent.add_knowledge(documents=web_doc)
                        st.toast(f"✅ Added {website_url} to knowledge base.", icon="🔗")
                        # Clear input after adding
                        # st.session_state.url_input = "" # May need js hack or rerun
                except Exception as e:
                    logger.error(f"Error adding URL: {e}")
                    st.toast(f"❌ Error adding URL: {e}", icon="🔥")
            else:
                st.toast("Agent not initialized.", icon="⚠️")

    # Store checkbox states to detect changes
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
        # Include user_id in the config for agent re-initialization
        "user_id": st.session_state.get("user_id"),
    }

    ####################################################################
    # Initialize Agent
    ####################################################################
    llm_os_agent: Agent
    # Check if agent needs re-initialization due to config change
    config_changed = st.session_state.get("current_config") != current_config
    logger.debug(f"[App] Checking agent re-initialization conditions:")
    logger.debug(f"[App]   'llm_os_agent' not in state: {'llm_os_agent' not in st.session_state}")
    if 'llm_os_agent' in st.session_state:
        logger.debug(f"[App]   st.session_state['llm_os_agent'] is None: {st.session_state['llm_os_agent'] is None}")
    logger.debug(f"[App]   config_changed: {config_changed}")
    if (
        "llm_os_agent" not in st.session_state
        or st.session_state["llm_os_agent"] is None
        or config_changed
    ):
        # Updated agent creation logic
        logger.info("---*--- Creating/Loading LLM OS agent ---*---")
        # Session ID is now handled by the session_selector_widget on change
        # This block now only handles initial creation or config changes
        # target_session_id = st.session_state.get("selected_session_id") # Removed
        logger.debug(f"Initializing agent with User: {st.session_state.get('user_id')}") # Removed target session log
        llm_os_agent = get_llm_os(
            # Pass the correct model_id format
            model_id=model_id,
            calculator=use_calculator,
            ddg_search=use_ddg_search,
            file_tools=use_file_tools,
            shell_tools=use_shell_tools,
            data_analyst=enable_data_analyst,
            python_agent_enable=enable_python_agent,
            research_agent_enable=enable_research_agent,
            investment_agent_enable=enable_investment_agent,
            # Pass user_id to the agent
            user_id=st.session_state.get("user_id"),
            # session_id is no longer passed here, handled by widget
            # session_id=target_session_id,
            debug_mode=True # Keep debug on for now
        )
        # Renamed session state key
        st.session_state["llm_os_agent"] = llm_os_agent
        # Store the current config
        st.session_state["current_config"] = current_config
        # Clear messages on re-initialization
        logger.debug("[App] Clearing st.session_state['messages'] due to agent re-initialization.")
        st.session_state["messages"] = []
        # <<< MODIFIED LOG vvv (Show ID from agent object)
        logger.info(f"LLM OS Agent created/loaded. Agent Session ID from agent object: {llm_os_agent.session_id}")
        # <<< MODIFIED LOG ^^^
        # Removed comparison logic as it's handled by the widget now
        # if target_session_id and llm_os_agent.session_id != target_session_id:
        #     logger.warning(f"Agent session ID {llm_os_agent.session_id} does NOT match target session ID {target_session_id} after initialization.")
        # elif target_session_id:
        #     logger.debug("Agent session ID matches target session ID.")

    else:
        # Renamed variable
        llm_os_agent = st.session_state["llm_os_agent"]

    # Removed agent session loading, handled internally by llm_os_agent storage

    ####################################################################
    # Load runs from memory (keep this part, might still be relevant)
    ####################################################################
    # Use the new agent variable
    logger.debug(f"[App] Attempting to load runs. Agent in state: {'llm_os_agent' in st.session_state and st.session_state['llm_os_agent'] is not None}")
    if 'llm_os_agent' in st.session_state and st.session_state['llm_os_agent']:
        current_agent_session_id = st.session_state['llm_os_agent'].session_id
        logger.debug(f"[App] Agent ID for run loading: {current_agent_session_id}")
        if current_agent_session_id is None:
            logger.error("[App] Agent Session ID is None before loading runs! Cannot load history.")
            agent_runs = []
        else:
            # Only attempt to load runs if session_id is valid
            agent_runs = llm_os_agent.memory.runs if hasattr(llm_os_agent.memory, 'runs') else []
            logger.debug(f"Retrieved agent {llm_os_agent.session_id}. Found {len(agent_runs)} runs in memory.")
    else:
        logger.warning("[App] Agent not found in session state before loading runs.")
        agent_runs = [] # Ensure agent_runs is defined

    # Initialize messages if not present or if agent was re-initialized
    if "messages" not in st.session_state:
        logger.debug(f"[App] Initializing st.session_state['messages'] because it was not found.")
        st.session_state["messages"] = []

    logger.debug(f"UI messages count before loading history: {len(st.session_state['messages'])}")
    # Load history only if messages are empty and runs exist (prevents duplication on rerun)
    logger.debug(f"[App] Checking history load condition: not st.session_state['messages'] = {not st.session_state['messages']}, agent_runs = {bool(agent_runs)}")
    if not st.session_state["messages"] and agent_runs:
        logger.debug("Loading run history from agent memory into UI messages")
        for _run in agent_runs:
            if _run.message is not None:
                add_message(_run.message.role, _run.message.content)
            if _run.response is not None:
                add_message("assistant", _run.response.content, _run.response.tools)

    ####################################################################
    # Sidebar - Utilities & Session Management
    ####################################################################
    st.sidebar.markdown("---")
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🔄 New Chat", key="new_chat_button"):
            restart_agent() # Call the updated restart_agent function
    with col2:
        if llm_os_agent.session_id:
            fn = f"llm_os_chat_{llm_os_agent.session_id}.md"
        else:
            fn = "llm_os_chat_history.md"
        st.download_button(
            "💾 Export Chat",
            export_chat_history(), # Call the updated export function
            file_name=fn,
            mime="text/markdown",
            key="export_chat_button"
        )

    # Add Delete Sessions button
    st.sidebar.markdown("", unsafe_allow_html=True) # Add some space
    if st.sidebar.button("⚠️ Delete All My Sessions", key="delete_sessions_button", type="primary"):
        current_user_id = st.session_state.get("user_id")
        if llm_os_agent and llm_os_agent.storage:
            try:
                # Attempt to delete sessions for the current user
                # NOTE: Assumes a delete_all_sessions method exists on the storage object
                logger.info(f"Attempting to delete all sessions for user: {current_user_id}")
                # Placeholder: Replace with actual method if different or add direct SQL execution if needed
                if hasattr(llm_os_agent.storage, "delete_all_sessions"):
                    llm_os_agent.storage.delete_all_sessions(user_id=current_user_id)
                    st.toast(f"Deleted all sessions for user '{current_user_id or 'default'}'.", icon="🗑️")
                    logger.info(f"Successfully deleted sessions for user: {current_user_id}")
                    # Restart agent to reflect the cleared state
                    # <<< ADDED LOG BEFORE RESTART vvv
                    logger.debug("[App] Triggering restart_agent after deleting sessions.")
                    # <<< ADDED LOG BEFORE RESTART ^^^
                    restart_agent()
                else:
                     logger.warning("Agent storage does not have a 'delete_all_sessions' method.")
                     st.error("Deletion feature not implemented for this storage type.")

            except Exception as e:
                logger.error(f"Error deleting sessions for user {current_user_id}: {e}", exc_info=True)
                st.error(f"Failed to delete sessions: {e}")
        else:
            st.warning("Agent or storage not initialized.")

    # Add Session Selector and Renamer
    st.sidebar.markdown("---")
    st.sidebar.markdown("#### 🔄 Sessions")
    session_selector_widget(llm_os_agent, current_config)
    rename_session_widget(llm_os_agent)

    ####################################################################
    # Sidebar - General (keep if useful, e.g., clearing chat)
    ####################################################################
    # Removed redundant Clear Chat button
    # if st.sidebar.button("Clear Chat History", key="clear_chat"):
    #     llm_os_agent.clear_session() # Use agent's method if available
    #     st.session_state["messages"] = []
    #     st.rerun()

    ####################################################################
    # Get user input
    ####################################################################
    # Updated chat input prompt
    if prompt := st.chat_input("🧠 Ask LLM OS anything!"):
        add_message("user", prompt)

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
                        display_tool_calls(st.empty(), message["tool_calls"])
                    st.markdown(_content)

    ####################################################################
    # Generate response for user message
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )
    if last_message and last_message.get("role") == "user":
        question = last_message["content"]
        with st.chat_message("assistant"):
            # Create container for tool calls *before* the streaming loop
            tool_calls_container = st.empty()
            resp_container = st.empty()
            with st.spinner("🤔 Thinking..."):
                response = ""
                try:
                    # Use the new agent variable and remove previous log
                    # Run the agent and stream the response
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
                    # Use the new agent variable
                    add_message("assistant", response, llm_os_agent.run_response.tools)
                except Exception as e:
                    logger.exception(e)
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)

    # Removed SQL-specific session widgets
    # session_selector_widget(sql_agent, model_id)
    # rename_session_widget(sql_agent)

    ####################################################################
    # About section
    ####################################################################
    about_widget() # Keep if desired


if __name__ == "__main__":
    main()
