import os
import streamlit as st
from pathlib import Path
from prompt import extraction_prompt

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.utils.log import logger
from agno.media import Image
from image_extraction import image_processing_agent
from utils import (
    about_widget,
    add_message,
    rename_session_widget,
    session_selector_widget,
)
from dotenv import load_dotenv

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
        unsafe_allow_html=True
    )

    ####################################################################
    # Sidebar Configuration
    ####################################################################
    with st.sidebar:
        st.markdown("#### 🖼️ Image Processing Queries")

        # Model Selection
        model_choice = st.selectbox("🔍 Select Model Provider", ["OpenAI", "Gemini"], index=0)

        # Mode Selection
        mode = st.radio("⚙️ Extraction Mode", ["Auto", "Manual", "Hybrid"], index=0)

        # Manual/Hybrid Mode Instructions
        instruction = None
        if mode in ["Manual", "Hybrid"]:
            instruction = st.text_area("📝 Enter Extraction Instructions", placeholder="Extract number plates...")

        # Session Management
        user_id = st.text_input("👤 User ID (For session tracking)", value="user_123")
        session_id = st.text_input("📂 Session ID (To keep chat history)", value="session_1")

    ####################################################################
    # Store selections in session_state
    ####################################################################
    st.session_state["model_choice"] = model_choice
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
    ):
        logger.info("---*--- Creating new Image Processing Agent ---*---")
        image_agent = image_processing_agent(model=model, user_id=user_id)
        st.session_state["image_agent"] = image_agent
        st.session_state["current_model"] = model_choice
    else:
        image_agent = st.session_state["image_agent"]

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
    uploaded_file = st.file_uploader("📤 Upload an Image 📷", type=["png", "jpg", "jpeg"])
    image_path = None
    if uploaded_file:
        temp_dir = Path("temp_images")
        temp_dir.mkdir(exist_ok=True)
        image_path = temp_dir / uploaded_file.name

        with open(image_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

    logger.info(f"✅ Image successfully saved at: {image_path}")

    ####################################################################
    # **1️⃣ Display Chat History First**
    ####################################################################
    for message in st.session_state["messages"]:
        if message["role"] in ["user", "assistant"]:
            _content = message["content"]
            if _content is not None:
                with st.chat_message(message["role"]):
                    st.write(_content)

    ####################################################################
    # **2️⃣ Auto Mode - Automatically Extract Image Data**
    ####################################################################
    if mode == "Auto" and uploaded_file:
        st.success("📤 Auto Mode enabled! Extracting image data...")

        extracted_data = image_agent.run(
            extraction_prompt, images=[Image(filepath=image_path)]
        )
        logger.info(f"Extracted Data Response: {extracted_data.content}")

        # Show extracted data
        st.write(extracted_data.content)

        # Save the response in chat history
        add_message("assistant", extracted_data.content)

    ####################################################################
    # **3️⃣ Handle User Chat Input**
    ####################################################################
    if prompt := st.chat_input("💬 Ask about the image or anything else..."):
        add_message("user", prompt)

    ####################################################################
    # **4️⃣ Process User Queries & Stream Responses**
    ####################################################################
    last_message = st.session_state["messages"][-1] if st.session_state["messages"] else None
    if last_message and last_message.get("role") == "user":
        question = last_message["content"]
        with st.chat_message("assistant"):
            response_container = st.empty()
            with st.spinner("🤔 Processing..."):
                response = ""
                try:
                    # Run agent and stream response
                    if uploaded_file:
                        extracted_data = image_agent.run(
                            extraction_prompt,
                            images=[Image(filepath=image_path)],
                            instructions=instruction,
                            stream=True
                        )
                    else:
                        extracted_data = image_agent.run(
                            extraction_prompt,
                            images=[Image(filepath=image_path)],
                            instructions=question,
                            stream=True
                        )

                    # Stream updates in real-time
                    for chunk in extracted_data:
                        if chunk and chunk.content:
                            response += chunk.content
                            response_container.markdown(response)

                    # Save assistant response in chat history
                    add_message("assistant", response)
                except Exception as e:
                    error_message = f"❌ Error: {str(e)}"
                    add_message("assistant", error_message)
                    st.error(error_message)

    ####################################################################
    # Rename Sessions
    ####################################################################
    rename_session_widget(image_agent)

    ####################################################################
    # About Section
    ####################################################################
    about_widget()


if __name__ == "__main__":
    main()
