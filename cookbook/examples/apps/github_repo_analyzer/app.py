from os import getenv

import nest_asyncio
import streamlit as st
from agents import get_github_agent
from agno.agent import Agent
from agno.utils.log import logger
from utils import (
    CUSTOM_CSS,
    about_widget,
    add_message,
    display_tool_calls,
    sidebar_widget,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="GitHub Repo Analyzer",
    page_icon="👨‍💻",
    layout="wide",
)

# Load custom CSS with dark mode support
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def main() -> None:
    #####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-header'>👨‍💻 GitHub Repo Analyzer</h1>", unsafe_allow_html=True
    )
    st.markdown("Analyze GitHub repositories")

    ####################################################################
    # Initialize Agent
    ####################################################################
    github_agent: Agent
    if (
        "github_agent" not in st.session_state
        or st.session_state["github_agent"] is None
    ):
        logger.info("---*--- Creating new Github agent ---*---")
        github_agent = get_github_agent()
        st.session_state["github_agent"] = github_agent
        st.session_state["messages"] = []
        st.session_state["github_token"] = getenv("GITHUB_ACCESS_TOKEN")
    else:
        github_agent = st.session_state["github_agent"]

    ####################################################################
    # Load Agent Session from the database
    ####################################################################
    try:
        st.session_state["github_agent_session_id"] = github_agent.load_session()
    except Exception:
        st.warning("Could not create Agent session, is the database running?")
        return

    ####################################################################
    # Load runs from memory (v2 Memory) only on initial load
    ####################################################################
    if github_agent.memory is not None and not st.session_state.get("messages"):
        session_id = st.session_state.get("github_agent_session_id")
        # Fetch stored runs for this session
        agent_runs = github_agent.memory.get_runs(session_id)
        if agent_runs:
            logger.debug("Loading run history")
            st.session_state["messages"] = []
            for run_response in agent_runs:
                # Iterate through stored messages in the run
                for msg in run_response.messages or []:
                    if msg.role in ["user", "assistant"] and msg.content is not None:
                        # Include any tool calls attached to this message
                        add_message(
                            msg.role, msg.content, getattr(msg, "tool_calls", None)
                        )
        else:
            logger.debug("No run history found")
            st.session_state["messages"] = []

    ####################################################################
    # Sidebar
    ####################################################################
    sidebar_widget()

    ####################################################################
    # Get user input
    ####################################################################
    if prompt := st.chat_input("👋 Ask me about GitHub repositories!"):
        add_message("user", prompt)

    ####################################################################
    # Display chat history
    ####################################################################
    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            _content = message["content"]
            if _content is not None:
                with st.chat_message(message["role"]):
                    # Display tool calls if they exist in the message
                    if "tool_calls" in message and message["tool_calls"]:
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
            # Create container for tool calls
            tool_calls_container = st.empty()
            resp_container = st.empty()
            with st.spinner("🤔 Thinking..."):
                response = ""
                try:
                    # Run the agent and stream the response
                    run_response = github_agent.run(
                        question, stream=True, stream_intermediate_steps=True
                    )
                    for _resp_chunk in run_response:
                        # Display tool calls if available
                        if _resp_chunk.tools and len(_resp_chunk.tools) > 0:
                            display_tool_calls(tool_calls_container, _resp_chunk.tools)

                        # Display response if available and event is RunResponse
                        if (
                            _resp_chunk.event == "RunResponse"
                            and _resp_chunk.content is not None
                        ):
                            response += _resp_chunk.content
                            resp_container.markdown(response)

                    add_message("assistant", response, github_agent.run_response.tools)
                except Exception as e:
                    logger.exception(e)
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)

    ####################################################################
    # About section
    ####################################################################
    about_widget()


if __name__ == "__main__":
    main()
