from typing import List

import nest_asyncio
import streamlit as st
from agno.agent import Agent
from agno.document import Document
from agno.document.reader.pdf_reader import PDFReader
from agno.document.reader.website_reader import WebsiteReader
from agno.utils.log import logger
from os_agent import get_llm_os  # type: ignore

nest_asyncio.apply()

st.set_page_config(
    page_title="LLM OS",
    page_icon=":orange_heart:",
)
st.title("LLM OS")
st.markdown("##### :orange_heart: built using [Agno](https://github.com/agno-agi/agno)")


def main() -> None:
    """Main function to run the Streamlit app."""

    # Initialize session_state["messages"] before accessing it
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Sidebar for selecting model
    model_id = st.sidebar.selectbox("Select LLM", options=["gpt-4o"]) or "gpt-4o"
    if st.session_state.get("model_id") != model_id:
        st.session_state["model_id"] = model_id
        restart_agent()

    # Sidebar checkboxes for selecting tools
    st.sidebar.markdown("### Select Tools")

    # Enable Calculator
    if "calculator_enabled" not in st.session_state:
        st.session_state["calculator_enabled"] = True
    # Get calculator_enabled from session state if set
    calculator_enabled = st.session_state["calculator_enabled"]
    # Checkbox for enabling calculator
    calculator = st.sidebar.checkbox(
        "Calculator", value=calculator_enabled, help="Enable calculator."
    )
    if calculator_enabled != calculator:
        st.session_state["calculator_enabled"] = calculator
        calculator_enabled = calculator
        restart_agent()

    # Enable file tools
    if "file_tools_enabled" not in st.session_state:
        st.session_state["file_tools_enabled"] = True
    # Get file_tools_enabled from session state if set
    file_tools_enabled = st.session_state["file_tools_enabled"]
    # Checkbox for enabling shell tools
    file_tools = st.sidebar.checkbox(
        "File Tools", value=file_tools_enabled, help="Enable file tools."
    )
    if file_tools_enabled != file_tools:
        st.session_state["file_tools_enabled"] = file_tools
        file_tools_enabled = file_tools
        restart_agent()

    # Enable Web Search via DuckDuckGo
    if "ddg_search_enabled" not in st.session_state:
        st.session_state["ddg_search_enabled"] = True
    # Get ddg_search_enabled from session state if set
    ddg_search_enabled = st.session_state["ddg_search_enabled"]
    # Checkbox for enabling web search
    ddg_search = st.sidebar.checkbox(
        "Web Search",
        value=ddg_search_enabled,
        help="Enable web search using DuckDuckGo.",
    )
    if ddg_search_enabled != ddg_search:
        st.session_state["ddg_search_enabled"] = ddg_search
        ddg_search_enabled = ddg_search
        restart_agent()

    # Enable shell tools
    if "shell_tools_enabled" not in st.session_state:
        st.session_state["shell_tools_enabled"] = False
    # Get shell_tools_enabled from session state if set
    shell_tools_enabled = st.session_state["shell_tools_enabled"]
    # Checkbox for enabling shell tools
    shell_tools = st.sidebar.checkbox(
        "Shell Tools", value=shell_tools_enabled, help="Enable shell tools."
    )
    if shell_tools_enabled != shell_tools:
        st.session_state["shell_tools_enabled"] = shell_tools
        shell_tools_enabled = shell_tools
        restart_agent()

    # Sidebar checkboxes for selecting team members
    st.sidebar.markdown("### Select Team Members")

    # Enable Data Analyst
    if "data_analyst_enabled" not in st.session_state:
        st.session_state["data_analyst_enabled"] = False
    data_analyst_enabled = st.session_state["data_analyst_enabled"]
    data_analyst = st.sidebar.checkbox(
        "Data Analyst",
        value=data_analyst_enabled,
        help="Enable the Data Analyst agent for data related queries.",
    )
    if data_analyst_enabled != data_analyst:
        st.session_state["data_analyst_enabled"] = data_analyst
        st.session_state.pop("llm_os", None)  # Only remove the LLM OS instance
        st.rerun()

    # Enable Python Agent
    if "python_agent_enabled" not in st.session_state:
        st.session_state["python_agent_enabled"] = False
    python_agent_enabled = st.session_state["python_agent_enabled"]
    python_agent = st.sidebar.checkbox(
        "Python Agent",
        value=python_agent_enabled,
        help="Enable the Python Agent for writing and running python code.",
    )
    if python_agent_enabled != python_agent:
        st.session_state["python_agent_enabled"] = python_agent
        st.session_state.pop("llm_os", None)  # Only remove the LLM OS instance
        st.rerun()

    # Enable Research Agent
    if "research_agent_enabled" not in st.session_state:
        st.session_state["research_agent_enabled"] = False
    research_agent_enabled = st.session_state["research_agent_enabled"]
    research_agent = st.sidebar.checkbox(
        "Research Agent",
        value=research_agent_enabled,
        help="Enable the research agent (uses Exa).",
    )
    if research_agent_enabled != research_agent:
        st.session_state["research_agent_enabled"] = research_agent
        st.session_state.pop("llm_os", None)  # Only remove the LLM OS instance
        st.rerun()

    # Enable Investment Agent
    if "investment_agent_enabled" not in st.session_state:
        st.session_state["investment_agent_enabled"] = False
    investment_agent_enabled = st.session_state["investment_agent_enabled"]
    investment_agent = st.sidebar.checkbox(
        "Investment Agent",
        value=investment_agent_enabled,
        help="Enable the investment agent. NOTE: This is not financial advice.",
    )
    if investment_agent_enabled != investment_agent:
        st.session_state["investment_agent_enabled"] = investment_agent
        st.session_state.pop("llm_os", None)  # Only remove the LLM OS instance
        st.rerun()

    # Initialize the agent
    if "llm_os" not in st.session_state or st.session_state["llm_os"] is None:
        logger.info(f"---*--- Creating {model_id} LLM OS ---*---")
        try:
            llm_os: Agent = get_llm_os(
                model_id=model_id,
                calculator=calculator_enabled,
                ddg_search=ddg_search_enabled,
                file_tools=file_tools_enabled,
                shell_tools=shell_tools_enabled,
                data_analyst=data_analyst_enabled,
                python_agent_enable=python_agent_enabled,
                research_agent_enable=research_agent_enabled,
                investment_agent_enable=investment_agent_enabled,
            )
            st.session_state["llm_os"] = llm_os
        except RuntimeError as e:
            st.error(f"Database Error: {str(e)}")
            st.info(
                "Please make sure your PostgreSQL database is running at postgresql+psycopg://ai:ai@localhost:5532/ai"
            )
            return
    else:
        llm_os = st.session_state["llm_os"]

    # Create agent run (i.e. log to database) and save session_id in session state
    try:
        if llm_os.storage is None:
            st.session_state["llm_os_run_id"] = None
        else:
            st.session_state["llm_os_run_id"] = llm_os.new_session()
    except Exception as e:
        st.session_state["llm_os_run_id"] = None

    # Modify the chat history loading to work without storage
    if llm_os.memory and not st.session_state["messages"]:
        logger.debug("Loading chat history")
        st.session_state["messages"] = [
            {"role": message.role, "content": message.content}
            for message in llm_os.memory.messages
        ]
    elif not st.session_state["messages"]:
        logger.debug("No chat history found")
        st.session_state["messages"] = [
            {"role": "agent", "content": "Ask me questions..."}
        ]

    # Display chat history first (all previous messages)
    for message in st.session_state["messages"]:
        if message["role"] == "system":
            continue
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # Handle user input and generate responses
    if prompt := st.chat_input("Ask a question:"):
        # Display user message first
        with st.chat_message("user"):
            st.write(prompt)

        # Then display agent response
        with st.chat_message("agent"):
            # Create an empty container for the streaming response
            response_container = st.empty()
            with st.spinner("Thinking..."):  # Add spinner while generating response
                response = ""
                for chunk in llm_os.run(prompt, stream=True):
                    if chunk and chunk.content:
                        response += chunk.content
                        # Update the response in real-time
                        response_container.markdown(response)

        # Add messages to session state after completion
        st.session_state["messages"].append({"role": "user", "content": prompt})
        st.session_state["messages"].append({"role": "agent", "content": response})

    # Load LLM OS knowledge base
    if llm_os.knowledge:
        # -*- Add websites to knowledge base
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
                        llm_os.knowledge.load_documents(web_documents, upsert=True)
                    else:
                        st.sidebar.error("Could not read website")
                    st.session_state[f"{input_url}_uploaded"] = True
                alert.empty()

        # Add PDFs to knowledge base
        if "file_uploader_key" not in st.session_state:
            st.session_state["file_uploader_key"] = 100

        uploaded_file = st.sidebar.file_uploader(
            "Add a PDF :page_facing_up:",
            type="pdf",
            key=st.session_state["file_uploader_key"],
        )
        if uploaded_file is not None:
            alert = st.sidebar.info("Processing PDF...", icon="🧠")
            auto_rag_name = uploaded_file.name.split(".")[0]
            if f"{auto_rag_name}_uploaded" not in st.session_state:
                reader = PDFReader()
                auto_rag_documents: List[Document] = reader.read(uploaded_file)
                if auto_rag_documents:
                    llm_os.knowledge.load_documents(auto_rag_documents, upsert=True)
                else:
                    st.sidebar.error("Could not read PDF")
                st.session_state[f"{auto_rag_name}_uploaded"] = True
            alert.empty()

    if llm_os.knowledge and llm_os.knowledge.vector_db:
        if st.sidebar.button("Clear Knowledge Base"):
            llm_os.knowledge.vector_db.delete()
            st.sidebar.success("Knowledge base cleared")

    # Show team member memory
    if llm_os.team and len(llm_os.team) > 0:
        for team_member in llm_os.team:
            if team_member.memory and len(team_member.memory.messages) > 0:
                with st.status(
                    f"{team_member.name} Memory", expanded=False, state="complete"
                ):
                    with st.container():
                        _team_member_memory_container = st.empty()
                        _team_member_memory_container.json(
                            team_member.memory.get_messages()
                        )

    # Remove the run history section entirely
    if st.sidebar.button("New Run"):
        restart_agent()


def restart_agent():
    """Restart the agent and reset session state."""
    logger.debug("---*--- Restarting Agent ---*---")
    for key in ["llm_os", "messages"]:  # Removed "llm_os_run_id"
        st.session_state.pop(key, None)
    st.session_state["url_scrape_key"] = st.session_state.get("url_scrape_key", 0) + 1
    st.session_state["file_uploader_key"] = (
        st.session_state.get("file_uploader_key", 100) + 1
    )
    st.rerun()


main()
