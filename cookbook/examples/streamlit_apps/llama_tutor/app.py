import nest_asyncio
import streamlit as st
from agents import tutor_agent
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
    page_title="Llama Tutor: Learn Anything",
    page_icon=":book:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load custom CSS with dark mode support
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def main() -> None:
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>Llama Tutor</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Your intelligent answer engine powered by Agno</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model configuration - always use Llama 3.3 70B
    ####################################################################
    model_id = "groq:llama-3.3-70b-versatile"

    ####################################################################
    # Education level selector
    ####################################################################
    education_levels = [
        "Elementary School",
        "Middle School",
        "High School",
        "College",
        "Undergrad",
        "Graduate",
    ]

    selected_education_level = st.sidebar.selectbox(
        "Education Level",
        options=education_levels,
        index=2,  # Default to High School
        key="education_level_selector",
    )

    # Store the education level in session state
    if "education_level" not in st.session_state:
        st.session_state["education_level"] = selected_education_level
    elif st.session_state["education_level"] != selected_education_level:
        st.session_state["education_level"] = selected_education_level
        # Reset the agent if education level changes
        if "llama_tutor" in st.session_state:
            st.session_state["llama_tutor"] = None

    ####################################################################
    # Initialize Agent
    ####################################################################
    llama_tutor: Agent
    if (
        "llama_tutor" not in st.session_state
        or st.session_state["llama_tutor"] is None
        or st.session_state.get("current_model") != model_id
    ):
        logger.info("---*--- Creating new Llama Tutor agent ---*---")
        llama_tutor = tutor_agent(
            model_id=model_id, education_level=st.session_state["education_level"]
        )
        st.session_state["llama_tutor"] = llama_tutor
        st.session_state["current_model"] = model_id
    else:
        llama_tutor = st.session_state["llama_tutor"]

    ####################################################################
    # Load Agent Session from the database
    ####################################################################
    try:
        st.session_state["llama_tutor_session_id"] = llama_tutor.load_session()
    except Exception:
        st.warning("Could not create Agent session, is the database running?")
        return

    ####################################################################
    # Load runs from memory
    ####################################################################
    agent_runs = llama_tutor.memory.runs
    if len(agent_runs) > 0:
        logger.debug("Loading run history")
        st.session_state["messages"] = []
        for _run in agent_runs:
            if _run.message is not None:
                add_message(_run.message.role, _run.message.content)
            if _run.response is not None:
                add_message("assistant", _run.response.content, _run.response.tools)
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
    if prompt := st.chat_input("✨ What would you like to learn about?"):
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
            with st.spinner(":book: Llama Tutor is preparing your lesson..."):
                response = ""
                try:
                    # Run the agent and stream the response
                    run_response = llama_tutor.run(question, stream=True)
                    for _resp_chunk in run_response:
                        # Display tool calls if available
                        if _resp_chunk.tools and len(_resp_chunk.tools) > 0:
                            display_tool_calls(tool_calls_container, _resp_chunk.tools)

                        # Display response
                        if _resp_chunk.content is not None:
                            response += _resp_chunk.content
                            resp_container.markdown(response)

                    add_message("assistant", response, llama_tutor.run_response.tools)
                except Exception as e:
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)

    ####################################################################
    # Session selector
    ####################################################################
    session_selector_widget(llama_tutor, model_id)
    rename_session_widget(llama_tutor)

    ####################################################################
    # About section
    ####################################################################
    about_widget()


if __name__ == "__main__":
    main()
