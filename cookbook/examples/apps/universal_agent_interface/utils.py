import json
from typing import Any, Dict, List, Optional

import streamlit as st
from agno.document import Document
from agno.document.reader import Reader
from agno.document.reader.csv_reader import CSVReader
from agno.document.reader.docx_reader import DocxReader
from agno.document.reader.pdf_reader import PDFReader
from agno.document.reader.text_reader import TextReader
from agno.document.reader.website_reader import WebsiteReader
from agno.memory.v2 import Memory, UserMemory
from agno.team import Team
from agno.utils.log import logger
from uagi import UAgIConfig, create_uagi


async def initialize_session_state():
    logger.info(f"---*--- Initializing session state ---*---")
    if "uagi" not in st.session_state:
        st.session_state["uagi"] = None
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = None
    if "messages" not in st.session_state:
        st.session_state["messages"] = []


async def add_message(
    role: str,
    content: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    intermediate_steps_displayed: bool = False,
) -> None:
    """Safely add a message to the session state"""
    if role == "user":
        logger.info(f"👤  {role}: {content}")
    else:
        logger.info(f"🤖  {role}: {content}")
    st.session_state["messages"].append(
        {
            "role": role,
            "content": content,
            "tool_calls": tool_calls,
            "intermediate_steps_displayed": intermediate_steps_displayed,
        }
    )


async def selected_model() -> str:
    """Display a model selector in the sidebar."""
    model_options = {
        "claude-3-7-sonnet": "anthropic:claude-3-7-sonnet-latest",
        "gpt-4o": "openai:gpt-4o",
        "gemini-2.5-pro": "google:gemini-2.5-pro-preview-03-25",
        "llama-4-scout": "groq:meta-llama/llama-4-scout-17b-16e-instruct",
    }

    selected_model_key = st.sidebar.selectbox(
        "Select a model",
        options=list(model_options.keys()),
        index=0,  # Default to claude-3-7-sonnet
        key="model_selector",
    )
    model_id = model_options[selected_model_key]
    return model_id


async def selected_tools() -> List[str]:
    """Display a tool selector in the sidebar."""
    tool_options = {
        "Web Search (DDG)": "ddg_search",
        "File I/O": "file_tools",
        "Shell Access": "shell_tools",
    }
    selected_tools = st.sidebar.multiselect(
        "Select Tools",
        options=list(tool_options.keys()),
        default=list(tool_options.keys()),
        key="tool_selector",
    )
    return [tool_options[tool] for tool in selected_tools]


async def selected_agents() -> List[str]:
    """Display a selector for agents in the sidebar."""
    agent_options = {
        "Calculator": "calculator",
        "Data Analyst": "data_analyst",
        "Python Agent": "python_agent",
        "Research Agent": "research_agent",
        "Investment Agent": "investment_agent",
    }
    selected_agents = st.sidebar.multiselect(
        "Select Agents",
        options=list(agent_options.keys()),
        default=list(agent_options.keys()),
        key="agent_selector",
    )
    return [agent_options[agent] for agent in selected_agents]


async def show_user_memories(uagi_memory: Memory, user_id: str) -> None:
    """Show use memories in a streamlit container."""

    with st.container():
        user_memories = uagi_memory.get_user_memories(user_id=user_id)
        with st.expander(f"💭 Memories for {user_id}", expanded=False):
            if len(user_memories) > 0:
                # Create a dataframe from the memories
                memory_data = {
                    "Memory": [memory.memory for memory in user_memories],
                    "Topics": [
                        ", ".join(memory.topics) if memory.topics else ""
                        for memory in user_memories
                    ],
                    "Last Updated": [
                        memory.last_updated.strftime("%Y-%m-%d %H:%M")
                        if memory.last_updated
                        else ""
                        for memory in user_memories
                    ],
                }

                # Display as a table with custom styling
                st.dataframe(
                    memory_data,
                    use_container_width=True,
                    column_config={
                        "Memory": st.column_config.TextColumn("Memory", width="medium"),
                        "Topics": st.column_config.TextColumn("Topics", width="small"),
                        "Last Updated": st.column_config.TextColumn(
                            "Last Updated", width="small"
                        ),
                    },
                    hide_index=True,
                )
            else:
                st.info("No memories found, tell me about yourself!")

            col1, col2 = st.columns([0.5, 0.5])
            with col1:
                if st.button("Clear all memories", key="clear_all_memories"):
                    await add_message("user", "Clear all my memories")
                    if "memory_refresh_count" not in st.session_state:
                        st.session_state.memory_refresh_count = 0
                    st.session_state.memory_refresh_count += 1
            with col2:
                if st.button("Refresh memories", key="refresh_memories"):
                    if "memory_refresh_count" not in st.session_state:
                        st.session_state.memory_refresh_count = 0
                    st.session_state.memory_refresh_count += 1


