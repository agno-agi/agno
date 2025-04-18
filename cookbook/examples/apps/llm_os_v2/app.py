import io
import os

import nest_asyncio
import streamlit as st
from agno.agent import Agent
from agno.document import Document
from agno.document.reader.pdf_reader import PDFReader
from agno.document.reader.website_reader import WebsiteReader
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.utils.log import logger
from os_agent import SQLITE_DB_PATH, get_llm_os
from utils import (
    CUSTOM_CSS,
    about_widget,
    add_message,
    display_tool_calls,
    export_chat_history,
    rename_session_widget,
    restart_agent,
    session_selector_widget,
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
    st.markdown("<h1 class='main-title'>LLM OS</h1>", unsafe_allow_html=True)
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
    }

    selected_model_key = st.sidebar.selectbox(
        "Select a model",
        options=list(model_options.keys()),
        index=0,  # Default to gpt-4o
        key="model_selector",
    )
    model_id = model_options[selected_model_key]

    # Add User ID input
    st.sidebar.subheader("User")

    # Use st.session_state.get to avoid error on first run if key doesn't exist
    user_id_input = st.sidebar.text_input(
        "Set User ID (optional)",
        value=st.session_state.get(
            "user_id_input_value", ""
        ),  # Use a separate key for the input value
        key="user_id_input",
    )

    # Store/update User ID in session state only when input changes or on first load
    if user_id_input != st.session_state.get("user_id_input_value"):
        st.session_state["user_id_input_value"] = user_id_input
        st.session_state["user_id"] = user_id_input if user_id_input else None

    st.sidebar.subheader("Enable Tools")

    use_calculator = st.sidebar.checkbox(
        "Calculator",
        value=st.session_state.get("cb_calculator", True),
        key="cb_calculator",
    )
    use_ddg_search = st.sidebar.checkbox(
        "Web Search (DDG)", value=st.session_state.get("cb_ddg", True), key="cb_ddg"
    )
    use_file_tools = st.sidebar.checkbox(
        "File I/O", value=st.session_state.get("cb_file", True), key="cb_file"
    )
    use_shell_tools = st.sidebar.checkbox(
        "Shell Access", value=st.session_state.get("cb_shell", True), key="cb_shell"
    )

    # --- Add Team Member Checkboxes --- Start
    st.sidebar.markdown("---")  # Add separator
    st.sidebar.subheader("Enable Team Members")
    enable_data_analyst = st.sidebar.checkbox(
        "Data Analyst",
        value=st.session_state.get("cb_data_analyst", True),
        key="cb_data_analyst",
    )
    enable_python_agent = st.sidebar.checkbox(
        "Python Agent",
        value=st.session_state.get("cb_python_agent", True),
        key="cb_python_agent",
    )
    enable_research_agent = st.sidebar.checkbox(
        "Research Agent",
        value=st.session_state.get("cb_research_agent", True),
        key="cb_research_agent",
    )  # Default True
    enable_investment_agent = st.sidebar.checkbox(
        "Investment Agent",
        value=st.session_state.get("cb_investment_agent", True),
        key="cb_investment_agent",
    )
    # --- Add Team Member Checkboxes --- End

    # Define current_config HERE, **BEFORE** it might be used
    current_config = {
        "model_id": model_id,
        "calculator": use_calculator,
        "ddg_search": use_ddg_search,
        "file_tools": use_file_tools,
        "shell_tools": use_shell_tools,
        # --- Pass Member Enablement Flags --- Start
        "data_analyst": enable_data_analyst,
        "python_agent_enable": enable_python_agent,
        "research_agent_enable": enable_research_agent,
        "investment_agent_enable": enable_investment_agent,
        # --- Pass Member Enablement Flags --- End
        "user_id": st.session_state.get("user_id"),
        "debug_mode": True,  # Or make this configurable
    }

    st.sidebar.markdown("---")  # Add a separator
    st.sidebar.subheader("Chat Sessions")

    team_instance_for_widgets = st.session_state.get("llm_os_team")

    if team_instance_for_widgets:
        session_selector_widget(team_instance_for_widgets, current_config)
    else:
        st.sidebar.caption("Chat history available after first message.")

    if team_instance_for_widgets:
        rename_session_widget(team_instance_for_widgets)

    st.sidebar.markdown("---")  # Add another separator

    # Added section for Knowledge Base Management
    st.sidebar.subheader("Manage Knowledge Base")
    uploaded_file = st.sidebar.file_uploader(
        "Add PDF to Knowledge Base", type="pdf", key="pdf_uploader"
    )
    if uploaded_file is not None:
        team_for_kb = st.session_state.get("llm_os_team")

        if team_for_kb:
            logger.debug(f"PDF Upload: Team object attributes: {dir(team_for_kb)}")
            logger.debug(
                f"PDF Upload: Does team have 'knowledge'? {'knowledge' in dir(team_for_kb)}"
            )
            if hasattr(team_for_kb, "knowledge"):
                logger.debug(
                    f"PDF Upload: Team knowledge object: {type(team_for_kb.knowledge)}"
                )
                logger.debug(
                    f"PDF Upload: Team knowledge attributes: {dir(team_for_kb.knowledge)}"
                )
                logger.debug(
                    f"PDF Upload: Does knowledge have 'vector_db'? {'vector_db' in dir(team_for_kb.knowledge)}"
                )
                if hasattr(team_for_kb.knowledge, "vector_db"):
                    logger.debug(
                        f"PDF Upload: Vector DB object: {type(team_for_kb.knowledge.vector_db)}"
                    )
                    logger.debug(
                        f"PDF Upload: Vector DB attributes: {dir(team_for_kb.knowledge.vector_db)}"
                    )
        else:
            logger.warning("PDF Upload: Team object not found in session state!")
        if st.sidebar.button("Add PDF", key="add_pdf_button"):
            if team_for_kb:
                try:
                    with st.spinner(f"Processing {uploaded_file.name}..."):
                        file_bytes = uploaded_file.getvalue()
                        pdf_stream = io.BytesIO(file_bytes)
                        pdf_stream.name = uploaded_file.name
                        pdf_docs = PDFReader().read(pdf=pdf_stream)

                        if (
                            team_for_kb.knowledge
                            and hasattr(team_for_kb.knowledge, "vector_db")
                            and team_for_kb.knowledge.vector_db
                        ):  # Added hasattr check
                            if pdf_docs:  # Ensure there are documents to add
                                logger.info(
                                    f"Attempting to insert {len(pdf_docs)} PDF documents into vector DB."
                                )  # Add log before insert
                                team_for_kb.knowledge.vector_db.insert(
                                    documents=pdf_docs
                                )  # <-- FIX: Use correct object
                                st.toast(
                                    f"✅ Added {len(pdf_docs)} page(s) from {uploaded_file.name} to knowledge base.",
                                    icon="📄",
                                )
                            else:
                                st.toast(
                                    f"⚠️ No readable content found in {uploaded_file.name}.",
                                    icon="⚠️",
                                )
                        else:
                            logger.warning(
                                "PDF Upload: Knowledge base or vector store not available on team object."
                            )  # Log warning
                            st.toast(
                                "Knowledge base vector store not available.", icon="🔥"
                            )

                except Exception as e:
                    logger.error(
                        f"Error adding PDF: {e}", exc_info=True
                    )  # Log stack trace
                    st.toast(f"❌ Error adding PDF: {e}", icon="🔥")
            else:
                st.toast(
                    "Team not initialized. Please wait or refresh.", icon="⚠️"
                )  # FIX: Updated message

    website_url = st.sidebar.text_input(
        "Add Website URL to Knowledge Base", key="url_input"
    )
    if website_url:
        team_for_kb = st.session_state.get("llm_os_team")  # <-- Correct key

        logger.debug(
            f"URL Upload: Found team object in session state: {type(team_for_kb)}"
        )

        if team_for_kb:
            logger.debug(f"URL Upload: Team object attributes: {dir(team_for_kb)}")
            logger.debug(
                f"URL Upload: Does team have 'knowledge'? {'knowledge' in dir(team_for_kb)}"
            )
            if hasattr(team_for_kb, "knowledge"):
                logger.debug(
                    f"URL Upload: Team knowledge object: {type(team_for_kb.knowledge)}"
                )
                logger.debug(
                    f"URL Upload: Team knowledge attributes: {dir(team_for_kb.knowledge)}"
                )
                logger.debug(
                    f"URL Upload: Does knowledge have 'vector_db'? {'vector_db' in dir(team_for_kb.knowledge)}"
                )
                if hasattr(team_for_kb.knowledge, "vector_db"):
                    logger.debug(
                        f"URL Upload: Vector DB object: {type(team_for_kb.knowledge.vector_db)}"
                    )
                    logger.debug(
                        f"URL Upload: Vector DB attributes: {dir(team_for_kb.knowledge.vector_db)}"
                    )
        else:
            logger.warning("URL Upload: Team object not found in session state!")

        if st.sidebar.button("Add URL", key="add_url_button"):
            if team_for_kb:
                try:
                    with st.spinner(f"Processing {website_url}..."):
                        web_docs = WebsiteReader().read(url=website_url)

                        if (
                            team_for_kb.knowledge
                            and hasattr(team_for_kb.knowledge, "vector_db")
                            and team_for_kb.knowledge.vector_db
                        ):  # Added hasattr check
                            if web_docs:
                                logger.info(
                                    f"Attempting to insert {len(web_docs)} Web documents into vector DB."
                                )
                                team_for_kb.knowledge.vector_db.insert(
                                    documents=web_docs
                                )
                                st.toast(
                                    f"✅ Added content from {website_url} to knowledge base.",
                                    icon="🔗",
                                )
                            else:
                                st.toast(
                                    f"⚠️ No readable content found at {website_url}.",
                                    icon="⚠️",
                                )
                        else:
                            logger.warning(
                                "URL Upload: Knowledge base or vector store not available on team object."
                            )  # Log warning
                            st.toast(
                                "Knowledge base vector store not available.", icon="🔥"
                            )

                except Exception as e:
                    logger.error(
                        f"Error adding URL: {e}", exc_info=True
                    )  # Log stack trace
                    st.toast(f"❌ Error adding URL: {e}", icon="🔥")
            else:
                st.toast(
                    "Team not initialized. Please wait or refresh.", icon="⚠️"
                )  # FIX: Updated message

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🔄 New Chat", key="new_chat"):
            restart_agent()
    with col2:
        fn = "llm_os_chat_history.md"
        current_session_id = st.session_state.get("llm_os_session_id")
        if current_session_id:
            fn = f"llm_os_{str(current_session_id)[:8]}.md"
        if st.download_button(
            "💾 Export Chat",
            export_chat_history(),
            file_name=fn,
            mime="text/markdown",
            key="export_chat",
        ):
            st.sidebar.success("Chat history exported!")

    ####################################################################
    # Initialize Team (with Session Management Logic)
    ####################################################################
    llm_os_team: Optional[Team] = None
    team_should_initialize = False

    # Condition 1: Team object not in session state
    if "llm_os_team" not in st.session_state or st.session_state.llm_os_team is None:
        team_should_initialize = True
        logger.info("Reason: Team not found in session state.")

    # Condition 2: Configuration mismatch
    # Compare current_config with the config used for the *last* initialization
    elif st.session_state.get("last_llm_os_config") != current_config:
        team_should_initialize = True
        logger.info("Reason: Config mismatch.")
        logger.debug(f"Stored Config: {st.session_state.get('last_llm_os_config')}")
        logger.debug(f"Current Config: {current_config}")

    if team_should_initialize:
        logger.info(
            "---*--- Creating/Re-initializing LLM OS Team (Config changed or first run) ---*---"
        )
        # Get the session ID from state (might have been set by selector)
        session_id_to_load = st.session_state.get("llm_os_session_id")

        # --- Add logic to load most recent session on initial load --- Start ---
        if session_id_to_load is None and "llm_os_team" not in st.session_state:
            logger.info(
                "Initial load detected. Attempting to load the most recent session."
            )
            try:
                # Instantiate storage to check existing sessions
                # Ensure table_name matches the one used in get_llm_os
                # Revert to SqliteStorage and explicitly set mode='agent'
                temp_storage = SqliteStorage(
                    db_file=str(SQLITE_DB_PATH),
                    table_name="team_sessions",
                    mode="agent",
                )  # Use SqliteStorage with mode='agent'
                all_sessions = temp_storage.get_all_sessions()
                if all_sessions:
                    # Sort by updated_at descending (assuming it exists and is comparable)
                    try:
                        all_sessions.sort(
                            key=lambda s: getattr(s, "updated_at", 0) or 0, reverse=True
                        )
                        most_recent_session_id = all_sessions[0].session_id
                        logger.info(
                            f"Found most recent session: {most_recent_session_id}"
                        )
                        session_id_to_load = most_recent_session_id
                        st.session_state["llm_os_session_id"] = (
                            session_id_to_load  # Update state immediately
                        )
                    except Exception as sort_e:
                        logger.warning(
                            f"Could not sort sessions by updated_at: {sort_e}. Loading may be unpredictable."
                        )
                        # Fallback: maybe take the last one in the list?
                        # most_recent_session_id = all_sessions[-1].session_id
                        # ... (add fallback if needed)
                else:
                    logger.info("No previous sessions found in storage.")
            except Exception as e:
                logger.error(f"Error trying to load most recent session: {e}")
        # --- Add logic to load most recent session on initial load --- End ---

        logger.debug(f"Passing config to get_llm_os: {current_config}")
        logger.debug(f"Attempting to load/create session: {session_id_to_load}")

        llm_os_team = get_llm_os(**current_config, session_id=session_id_to_load)
        # --- Add Log --- Start
        logger.debug(
            f"Team Initialization: Value returned by get_llm_os: {type(llm_os_team)}"
        )
        # --- Add Log --- End

        if llm_os_team:
            st.session_state["llm_os_team"] = llm_os_team
            st.session_state["llm_os_session_id"] = llm_os_team.team_id
            st.session_state["last_llm_os_config"] = (
                current_config  # Store the config used
            )
            st.session_state["messages"] = []
            logger.info(
                f"New LLM OS Team created/re-initialized. Instance: {id(llm_os_team)}"
            )
        else:
            st.error("Failed to initialize LLM OS Team. Please check logs.")
            st.session_state["llm_os_team"] = None
            st.session_state["llm_os_session_id"] = None
            st.session_state["last_llm_os_config"] = None
            return  # Stop execution if team fails
    else:
        llm_os_team = st.session_state.get("llm_os_team")
        if (
            llm_os_team
            and st.session_state.get("llm_os_session_id") != llm_os_team.team_id
        ):
            st.session_state["llm_os_session_id"] = llm_os_team.team_id
            logger.warning("Corrected session ID mismatch in state.")

    if not llm_os_team:
        st.error("LLM OS Team is not available. Cannot proceed.")
        logger.error(
            "Exiting main loop: llm_os_team is None after initialization block."
        )
        return

    if not hasattr(llm_os_team, "team_id") or not llm_os_team.team_id:
        st.warning("Team could not be initialized properly or has no session ID.")

    if "messages" not in st.session_state or not st.session_state["messages"]:
        logger.debug(f"Loading chat history for session: {llm_os_team.team_id}")
        st.session_state["messages"] = []  # Ensure it's a list
        try:
            if llm_os_team.memory:
                team_runs = llm_os_team.memory.get_runs(llm_os_team.team_id)
                if team_runs:
                    logger.debug(
                        f"Found {len(team_runs)} runs in memory for this session."
                    )
                    for run in team_runs:
                        if run.message and run.message.content:
                            add_message(run.message.role, run.message.content)
                        if run.response and run.response.content:
                            # Adapt based on RunResponse structure (check if tools are part of it)
                            add_message(
                                run.response.role,
                                run.response.content,
                                run.response.tools,
                            )
                else:
                    logger.debug("No runs found in memory for this session.")
            else:
                logger.warning("Team memory object not found, cannot load history.")
        except Exception as e:
            logger.error(f"Error loading chat history from memory: {e}", exc_info=True)
            st.warning("Could not load chat history.")

    ####################################################################
    # Main Chat Interface
    ####################################################################

    # Get user input
    if prompt := st.chat_input("🧠 Ask LLM OS anything!"):
        add_message("user", prompt)
        st.rerun()

    ####################################################################
    # Display chat history
    ####################################################################
    for idx, message in enumerate(st.session_state["messages"]):  # Add index for check
        if message["role"] in ["user", "assistant"]:
            _content = message.get("content")  # Use .get for safety
            if _content is not None:
                with st.chat_message(message["role"]):
                    is_last_assistant_message = (
                        message["role"] == "assistant"
                        and idx == len(st.session_state["messages"]) - 1
                    )
                    if (
                        "tool_calls" in message
                        and message["tool_calls"]
                        and is_last_assistant_message
                    ):
                        if not any(
                            m.get("role") == "assistant"
                            and "intermediate_steps_displayed" in m
                            for m in st.session_state["messages"][:-1]
                        ):
                            display_tool_calls(
                                st.container(), message["tool_calls"]
                            )  # Use st.container
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
            output_container = st.container()
            # Separate container for the final streaming text to allow updates
            final_response_container = output_container.empty()

            with st.spinner("🤔Thinking..."):
                response = ""
                # --- State for Tool Expanders --- Start
                # Dictionary to hold expander objects keyed by tool_call_id
                tool_expanders = {}
                # --- State for Tool Expanders --- End
                try:
                    run_response = llm_os_team.run(
                        question, stream=True, stream_intermediate_steps=True
                    )

                    for _resp_chunk in run_response:
                        event_type = (
                            _resp_chunk.event.lower()
                            if _resp_chunk.event
                            else "unknown_event"
                        )
                        # Log the event type and relevant details
                        log_details = f"Event Type: {event_type}"
                        tool_data = None
                        tool_call_id = None
                        tool_name = None
                        tool_args = None
                        tool_content = None

                        if _resp_chunk.tools:
                            # --- FIX: Get the LAST tool entry, as the list accumulates --- Start
                            tool_data = _resp_chunk.tools[
                                -1
                            ]  # Get the most recent tool data
                            # --- FIX: Get the LAST tool entry, as the list accumulates --- End
                            tool_call_id = tool_data.get("tool_call_id")
                            tool_name = tool_data.get("tool_name")
                            tool_args = tool_data.get("tool_args", {})
                            tool_content = tool_data.get("content")
                            if tool_name:
                                log_details += f", Tool: {tool_name}"
                            if tool_call_id:
                                log_details += f", ID: {tool_call_id}"
                            if tool_args and "member_id" in tool_args:
                                log_details += f", Member ID: {tool_args['member_id']}"

                        content_preview = None
                        if _resp_chunk.content and event_type != "runresponse":
                            content_preview = str(_resp_chunk.content)[:80] + (
                                "..." if len(str(_resp_chunk.content)) > 80 else ""
                            )
                            log_details += f", Content Preview: '{content_preview}'"
                        elif _resp_chunk.content and event_type == "runresponse":
                            log_details += ", Streaming final response chunk."

                        logger.info(f"Processing Stream Event -> {log_details}")

                        if event_type == "thinking":
                            output_container.markdown(
                                f"**🧠 Thinking:**\\n```\\n{_resp_chunk.content}\\n```\\n"
                            )
                            output_container.divider()

                        elif (
                            event_type == "toolcallstarted"
                            and tool_call_id
                            and tool_name
                        ):
                            expander_title = f"⚙️ Using Tool: `{tool_name}`"
                            member_id = tool_args.get("member_id")
                            task_desc = tool_args.get("task_description")
                            if tool_name == "transfer_task_to_member" and member_id:
                                expander_title = f"🚀 Delegating Task to `{member_id}`"

                            # Create and store the expander in the main container
                            expander = output_container.expander(
                                expander_title, expanded=False
                            )
                            tool_expanders[tool_call_id] = expander

                            # If delegation, add task description immediately
                            if tool_name == "transfer_task_to_member" and task_desc:
                                expander.markdown(f"**Task:**\\n> {task_desc}")

                        elif event_type == "toolcallcompleted" and tool_call_id:
                            expander = tool_expanders.get(tool_call_id)
                            if expander:
                                tool_name = tool_data.get(
                                    "tool_name", "Unknown Tool"
                                )  # Get name again for clarity
                                tool_content = tool_data.get(
                                    "content", "No content returned"
                                )
                                # Add results inside the specific expander
                                if tool_name == "transfer_task_to_member":
                                    member_id = tool_data.get("tool_args", {}).get(
                                        "member_id", "Unknown Agent"
                                    )
                                    expander.markdown(
                                        f"**✅ Final Result from `{member_id}`:**"
                                    )
                                    expander.markdown(
                                        f"```markdown\\n{tool_content}\\n```"
                                    )  # Use markdown for agent response
                                else:
                                    expander.markdown(f"**✅ Tool Result:**")
                                    if isinstance(tool_content, (dict, list)) or (
                                        isinstance(tool_content, str)
                                        and tool_content.strip().startswith(("[", "{"))
                                    ):
                                        try:
                                            import json

                                            expander.code(
                                                json.dumps(
                                                    json.loads(tool_content), indent=2
                                                )
                                                if isinstance(tool_content, str)
                                                else json.dumps(tool_content, indent=2),
                                                language="json",
                                            )
                                        except:
                                            expander.code(
                                                str(tool_content)
                                            )  # Fallback to plain text code
                                    else:
                                        expander.code(
                                            str(tool_content)
                                        )  # Default to code for non-structured results
                            else:
                                logger.warning(
                                    f"Could not find expander for tool_call_id: {tool_call_id}"
                                )
                                output_container.warning(
                                    f"Result for tool call {tool_call_id} (expander not found): {tool_content}"
                                )

                        elif (
                            event_type == "runresponse"
                            and _resp_chunk.content is not None
                        ):
                            response += _resp_chunk.content
                            final_response_container.markdown(response)

                    final_tools = (
                        llm_os_team.run_response.tools
                        if hasattr(llm_os_team, "run_response")
                        and llm_os_team.run_response
                        else None
                    )
                    final_content = response
                    intermediate_steps_displayed = bool(tool_expanders)
                    add_message(
                        "assistant",
                        final_content,
                        final_tools,
                        intermediate_steps_displayed=intermediate_steps_displayed,
                    )

                except Exception as e:
                    logger.exception(e)
                    error_message = f"Sorry, the team encountered an error: {str(e)}"
                    if (
                        not st.session_state.get("messages")
                        or st.session_state["messages"][-1].get("content")
                        != error_message
                    ):
                        add_message("assistant", error_message)
                    final_response_container.error(error_message)

    elif not llm_os_team and last_message and last_message.get("role") == "user":
        st.error("Team not initialized. Please wait or refresh the page.")
    ####################################################################
    # About section
    ####################################################################
    about_widget()  # Keep if desired


if __name__ == "__main__":
    main()
