import asyncio

import nest_asyncio
import streamlit as st
from agents import get_mcp_agent
from agno.utils.log import logger
from mcp_client import MCPClient
from utils import (
    about_widget,
    add_message,
    apply_theme,
    display_tool_calls,
    example_inputs,
    get_mcp_server_config,
    get_num_history_responses,
    get_selected_model,
    session_selector_widget,
    utilities_widget,
)

nest_asyncio.apply()
apply_theme()


async def main() -> None:
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
    mcp_server_id = mcp_server_config.id
    num_history_responses = get_num_history_responses()

    ####################################################################
    # Initialize MCP Client and Agent
    ####################################################################
    try:
        # Check if we need to reinitialize the MCP client
        if (
            "mcp_client" not in st.session_state
            or st.session_state.get("mcp_server_id") != mcp_server_id
            or getattr(st.session_state.get("mcp_client", None), "session", None)
            is None
        ):
            # # Clean up existing client if it exists
            # if "mcp_client" in st.session_state:
            #     logger.info("Cleaning up existing MCP client")
            #     await st.session_state["mcp_client"].cleanup()

            # Initialize new MCP client
            logger.info(f"Creating new MCPClient for {mcp_server_id}")
            st.session_state["mcp_client"] = MCPClient()

        mcp_client = st.session_state["mcp_client"]
        # Connect to the MCP server and get tools
        mcp_tools = await mcp_client.connect_to_server(mcp_server_config)

        # Initialize or retrieve the agent
        if (
            "mcp_agent" not in st.session_state
            or st.session_state["mcp_agent"] is None
            or st.session_state.get("current_model") != selected_model
            or st.session_state.get("mcp_server_id") != mcp_server_id
        ):
            logger.info("---*--- Creating new MCP Agent ---*---")
            mcp_agent = get_mcp_agent(
                model_str=selected_model,
                num_history_responses=num_history_responses,
                mcp_tools=[mcp_tools],
                mcp_server_ids=[mcp_server_id],
            )
            st.session_state["mcp_agent"] = mcp_agent
            st.session_state["current_model"] = selected_model
        else:
            mcp_agent = st.session_state["mcp_agent"]

        # Update the agent's MCP tools incase the session has been reinitialized
        mcp_agent.tools = [mcp_tools]
        ####################################################################
        # Load the current Agent session from the database
        ####################################################################
        try:
            st.session_state["mcp_agent_session_id"] = mcp_agent.load_session()
        except Exception as e:
            st.warning(
                f"Could not create Agent session: {str(e)}. Is the database running?"
            )
            return

        ####################################################################
        # Load agent runs (i.e. chat history) from memory
        ####################################################################
        agent_runs = mcp_agent.memory.runs
        if len(agent_runs) > 0:
            # If there are runs, load the messages
            logger.debug("Loading run history")
            st.session_state["messages"] = []
            # Loop through the runs and add the messages to the messages list
            for _run in agent_runs:
                if _run.message is not None:
                    add_message(_run.message.role, _run.message.content)
                if _run.response is not None:
                    add_message("assistant", _run.response.content, _run.response.tools)
        else:
            # If there are no runs, create an empty messages list
            logger.debug("No run history found")
            st.session_state["messages"] = []

        ####################################################################
        # Get user input
        ####################################################################
        if prompt := st.chat_input("✨ How can I help, bestie?"):
            add_message("user", prompt)

        ####################################################################
        # Show example inputs
        ####################################################################
        example_inputs(server_id=mcp_server_id)

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
            question = last_message["content"]
            with st.chat_message("assistant"):
                # Create container for tool calls
                tool_calls_container = st.empty()
                resp_container = st.empty()
                with st.spinner(":thinking_face: Thinking..."):
                    response = ""
                    try:
                        # Run the agent and stream the response
                        run_response = await mcp_agent.arun(question, stream=True)
                        async for _resp_chunk in run_response:
                            # Display tool calls if available
                            if _resp_chunk.tools and len(_resp_chunk.tools) > 0:
                                display_tool_calls(
                                    tool_calls_container, _resp_chunk.tools
                                )

                            # Display response
                            if _resp_chunk.content is not None:
                                response += _resp_chunk.content
                                resp_container.markdown(response)

                        add_message("assistant", response, mcp_agent.run_response.tools)
                    except Exception as e:
                        logger.error(f"Error during agent run: {str(e)}", exc_info=True)
                        error_message = f"Sorry, I encountered an error: {str(e)}"
                        add_message("assistant", error_message)
                        st.error(error_message)

        ####################################################################
        # Session selector
        ####################################################################
        session_selector_widget(
            agent=mcp_agent,
            model_str=selected_model,
            num_history_responses=num_history_responses,
            mcp_tools=[mcp_tools],
            mcp_server_ids=[mcp_server_id],
        )

        ####################################################################
        # About section
        ####################################################################
        utilities_widget(agent=mcp_agent)
        about_widget()

    except Exception as e:
        logger.error(f"Error during agent run: {str(e)}", exc_info=True)
        error_message = f"Sorry, I encountered an error: {str(e)}"
        add_message("assistant", error_message)
        st.error(error_message)
    finally:
        # Don't clean up resources here - we want to keep the connection alive
        # between Streamlit reruns. We'll clean up when we need to reinitialize.
        pass


if __name__ == "__main__":
    asyncio.run(main())