async def example_inputs() -> None:
    """Show example inputs on the sidebar."""
    with st.sidebar:
        st.markdown("#### :thinking_face: Try me!")
        if st.button("Hi"):
            await add_message(
                "user",
                "Hi",
            )

        if st.button("My name is Ava and I live in Greenwich Village"):
            await add_message(
                "user",
                "My name is Ava and I live in Greenwich Village",
            )

        if st.button("Calculate cost of a pizza party"):
            await add_message(
                "user",
                "Calculate the total cost of ordering pizzas for 25 people, assuming each person eats 3 slices, each pizza has 8 slices, and one pizza costs $15.95. After calculating the total cost, add 20% for tip and 10% for taxes. Also recommend some good places around me",
            )

        if st.button("Analyze a CSV file"):
            await add_message(
                "user",
                "Analyze this CSV file and show me the most popular movies: https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
            )

        if st.button("Translate a sentence into emojis"):
            await add_message(
                "user",
                "Write a Python function that translates a given sentence into emojis, replacing words like “happy,” “sad,” “pizza,” and “party” with relevant emojis. Test it with the sentence: “I am happy because I am learning to build agents with Agno”",
            )

        if st.button("Why Do Cats Love Boxes?"):
            await add_message(
                "user",
                "Research and report scientifically-backed explanations for why cats seem irresistibly drawn to cardboard boxes.",
            )

        if st.button("Chocolate Stocks Sweetness Analysis"):
            await add_message(
                "user",
                "Perform financial analysis comparing Hershey's and Lindt stocks to suggest which company might be a sweeter investment choice based on profitability, market trends, and valuation.",
            )


async def about_agno():
    """Show information about Agno in the sidebar"""
    with st.sidebar:
        st.markdown("### About Agno ✨")
        st.markdown("""
        Agno is a lightweight library for building Reasoning Agents.

        [GitHub](https://github.com/agno-agi/agno) | [Docs](https://docs.agno.com)
        """)

        st.markdown("### Need Help?")
        st.markdown(
            "If you have any questions, catch us on [discord](https://agno.link/discord) or post in the community [forum](https://agno.link/community)."
        )


def is_json(myjson):
    """Check if a string is valid JSON"""
    try:
        json.loads(myjson)
    except (ValueError, TypeError):
        return False
    return True


def display_tool_calls(tool_calls_container, tools):
    """Display tool calls in a streamlit container with expandable sections.

    Args:
        tool_calls_container: Streamlit container to display the tool calls
        tools: List of tool call dictionaries containing name, args, content, and metrics
    """
    try:
        with tool_calls_container.container():
            # Handle single tool_call dict case
            if isinstance(tools, dict):
                tools = [tools]
            elif not isinstance(tools, list):
                logger.warning(
                    f"Unexpected tools format: {type(tools)}. Skipping display."
                )
                return

            for tool_call in tools:
                # Normalize access to tool details
                tool_name = tool_call.get("tool_name") or tool_call.get(
                    "name", "Unknown Tool"
                )
                tool_args = tool_call.get("tool_args") or tool_call.get("args", {})
                content = tool_call.get("content", None)
                metrics = tool_call.get("metrics", None)

                # Add timing information safely
                execution_time_str = "N/A"
                try:
                    if metrics is not None and hasattr(metrics, "time"):
                        execution_time = metrics.time
                        if execution_time is not None:
                            execution_time_str = f"{execution_time:.4f}s"
                except Exception as e:
                    logger.error(f"Error getting tool metrics time: {str(e)}")
                    pass  # Keep default "N/A"

                # Check if this is a transfer task
                is_task_transfer = "transfer_task_to_member" in tool_name
                is_memory_task = "user_memory" in tool_name
                expander_title = "🛠️"
                if is_task_transfer:
                    member_id = tool_args.get("member_id")
                    expander_title = f"🔄 {member_id.title()}"
                elif is_memory_task:
                    expander_title = f"💭 Updating Memory"
                else:
                    expander_title = f"🛠️ {tool_name.replace('_', ' ').title()}"

                if execution_time_str != "N/A":
                    expander_title += f" ({execution_time_str})"

                with st.expander(
                    expander_title,
                    expanded=False,
                ):
                    # Show query/code/command with syntax highlighting
                    if isinstance(tool_args, dict):
                        if "query" in tool_args:
                            st.code(tool_args["query"], language="sql")
                        elif "code" in tool_args:
                            st.code(tool_args["code"], language="python")
                        elif "command" in tool_args:
                            st.code(tool_args["command"], language="bash")

                    # Display arguments if they exist and are not just the code/query shown above
                    args_to_show = {
                        k: v
                        for k, v in tool_args.items()
                        if k not in ["query", "code", "command"]
                    }
                    if args_to_show:
                        st.markdown("**Arguments:**")
                        try:
                            st.json(args_to_show)
                        except Exception:
                            st.write(args_to_show)  # Fallback for non-serializable args

                    if content is not None:
                        try:
                            st.markdown("**Results:**")
                            if isinstance(content, str) and is_json(content):
                                st.json(content)
                            else:
                                st.write(content)
                        except Exception as e:
                            logger.debug(f"Could not display tool content: {e}")
                            st.error("Could not display tool content.")
    except Exception as e:
        logger.error(f"Error displaying tool calls: {str(e)}")
        tool_calls_container.error("Failed to display tool results")


