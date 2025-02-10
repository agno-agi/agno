from typing import Optional

import streamlit as st
from agents import World, get_world_builder
from agno.agent import Agent
from agno.utils.log import logger
from utils import add_message, display_tool_calls, sidebar_widget

# set page config
st.set_page_config(
    page_title="World Building",
    page_icon=":ringed_planet:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>Parallel World Building</h1>", unsafe_allow_html=True
    )
    st.markdown(
        "<p class='subtitle'>Your intelligent world creator powered by Agno</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    model_options = {
        "gpt-4o": "openai:gpt-4o",
        "gemini-2.0-flash-exp": "google:gemini-2.0-flash-exp",
        "claude-3-5-sonnet": "anthropic:claude-3-5-sonnet-20241022",
    }
    selected_model = st.sidebar.selectbox(
        "Select a model",
        options=list(model_options.keys()),
        index=0,
        key="model_selector",
    )
    model_id = model_options[selected_model]

    ####################################################################
    # Initialize Agent
    ####################################################################
    world_builder: Agent
    if (
        "world_builder" not in st.session_state
        or st.session_state["world_builder"] is None
        or st.session_state.get("current_model") != model_id
    ):
        logger.info("---*--- Creating new World Builder agent ---*---")
        world_builder = get_world_builder(model_id=model_id)
        st.session_state["world_builder"] = world_builder
        st.session_state["current_model"] = model_id
    else:
        world_builder = st.session_state["world_builder"]

    ####################################################################
    # Initialize messages if not exists
    ####################################################################
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    ####################################################################
    # Sidebar
    ####################################################################
    sidebar_widget()

    ####################################################################
    # Get user input
    ####################################################################
    if prompt := st.chat_input("Describe your world! 🌏"):
        add_message("user", prompt)

    ####################################################################
    # Display chat history
    ####################################################################
    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            with st.chat_message(message["role"]):
                if "tool_calls" in message and message["tool_calls"]:
                    display_tool_calls(st.empty(), message["tool_calls"])
                st.markdown(message["content"])

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
            with st.spinner("🤔 Generating world..."):
                try:
                    # Run the agent and get response
                    run_response = world_builder.run(question)
                    world_data: World = run_response.content

                    # Display world details in a single column layout
                    st.header(world_data.name)

                    st.subheader("🌟 Characteristics")
                    for char in world_data.characteristics:
                        st.markdown(f"- {char}")

                    st.subheader("💰 Currency")
                    st.markdown(world_data.currency)

                    st.subheader("🗣️ Languages")
                    for lang in world_data.languages:
                        st.markdown(f"- {lang}")

                    st.subheader("⚔️ Major Wars & Conflicts")
                    for war in world_data.wars:
                        st.markdown(f"- {war}")

                    st.subheader("🧪 Notable Substances")
                    for drug in world_data.drugs:
                        st.markdown(f"- {drug}")

                    st.subheader("📜 History")
                    st.markdown(world_data.history)

                    # Store the formatted response for chat history
                    response = f"""# {world_data.name}

### Characteristics
{chr(10).join("- " + char for char in world_data.characteristics)}

### Currency
{world_data.currency}

### Languages
{chr(10).join("- " + lang for lang in world_data.languages)}

### History
{world_data.history}

### Major Wars & Conflicts
{chr(10).join("- " + war for war in world_data.wars)}

### Notable Substances
{chr(10).join("- " + drug for drug in world_data.drugs)}"""

                    # Display tool calls if available
                    if run_response.tools and len(run_response.tools) > 0:
                        display_tool_calls(tool_calls_container, run_response.tools)

                    add_message("assistant", response, run_response.tools)

                except Exception as e:
                    error_message = f"Sorry, I encountered an error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)


if __name__ == "__main__":
    main()
