import base64
import io

import nest_asyncio
import streamlit as st
from agents import get_recipe_agent
from agno.utils.log import logger
from PIL import Image
from utils import (
    CUSTOM_CSS,
    about_widget,
    add_message,
    display_tool_calls,
    example_inputs,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="Recipe Image Generator",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load custom CSS with dark mode support
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def main() -> None:
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>Recipe Image Generator</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='subtitle'>Upload your recipe PDF or use the default. Ask for a recipe and receive step-by-step images!</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    model_options = {
        "llama-4-scout": "groq:meta-llama/llama-4-scout-17b-16e-instruct",
    }
    selected_model = st.sidebar.selectbox(
        "Select a model",
        options=list(model_options.keys()),
        index=0,
        key="model_selector",
    )
    model_id = model_options[selected_model]

    example_inputs()
    ####################################################################
    # Recipe source selector & Agent initialization
    ####################################################################
    uploaded_file = st.sidebar.file_uploader("Upload recipe PDF", type=["pdf"])
    use_default = st.sidebar.checkbox(
        "Use default sample recipe book", value=(uploaded_file is None)
    )
    pdf_path = None
    if uploaded_file:
        import tempfile

        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tf.write(uploaded_file.read())
        tf.flush()
        pdf_path = tf.name
    if use_default:
        pdf_path = None

    if (
        "recipe_agent" not in st.session_state
        or st.session_state.get("pdf_path") != pdf_path
        or st.session_state.get("current_model") != model_id
    ):
        logger.info("---*--- Creating new Recipe agent ---*---")
        recipe_agent = get_recipe_agent(
            local_pdf_path=pdf_path,
        )
        st.session_state["recipe_agent"] = recipe_agent
        st.session_state["pdf_path"] = pdf_path
        st.session_state["current_model"] = model_id
    else:
        recipe_agent = st.session_state["recipe_agent"]

    # Track knowledge load state
    if "knowledge_loaded" not in st.session_state:
        st.session_state["knowledge_loaded"] = False

    # Manual load button
    if st.sidebar.button("Load recipes"):
        st.sidebar.info("Loading default recipes...")
        recipe_agent.knowledge.load(recreate=True)
        st.session_state["knowledge_loaded"] = True
        st.sidebar.success("Recipes loaded!")

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    ####################################################################
    # Get user input
    ####################################################################
    if prompt := st.chat_input("👋 Ask me for a recipe (e.g., 'Recipe for Pad Thai')"):
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
        # Auto-load knowledge if needed
        if not st.session_state.get("knowledge_loaded", False):
            info = st.info("Loading default recipes...")
            recipe_agent.knowledge.load(recreate=True)
            st.session_state["knowledge_loaded"] = True
            info.empty()
        with st.chat_message("assistant"):
            # Create container for tool calls
            tool_calls_container = st.empty()
            resp_container = st.empty()
            with st.spinner("🤔 Thinking..."):
                response = ""
                try:
                    # Run the agent and stream the response
                    run_response = recipe_agent.run(
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

                    # Display generated images
                    for img in recipe_agent.run_response.images or []:
                        # Inline base64 content
                        if getattr(img, "content", None):
                            try:
                                # img.content is base64-encoded bytes
                                decoded = base64.b64decode(img.content)
                                image = Image.open(io.BytesIO(decoded))
                                resp_container.image(image)
                            except Exception as e:
                                logger.error(f"Failed to render inline image: {e}")
                                # Fallback to URL if available
                                if getattr(img, "url", None):
                                    resp_container.image(img.url)
                        # URL fallback
                        elif getattr(img, "url", None):
                            resp_container.image(img.url)
                    add_message("assistant", response, recipe_agent.run_response.tools)
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
