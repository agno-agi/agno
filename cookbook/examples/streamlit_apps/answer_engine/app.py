import nest_asyncio
import streamlit as st
from agents import get_sage
from agno.agent import Agent
from agno.utils.log import logger
from utils import (
    CUSTOM_CSS,
    about_widget,
    add_message,
    display_tool_calls,
    rename_session_widget,
    session_selector_widget,
    sidebar_widget,
)

nest_asyncio.apply()

# Page configuration
st.set_page_config(
    page_title="Sage: The Answer Engine",
    page_icon=":crystal_ball:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load custom CSS with dark mode support
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def main() -> None:
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>Sage</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Your intelligent answer engine powered by Agno</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    model_options = {
        "llama-3.3-70b": "groq:llama-3.3-70b-versatile",
        "gpt-4o": "openai:gpt-4o",
        "o3-mini": "openai:o3-mini",
        "gemini-2.0-flash-exp": "google:gemini-2.0-flash-exp",
        "claude-3-5-sonnet": "anthropic:claude-3-5-sonnet-20241022",
    }
    selected_model = st.sidebar.selectbox(
        "Choose a model",
        options=list(model_options.keys()),
        index=0,
        key="model_selector",
    )
    model_id = model_options[selected_model]

    ####################################################################
    # Initialize Agent
    ####################################################################
    sage: Agent
    if (
        "sage" not in st.session_state
        or st.session_state["sage"] is None
        or st.session_state.get("current_model") != model_id
    ):
        logger.info("---*--- Creating new Sage agent ---*---")
        sage = get_sage(model_id=model_id)
        st.session_state["sage"] = sage
        st.session_state["current_model"] = model_id
        # Initialize messages array if needed
        if "messages" not in st.session_state:
            st.session_state["messages"] = []
    else:
        sage = st.session_state["sage"]

    ####################################################################
    # Load Agent Session from the database
    ####################################################################
    # Initialize session state
    if "sage_session_id" not in st.session_state:
        st.session_state["sage_session_id"] = None

    # Attempt to load or create a session
    if not st.session_state["sage_session_id"]:
        try:
            logger.info("---*--- Loading Sage session ---*---")
            st.session_state["sage_session_id"] = sage.load_session()
            logger.info(
                f"---*--- Sage session: {st.session_state['sage_session_id']} ---*---"
            )
        except Exception as e:
            logger.error(f"Session load error: {str(e)}")
            st.warning("Database connection unavailable. Running in memory-only mode.")
            # Generate a temporary session ID to allow the app to function without storage
            if not st.session_state["sage_session_id"]:
                import uuid

                st.session_state["sage_session_id"] = f"temp-{str(uuid.uuid4())}"
                logger.info(
                    f"---*--- Created temporary session: {st.session_state['sage_session_id']} ---*---"
                )

    ####################################################################
    # Load runs from memory
    ####################################################################
    # Initialize the messages array if not already done
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Only try to load runs from memory if we have a valid session and no messages yet
    if (
        len(st.session_state["messages"]) == 0
        and hasattr(sage, "memory")
        and sage.memory is not None
    ):
        agent_runs = []
        # Check if memory is a dict or an object with runs attribute
        if isinstance(sage.memory, dict) and "runs" in sage.memory:
            agent_runs = sage.memory["runs"]
        elif hasattr(sage.memory, "runs"):
            agent_runs = sage.memory.runs

        # Load messages from agent runs
        if len(agent_runs) > 0:
            logger.debug("Loading run history")
            for _run in agent_runs:
                # Check if _run is an object with message attribute
                if hasattr(_run, "message") and _run.message is not None:
                    add_message(_run.message.role, _run.message.content)
                # Check if _run is an object with response attribute
                if hasattr(_run, "response") and _run.response is not None:
                    add_message("assistant", _run.response.content, _run.response.tools)
        else:
            logger.debug("No run history found")

    ####################################################################
    # Sidebar
    ####################################################################
    sidebar_widget()

    ####################################################################
    # Get user input
    ####################################################################
    if prompt := st.chat_input("✨ What would you like to know, bestie?"):
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
            with st.spinner(":crystal_ball: Sage is working its magic..."):
                response = ""
                try:
                    # Run the agent and stream the response
                    run_response = sage.run(question, stream=True)
                    for _resp_chunk in run_response:
                        # Display tool calls if available
                        if _resp_chunk.tools and len(_resp_chunk.tools) > 0:
                            display_tool_calls(tool_calls_container, _resp_chunk.tools)

                        # Display response
                        if _resp_chunk.content is not None:
                            response += _resp_chunk.content
                            resp_container.markdown(response)

                    add_message("assistant", response, sage.run_response.tools)
                except Exception as e:
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)

    ####################################################################
    # Session selector
    ####################################################################
    session_selector_widget(sage, model_id)
    rename_session_widget(sage)

    ####################################################################
    # About section
    ####################################################################
    about_widget()


if __name__ == "__main__":
    main()