async def knowledge_widget(uagi: Team) -> None:
    """Display a knowledge widget in the sidebar."""

    if uagi is not None and uagi.knowledge is not None:
        # Add websites to knowledge base
        if "url_scrape_key" not in st.session_state:
            st.session_state["url_scrape_key"] = 0
        input_url = st.sidebar.text_input(
            "Add URL to Knowledge Base",
            type="default",
            key=st.session_state["url_scrape_key"],
        )
        add_url_button = st.sidebar.button("Add URL")
        if add_url_button:
            if input_url is not None:
                alert = st.sidebar.info("Processing URLs...", icon="ℹ️")
                if f"{input_url}_scraped" not in st.session_state:
                    scraper = WebsiteReader(max_links=2, max_depth=1)
                    web_documents: List[Document] = scraper.read(input_url)
                    if web_documents:
                        uagi.knowledge.load_documents(web_documents, upsert=True)
                    else:
                        st.sidebar.error("Could not read website")
                    st.session_state[f"{input_url}_uploaded"] = True
                alert.empty()

        # Add documents to knowledge base
        if "file_uploader_key" not in st.session_state:
            st.session_state["file_uploader_key"] = 100
        uploaded_file = st.sidebar.file_uploader(
            "Add a Document (.pdf, .csv, .txt, or .docx)",
            key=st.session_state["file_uploader_key"],
        )
        if uploaded_file is not None:
            alert = st.sidebar.info("Processing document...", icon="🧠")
            document_name = uploaded_file.name.split(".")[0]
            if f"{document_name}_uploaded" not in st.session_state:
                file_type = uploaded_file.name.split(".")[-1].lower()

                reader: Reader
                if file_type == "pdf":
                    reader = PDFReader()
                elif file_type == "csv":
                    reader = CSVReader()
                elif file_type == "txt":
                    reader = TextReader()
                elif file_type == "docx":
                    reader = DocxReader()
                else:
                    st.sidebar.error("Unsupported file type")
                    return
                uploaded_file_documents: List[Document] = reader.read(uploaded_file)
                if uploaded_file_documents:
                    uagi.knowledge.load_documents(uploaded_file_documents, upsert=True)
                else:
                    st.sidebar.error("Could not read document")
                st.session_state[f"{document_name}_uploaded"] = True
            alert.empty()

        # Load and delete knowledge
        if st.sidebar.button("🗑️ Delete Knowledge"):
            uagi.knowledge.delete()
            st.sidebar.success("Knowledge deleted!")


