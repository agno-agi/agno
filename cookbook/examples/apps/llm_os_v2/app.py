import nest_asyncio
import streamlit as st
import io
from os_agent import get_llm_os
from agno.agent import Agent
from agno.team import Team
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
    llm_os_team: Optional[Team] = None

    # Simplify the re-initialization check: only re-init if agent/team doesn't exist or model changes
    team_should_initialize = (
        "llm_os_team" not in st.session_state
        or st.session_state["llm_os_team"] is None
        or st.session_state.get("current_model_id") != model_id
    )

    if team_should_initialize:
        logger.info(f"---*--- Creating/Re-initializing LLM OS Team (Model changed or first run) ---*---")
        logger.debug(f"Passing config to get_llm_os: {current_config}") # Log the config
        llm_os_team = get_llm_os(**current_config) # Call the refactored function
        st.session_state["llm_os_team"] = llm_os_team # Store the Team instance
        st.session_state["current_model_id"] = model_id
        st.session_state["messages"] = [] # Clear UI messages on re-init
        logger.info(f"New LLM OS Team created/re-initialized. Instance: {id(llm_os_team)}")
        # Attempt to load session after creating team
        try:
            # Use the team instance to load session
            if hasattr(llm_os_team, 'load_session') and callable(llm_os_team.load_session):
                session_id = llm_os_team.load_session()
                st.session_state["llm_os_session_id"] = session_id
                logger.info(f"Loaded session ID: {session_id}")
            else:
                 logger.warning("Team does not have a load_session method.")
                 st.session_state["llm_os_session_id"] = None
        except Exception as e:
            logger.error(f"Could not load team session: {e}")
            st.warning(f"Could not load team session: {e}")
            st.session_state["llm_os_session_id"] = None
    else:
        # Use existing team from session state
        llm_os_team = st.session_state["llm_os_team"]
        logger.debug(f"Using existing LLM OS Team. Instance: {id(llm_os_team)}, Session ID: {llm_os_team.session_id}") # Assuming Team has session_id


    ####################################################################
    # Load runs from memory IF messages list is empty
    ####################################################################
    logger.debug(f"Checking history load: Team exists? {llm_os_team is not None}. Messages empty? {not st.session_state.get('messages')}")
    if llm_os_team and not st.session_state.get("messages"): # Only load if messages are empty
        logger.info("Attempting to load chat history from team memory...")
        try:
            # Assuming Team has a memory attribute similar to Agent
            if hasattr(llm_os_team, 'memory') and hasattr(llm_os_team.memory, 'runs'):
                team_runs = llm_os_team.memory.runs
                if team_runs:
                    logger.info(f"Loading {len(team_runs)} runs from team memory into UI history.")
                    st.session_state["messages"] = []
                    for _run in team_runs:
                        if _run.message is not None:
                            add_message(_run.message.role, _run.message.content)
                            logger.debug(f"Loaded user message: {_run.message.content[:50]}...")
                        if _run.response is not None:
                            add_message("assistant", _run.response.content, _run.response.tools)
                            logger.debug(f"Loaded assistant message: {_run.response.content[:50]}...")
                    logger.info(f"Finished loading {len(st.session_state['messages'])} messages into UI state. Triggering rerun.")
                    st.rerun() # Re-enable rerun after history loading
                else:
                    logger.debug("Team memory has no runs to load.")
                    st.session_state["messages"] = []
            else:
                logger.warning("Team has no memory or runs attribute.")
                st.session_state["messages"] = []
        except Exception as e:
            logger.error(f"Error loading runs from team memory: {e}")
            st.session_state["messages"] = []


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
        if llm_os_team and hasattr(llm_os_team, 'session_id') and llm_os_team.session_id:
             export_filename = f"llm_os_chat_{llm_os_team.session_id}.md"

        st.download_button(
            "💾 Export Chat",
            export_chat_history(), # Reads from st.session_state["messages"]
            file_name=export_filename,
            mime="text/markdown",
            key="export_chat_button",
            help="Download the current chat history as a markdown file."
        )

    # Add Session Selector and Renamer Widgets
    if llm_os_team:
        # Pass the current config needed by the session_selector_widget for re-initialization
        # Also pass the current session ID from state explicitly for reliable comparison
        current_session_id = st.session_state.get("llm_os_session_id")
        session_selector_widget(llm_os_team, current_config, current_session_id)
        rename_session_widget(llm_os_team)
    else:
        st.sidebar.warning("Team not ready for session management.")


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
    # Add logging to check the last message before the condition
    logger.debug(f"Checking for response generation. Last message: {last_message}")
    # Check if the Team is initialized
    if llm_os_team and last_message and last_message.get("role") == "user":
        question = last_message["content"]

        with st.chat_message("assistant"):
            tool_calls_container = st.empty()
            resp_container = st.empty()
            intermediate_steps_container = st.container() # New container for intermediate steps
            with st.spinner("🤔 Coordinating Team..."): # Updated spinner text
                response = ""
                try:
                    # Use the Team instance to run
                    run_response = llm_os_team.run(
                        question, stream=True, stream_intermediate_steps=True
                    )
                    for _resp_chunk in run_response:
                        logger.debug(f"Received chunk: Event={_resp_chunk.event}, Content Type={type(_resp_chunk.content)}, Content={_resp_chunk.content}, Tools={_resp_chunk.tools}, Raw Chunk: {_resp_chunk}") # Keep detailed logging

                        # --- Enhanced Event Handling for Team Observability ---
                        event_type = _resp_chunk.event.lower() if _resp_chunk.event else None

                        if event_type == 'thinking':
                            with intermediate_steps_container.expander("Coordinator Reasoning", expanded=False):
                                st.markdown(_resp_chunk.content)
                        elif event_type == 'toolcallstarted':
                             # Check if it's a delegation call (member name = tool name)
                             member_names = [m.name for m in llm_os_team.members] if llm_os_team.members else []
                             tool_name = _resp_chunk.tools[0].get('tool_name') if _resp_chunk.tools else None
                             if tool_name in member_names:
                                 intermediate_steps_container.info(f"⏳ Delegating to `{tool_name}`...")
                             else:
                                 with intermediate_steps_container.expander(f"Coordinator Tool Call: `{tool_name}`", expanded=False):
                                     st.code(str(_resp_chunk.tools[0].get('tool_args', '')), language='json')
                        elif event_type == 'toolcallcompleted':
                             member_names = [m.name for m in llm_os_team.members] if llm_os_team.members else []
                             tool_name = _resp_chunk.tools[0].get('tool_name') if _resp_chunk.tools else None
                             if tool_name not in member_names: # Only show non-member tool results here
                                with intermediate_steps_container.expander(f"Coordinator Tool Result: `{tool_name}`", expanded=False):
                                    st.code(str(_resp_chunk.tools[0].get('content', '')), language='json') # Assuming content is JSON-like
                        elif event_type == 'memberrunstarted':
                            member_name = _resp_chunk.extra_data.get('member_name', 'Unknown Agent') if _resp_chunk.extra_data else 'Unknown Agent'
                            intermediate_steps_container.info(f"🚀 Starting task execution by `{member_name}`...")
                        elif event_type == 'memberresponse':
                            member_name = _resp_chunk.extra_data.get('member_name', 'Unknown Agent') if _resp_chunk.extra_data else 'Unknown Agent'
                            with intermediate_steps_container.expander(f"Response from `{member_name}`", expanded=True):
                                if _resp_chunk.tools:
                                    display_tool_calls(st.empty(), _resp_chunk.tools)
                                if _resp_chunk.content:
                                    st.markdown(_resp_chunk.content)
                        elif event_type == 'memberruncompleted':
                            member_name = _resp_chunk.extra_data.get('member_name', 'Unknown Agent') if _resp_chunk.extra_data else 'Unknown Agent'
                            intermediate_steps_container.success(f"✅ Task execution by `{member_name}` completed.")
                        # Display final response stream
                        elif event_type == 'runresponse' and _resp_chunk.content is not None:
                            response += _resp_chunk.content
                            resp_container.markdown(response)
                        # Fallback for other/unexpected tool displays
                        elif _resp_chunk.tools and event_type not in ['toolcallstarted', 'toolcallcompleted', 'memberresponse']:
                            display_tool_calls(tool_calls_container, _resp_chunk.tools)

                    # Add final message using Team's run_response
                    # Assuming Team also has a run_response attribute
                    final_tools = llm_os_team.run_response.tools if hasattr(llm_os_team, 'run_response') else None
                    add_message("assistant", response, final_tools)
                except Exception as e:
                    logger.exception(e)
                    error_message = f"Sorry, the team encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    resp_container.error(error_message)

    elif not llm_os_team and last_message and last_message.get("role") == "user":
         st.error("Team not initialized. Please wait or refresh the page.")


    ####################################################################
    # About section
    ####################################################################
    about_widget() # Keep if desired


if __name__ == "__main__":
    main()
