import asyncio

import nest_asyncio
import streamlit as st
from agno.team import Team
from agno.utils.log import logger
from css import CUSTOM_CSS
from uagi import UAgIConfig, create_uagi, uagi_memory
from utils import (
    about_agno,
    add_message,
    display_tool_calls,
    example_inputs,
    initialize_session_state,
    knowledge_widget,
    selected_agents,
    selected_model,
    selected_tools,
    session_selector,
    show_user_memories,
    utilities_widget,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="UAgI",
    page_icon="💎",
    layout="wide",
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


async def header():
    st.markdown(
        "<h1 class='heading'>Universal Agent Interface</h1>", unsafe_allow_html=True
    )
    st.markdown(
        "<p class='subheading'>A Universal Interface for orchestrating multiple Agents</p>",
        unsafe_allow_html=True,
    )


async def body() -> None:
    ####################################################################
    # Initialize User and Session State
    ####################################################################
    user_id = st.sidebar.text_input(":technologist: User Id", value="Ava")

    ####################################################################
    # Select Model
    ####################################################################
    model_id = await selected_model()

    ####################################################################
    # Select Tools
    ####################################################################
    tools = await selected_tools()

    ####################################################################
    # Select Team Members
    ####################################################################
    agents = await selected_agents()

    ####################################################################
    # Create UAgI
    ####################################################################
    uagi_config = UAgIConfig(
        user_id=user_id, model_id=model_id, tools=tools, agents=agents
    )

    # Check if UAgI instance should be recreated
    recreate_uagi = (
        "uagi" not in st.session_state
        or st.session_state.get("uagi") is None
        or st.session_state.get("uagi_config") != uagi_config
    )

    # Create UAgI instance if it doesn't exist or configuration has changed
    uagi: Team
    if recreate_uagi:
        logger.info("---*--- Creating UAgI instance ---*---")
        uagi = create_uagi(uagi_config)
        st.session_state["uagi"] = uagi
        st.session_state["uagi_config"] = uagi_config
        logger.info(f"---*--- UAgI instance created ---*---")
    else:
        uagi = st.session_state["uagi"]
        logger.info(f"---*--- UAgI instance exists ---*---")

    ####################################################################
    # Load Agent Session from the database
    ####################################################################
    try:
        logger.info(f"---*--- Loading UAgI session ---*---")
        st.session_state["session_id"] = uagi.load_session()
    except Exception:
        st.warning("Could not create UAgI session, is the database running?")
        return
    logger.info(f"---*--- UAgI session: {st.session_state.get('session_id')} ---*---")

    ####################################################################
    # Load agent runs (i.e. chat history) from memory if messages is not empty
    ####################################################################
    chat_history = uagi.get_messages_for_session()
    if len(chat_history) > 0:
        logger.info("Loading messages")
        # Clear existing messages
        st.session_state["messages"] = []
        # Loop through the runs and add the messages to the messages list
        for message in chat_history:
            if message.role == "user":
                await add_message(message.role, str(message.content))
            if message.role == "assistant":
                await add_message("assistant", str(message.content), message.tool_calls)

    ####################################################################
    # Get user input
    ####################################################################
    if prompt := st.chat_input("✨ How can I help, bestie?"):
        await add_message("user", prompt)

    ####################################################################
    # Show example inputs
    ####################################################################
    await example_inputs()

    ####################################################################
    # Show user memories
    ####################################################################
    await show_user_memories(uagi_memory, user_id)

    ####################################################################
    # Display agent messages
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
        user_message = last_message["content"]
        logger.info(f"Responding to message: {user_message}")
        with st.chat_message("assistant"):
            # Create container for tool calls
            tool_calls_container = st.empty()
            resp_container = st.empty()
            with st.spinner(":thinking_face: Thinking..."):
                response = ""
                try:
                    # Run the agent and stream the response
                    run_response = await uagi.arun(
                        user_message, stream=True, stream_intermediate_steps=True
                    )
                    async for resp_chunk in run_response:
                        # Display tool calls if available
                        if resp_chunk.tools and len(resp_chunk.tools) > 0:
                            display_tool_calls(tool_calls_container, resp_chunk.tools)

                        # Display response if available and event is RunResponse
                        if (
                            resp_chunk.event == "RunResponse"
                            and resp_chunk.content is not None
                        ):
                            response += resp_chunk.content
                            resp_container.markdown(response)

                    # Add the response to the messages
                    if uagi.run_response is not None:
                        await add_message(
                            "assistant", response, uagi.run_response.tools
                        )
                    else:
                        await add_message("assistant", response)
                except Exception as e:
                    logger.error(f"Error during agent run: {str(e)}", exc_info=True)
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    await add_message("assistant", error_message)
                    st.error(error_message)

    ####################################################################
    # Knowledge widget
    ####################################################################
    await knowledge_widget(uagi)

    ####################################################################
    # Session selector
    ####################################################################
    await session_selector(uagi, uagi_config)

    ####################################################################
    # About section
    ####################################################################
    await utilities_widget(uagi)


async def main():
    await initialize_session_state()
    await header()
    await body()
    await about_agno()


if __name__ == "__main__":
    asyncio.run(main())