async def session_selector(uagi: Team, uagi_config: UAgIConfig) -> None:
    """Display a session selector in the sidebar, if a new session is selected, UAgI is restarted with the new session."""

    if not uagi.storage:
        return

    try:
        # Get all agent sessions.
        uagi_sessions = uagi.storage.get_all_sessions()
        if not uagi_sessions:
            st.sidebar.info("No saved sessions found.")
            return

        # Get session names if available, otherwise use IDs.
        sessions_list = []
        for session in uagi_sessions:
            session_id = session.session_id
            session_name = (
                session.session_data.get("session_name", None)
                if session.session_data
                else None
            )
            display_name = session_name if session_name else session_id
            sessions_list.append({"id": session_id, "display_name": display_name})

        # Display session selector.
        st.sidebar.markdown("#### 💬 Session")
        selected_session = st.sidebar.selectbox(
            "Session",
            options=[s["display_name"] for s in sessions_list],
            key="session_selector",
            label_visibility="collapsed",
        )
        # Find the selected session ID.
        selected_session_id = next(
            s["id"] for s in sessions_list if s["display_name"] == selected_session
        )
        # Update the agent session if it has changed.
        if st.session_state["session_id"] != selected_session_id:
            logger.info(f"---*--- Loading UAgI session: {selected_session_id} ---*---")
            st.session_state["uagi"] = create_uagi(
                config=uagi_config,
                session_id=selected_session_id,
            )
            st.rerun()

        # Show the rename session widget.
        container = st.sidebar.container()
        session_row = container.columns([3, 1], vertical_alignment="center")

        # Initialize session_edit_mode if needed.
        if "session_edit_mode" not in st.session_state:
            st.session_state.session_edit_mode = False

        # Show the session name.
        with session_row[0]:
            if st.session_state.session_edit_mode:
                new_session_name = st.text_input(
                    "Session Name",
                    value=uagi.session_name,
                    key="session_name_input",
                    label_visibility="collapsed",
                )
            else:
                st.markdown(f"Session Name: **{uagi.session_name}**")

        # Show the rename session button.
        with session_row[1]:
            if st.session_state.session_edit_mode:
                if st.button("✓", key="save_session_name", type="primary"):
                    if new_session_name:
                        uagi.rename_session(new_session_name)
                        st.session_state.session_edit_mode = False
                        container.success("Renamed!")
                        # Trigger a rerun to refresh the sessions list
                        st.rerun()
            else:
                if st.button("✎", key="edit_session_name"):
                    st.session_state.session_edit_mode = True
    except Exception as e:
        logger.error(f"Error in session selector: {str(e)}")
        st.sidebar.error("Failed to load sessions")


def export_chat_history():
    """Export chat history in markdown format.

    Returns:
        str: Formatted markdown string of the chat history
    """
    if "messages" not in st.session_state or not st.session_state["messages"]:
        return f"# UAgI - Chat History\n\nNo messages to export."

    chat_text = f"# UAgI - Chat History\n\n"
    for msg in st.session_state["messages"]:
        role_label = "🤖 Assistant" if msg["role"] == "assistant" else "👤 User"
        chat_text += f"### {role_label}\n{msg['content']}\n\n"

        # Include tool calls if present
        if msg.get("tool_calls"):
            chat_text += "#### Tool Calls:\n"
            for i, tool_call in enumerate(msg["tool_calls"]):
                tool_name = tool_call.get("name", "Unknown Tool")
                chat_text += f"**{i + 1}. {tool_name}**\n\n"
                if "arguments" in tool_call:
                    chat_text += (
                        f"Arguments: ```json\n{tool_call['arguments']}\n```\n\n"
                    )
                if "content" in tool_call:
                    chat_text += f"Results: ```\n{tool_call['content']}\n```\n\n"

    return chat_text


async def utilities_widget(uagi: Team) -> None:
    """Display a utilities widget in the sidebar."""
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🔄 Start New Chat"):
            restart_uagi()
    with col2:
        fn = f"uagi_chat_history.md"
        if "session_id" in st.session_state:
            fn = f"uagi_{st.session_state['session_id']}.md"
        if st.download_button(
            ":file_folder: Export Chat History",
            export_chat_history(),
            file_name=fn,
            mime="text/markdown",
        ):
            st.sidebar.success("Chat history exported!")


def restart_uagi():
    logger.debug("---*--- Restarting UAgI ---*---")
    st.session_state["uagi"] = None
    st.session_state["session_id"] = None
    st.session_state["messages"] = []
    if "url_scrape_key" in st.session_state:
        st.session_state["url_scrape_key"] += 1
    if "file_uploader_key" in st.session_state:
        st.session_state["file_uploader_key"] += 1
    st.rerun()
