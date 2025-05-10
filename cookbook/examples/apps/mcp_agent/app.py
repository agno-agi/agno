import asyncio

import nest_asyncio
import streamlit as st
from agents import get_mcp_agent, get_mcp_agent_with_tools
from agno.agent import Agent
from agno.utils.log import logger
from utils import (
    about_widget,
    add_message,
    apply_theme,
    display_tool_calls,
    example_inputs,
    get_mcp_server_config,
    get_num_history_responses,
    get_selected_model,
    initialize_agent_session_state,
    session_selector,
    utilities_widget,
)

nest_asyncio.apply()
apply_theme()

agent_name = "mcp_agent"


async def body() -> None:
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>Universal Agent Interface powered by MCP</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='subtitle'>A unified Agentic interface for MCP servers</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Settings
    ####################################################################
    selected_model = get_selected_model()
    mcp_server_config = get_mcp_server_config()
    if not mcp_server_config:
        st.warning(f"MCP server config is invalid.")
        return
    mcp_server_id = mcp_server_config.id
    num_history_responses = get_num_history_responses()

    ####################################################################
    # Initialize MCP Client and Agent
    ####################################################################
    mcp_agent: Agent
    try:
        # Initialize or retrieve the agent
        if (
            agent_name not in st.session_state
            or st.session_state[agent_name]["agent"] is None
            or st.session_state.get("current_model") != selected_model
            or st.session_state.get("mcp_server_id") != mcp_server_id
        ):
            logger.info("---*--- Creating new MCP Agent ---*---")
            mcp_agent = get_mcp_agent(
                model_id=selected_model,
                num_history_responses=num_history_responses,
                mcp_tools=[],
                mcp_server_ids=[mcp_server_id],
            )
            st.session_state[agent_name]["agent"] = mcp_agent
            st.session_state["current_model"] = selected_model
            st.session_state["mcp_server_id"] = mcp_server_id
        else:
            mcp_agent = st.session_state[agent_name]["agent"]

        ####################################################################
        # Load the current Agent session from the database
        ####################################################################
        try:
            st.session_state[agent_name]["session_id"] = mcp_agent.load_session()
        except Exception as e:
            st.warning(
                f"Could not create Agent session: {str(e)}. Is the database running?"
            )
            return

        ####################################################################
        # Load agent runs (i.e. chat history) from memory
        ####################################################################
        if mcp_agent.memory:
            agent_runs = mcp_agent.memory.runs
            if len(agent_runs) > 0:
                # If there are runs, load the messages
                logger.debug("Loading run history")
                # Clear existing messages
                st.session_state[agent_name]["messages"] = []
                # Loop through the runs and add the messages to the messages list
                for agent_run in agent_runs:
                    if agent_run.message is not None:
                        await add_message(
                            agent_name,
                            agent_run.message.role,
                            str(agent_run.message.content),
                        )
                    if agent_run.response is not None:
                        await add_message(
                            agent_name,
                            "assistant",
                            str(agent_run.response.content),
                            agent_run.response.tools,
                        )

        ####################################################################
        # Get user input
        ####################################################################
        if prompt := st.chat_input("✨ How can I help with your database, bestie?"):
            await add_message(agent_name, "user", prompt)

        ####################################################################
        # Show example inputs
        ####################################################################
        await example_inputs(server_id=mcp_server_id, agent_name=agent_name)

        ####################################################################
        # Display agent messages
        ####################################################################
        for message in st.session_state[agent_name]["messages"]:
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
            st.session_state[agent_name]["messages"][-1]
            if st.session_state[agent_name]["messages"]
            else None
        )
        if last_message and last_message.get("role") == "user":
            user_message = last_message["content"]
            logger.info(f"Responding to message: {user_message}")
            with st.chat_message("assistant"):
                tool_calls_container = st.empty()
                resp_container = st.empty()
                with st.spinner(":thinking_face: Thinking..."):
                    response = ""
                    try:
                        # Get current session ID from Streamlit state
                        current_session_id = st.session_state[agent_name].get(
                            "session_id"
                        )
                        logger.info(f"Using session ID: {current_session_id}")

                        async with get_mcp_agent_with_tools(
                            model_id=selected_model,
                            session_id=current_session_id,
                            num_history_responses=num_history_responses,
                            mcp_server_ids=[mcp_server_id],
                            server_config=mcp_server_config,
                        ) as temp_agent:
                            # Process the request with temporary agent that has full context
                            run_response = await temp_agent.arun(
                                user_message, stream=True
                            )
                            async for resp_chunk in run_response:
                                # Display tool calls if available
                                if resp_chunk.tools and len(resp_chunk.tools) > 0:
                                    display_tool_calls(
                                        tool_calls_container, resp_chunk.tools
                                    )

                                # Display response
                                if resp_chunk.content is not None:
                                    response += resp_chunk.content
                                    resp_container.markdown(response)

                            # Save the response to chat history in Streamlit
                            if temp_agent.run_response is not None:
                                await add_message(
                                    agent_name,
                                    "assistant",
                                    response,
                                    temp_agent.run_response.tools,
                                )
                            else:
                                await add_message(agent_name, "assistant", response)

                            # Update session ID in case it changed
                            # (This maintains continuity for the next query)
                            st.session_state[agent_name]["session_id"] = (
                                temp_agent.session_id
                            )

                    except Exception as e:
                        logger.error(f"Error during agent run: {str(e)}", exc_info=True)
                        error_message = f"Sorry, I encountered an error: {str(e)}"
                        await add_message(agent_name, "assistant", error_message)
                        st.error(error_message)

        ####################################################################
        # Session selector
        ####################################################################
        await session_selector(
            agent_name, mcp_agent, get_mcp_agent, selected_model, user_id=None
        )

        ####################################################################
        # About section
        ####################################################################
        await utilities_widget(agent_name, mcp_agent)
        about_widget()

    except Exception as e:
        logger.error(f"Error during agent run: {str(e)}", exc_info=True)
        error_message = f"Sorry, I encountered an error: {str(e)}"
        add_message(agent_name, "assistant", error_message)
        st.error(error_message)
    finally:
        # Don't clean up resources here - we want to keep the connection alive
        # between Streamlit reruns. We'll clean up when we need to reinitialize.
        pass


async def main():
    await initialize_agent_session_state(agent_name)
    await body()


if __name__ == "__main__":
    asyncio.run(main())
