import os
from pathlib import Path

import streamlit as st
from agno.agent import Agent
from agno.media import Image
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.utils.log import logger
from dotenv import load_dotenv
from agents import chat_followup_agent, image_processing_agent
from prompt import extraction_prompt
from utils import (
    about_widget,
    add_message,
    rename_session_widget,
    session_selector_widget,
)

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Streamlit App Configuration
st.set_page_config(
    page_title="VisioAI Chat",
    page_icon="📷",
    layout="wide",
)


def main():
    ####################################################################
    # App Header
    ####################################################################
    st.markdown(
        """
        <style>
            .title {
                text-align: center;
                font-size: 3em;
                font-weight: bold;
                color: white;
            }
            .subtitle {
                text-align: center;
                font-size: 1.5em;
                color: #bbb;
                margin-top: -15px;
            }
        </style>
        <h1 class='title'>VisioAI 🖼️</h1>
        <p class='subtitle'>Your AI-powered smart image analysis agent</p>
        """,
        unsafe_allow_html=True,
    )

    ####################################################################
    # Sidebar Configuration
    ####################################################################
    with st.sidebar:
        st.markdown("#### 🖼️ Smart Image Analysis Agent")

        # Model Selection
        model_choice = st.selectbox(
            "🔍 Select Model Provider", ["OpenAI", "Gemini"], index=0
        )

        # Mode Selection
        mode = st.radio("⚙️ Extraction Mode", ["Auto", "Manual", "Hybrid"], index=0)

        # Web Search Option (Enable/Disable DuckDuckGo)
        enable_search_option = st.radio("🌐 Enable Web Search?", ["Yes", "No"], index=1)
        enable_search = True if enable_search_option == "Yes" else False

        # Session Management
        user_id = st.text_input("👤 User ID (For session tracking)", value="user_123")
        session_id = st.text_input(
            "📂 Session ID (To keep chat history)", value="session_1"
        )

    ####################################################################
    # Store selections in session_state
    ####################################################################
    st.session_state["model_choice"] = model_choice
    st.session_state["enable_search"] = enable_search
    st.session_state["user_id"] = user_id
    st.session_state["session_id"] = session_id

    ####################################################################
    # Ensure Model is Initialized Properly
    ####################################################################
    if model_choice == "OpenAI":
        model = OpenAIChat(id="gpt-4o", api_key=OPENAI_API_KEY)
    else:
        model = Gemini(id="gemini-2.0-flash", api_key=GOOGLE_API_KEY)

    ####################################################################
    # Initialize Image Processing Agent
    ####################################################################
    image_agent: Agent
    if (
        "image_agent" not in st.session_state
        or st.session_state["image_agent"] is None
        or st.session_state.get("current_model") != model_choice
        or st.session_state.get("search_enabled") != enable_search
    ):
        logger.info("---*--- Creating new Image Processing Agent ---*---")
        image_agent = image_processing_agent(
            model=model, user_id=user_id, enable_search=enable_search
        )
        st.session_state["image_agent"] = image_agent
        st.session_state["current_model"] = model_choice
    else:
        image_agent = st.session_state["image_agent"]

    ####################################################################
    # Initialize Followup Chat Agent
    ####################################################################
    chat_agent: Agent
    if (
        "chat_agent" not in st.session_state
        or st.session_state["chat_agent"] is None
        or st.session_state.get("current_model") != model_choice
        or st.session_state.get("search_enabled") != enable_search
    ):
        logger.info("---*--- Creating new Chat Agent ---*---")
        chat_agent = chat_followup_agent(
            model=model, user_id=user_id, enable_search=enable_search
        )
        st.session_state["chat_agent"] = chat_agent
        st.session_state["search_enabled"] = enable_search
    else:
        chat_agent = st.session_state["chat_agent"]

    ####################################################################
    # Load Agent Session from the Database
    ####################################################################
    try:
        st.session_state["image_agent_session_id"] = image_agent.load_session()
    except Exception as e:
        st.warning(f"Could not create Agent session, exception {e}")
        return

    ####################################################################
    # Load Runs from Memory (Chat History)
    ####################################################################
    agent_runs = image_agent.memory.runs
    if len(agent_runs) > 0:
        logger.debug("Loading run history")
        st.session_state["messages"] = []
        for _run in agent_runs:
            if _run.message is not None:
                add_message(_run.message.role, _run.message.content)
            if _run.response is not None:
                add_message("assistant", _run.response.content)
    else:
        logger.debug("No run history found")
        st.session_state["messages"] = []

    ####################################################################
    # Session Selector Widget
    ####################################################################
    session_selector_widget(image_agent)

    ####################################################################
    # Image Upload Section
    ####################################################################
    uploaded_file = st.file_uploader(
        "📤 Upload an Image 📷", type=["png", "jpg", "jpeg"]
    )
    image_path = None
    if uploaded_file:
        temp_dir = Path("temp_images")
        temp_dir.mkdir(exist_ok=True)
        image_path = temp_dir / uploaded_file.name

        with open(image_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        logger.info(f"✅ Image successfully saved at: {image_path}")

        # Show instruction input only for Manual & Hybrid Mode
        if mode in ["Manual", "Hybrid"]:
            instruction = st.text_area(
                "📝 Enter Extraction Instructions",
                placeholder="Extract number plates...",
            )
        else:
            instruction = None

        # Run Image Processing Agent after Image Upload & Instruction Input
        if (
            mode in ["Auto", "Manual", "Hybrid"]
            and image_path
            and (mode == "Auto" or instruction)
        ):
            st.success("📤 Processing Image! Extracting image data...")

            extracted_data = image_agent.run(
                extraction_prompt,
                images=[Image(filepath=image_path)],
                instructions=instruction if instruction else None,
            )

            # Store last extracted response for chat follow-ups
            st.session_state["last_image_response"] = extracted_data.content

            logger.info(f"Extracted Data Response: {extracted_data.content}")

            st.write("### Extracted Image Insights:")
            st.write(extracted_data.content)

    ####################################################################
    # Display Chat History First
    ####################################################################
    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            _content = message["content"]
            if _content is not None:
                with st.chat_message(message["role"]):
                    st.write(_content)

    ####################################################################
    # Follow-up Chat Section
    ####################################################################
    st.markdown("---")
    st.markdown("### 💬 Chat with VisioAI")

    if prompt := st.chat_input(
        "💬 Ask follow-up questions on the image extracted data..."
    ):
        add_message("user", prompt)

    ####################################################################
    # Process User Queries & Stream Responses
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )

    if last_message and last_message["role"] == "user":
        user_question = last_message["content"]

        # Ensure Image Agent has extracted data before running chat agent
        if (
            "last_image_response" not in st.session_state
            or not st.session_state["last_image_response"]
        ):
            st.warning(
                "⚠️ No extracted insights available. Please process an image first."
            )
        else:
            with st.chat_message("assistant"):
                response_container = st.empty()
                with st.spinner("🤔 Processing follow-up question..."):
                    try:
                        chat_response = chat_agent.run(
                            f"""You are a chat agent who answers followup questions based on extracted image data.
Understand the requirement properly and then answer the question correctly.

Extracted Image Data: {st.session_state['last_image_response']}

Use the above image insights to answer the following question.
Answer the following question from the above given extracted image data: {user_question}""",
                            stream=True,
                        )

                        response_text = ""
                        for chunk in chat_response:
                            if chunk and chunk.content:
                                response_text += chunk.content
                                response_container.markdown(response_text)

                        add_message("assistant", response_text)

                    except Exception as e:
                        error_message = f"❌ Error: {str(e)}"
                        add_message("assistant", error_message)
                        st.error(error_message)

    ####################################################################
    # Rename Sessions
    ####################################################################
    rename_session_widget(image_agent)

    # About Section
    about_widget()


if __name__ == "__main__":
    main()
