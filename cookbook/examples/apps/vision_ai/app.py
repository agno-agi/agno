import os
import time
from pathlib import Path

import streamlit as st
from agents import chat_followup_agent, image_processing_agent
from agno.media import Image
from agno.models.google import Gemini
from agno.models.mistral.mistral import MistralChat
from agno.models.openai import OpenAIChat
from agno.utils.log import logger
from dotenv import load_dotenv
from prompt import extraction_prompt
from utils import about_widget, add_message, clear_chat

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# Streamlit App Configuration
st.set_page_config(
    page_title="VisionAI Chat",
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
        <h1 class='title'>VisionAI 🖼️</h1>
        <p class='subtitle'>Your AI-powered smart image analysis agent</p>
        """,
        unsafe_allow_html=True,
    )

    ####################################################################
    # Ensure session state variables are initialized
    ####################################################################
    if "last_extracted_image" not in st.session_state:
        st.session_state["last_extracted_image"] = None
    if "last_image_response" not in st.session_state:
        st.session_state["last_image_response"] = None
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "extract_triggered" not in st.session_state:
        st.session_state["extract_triggered"] = False

    ####################################################################
    # Sidebar Configuration
    ####################################################################
    with st.sidebar:
        st.markdown("#### 🖼️ Smart Image Analysis Agent")

        # Model Selection
        model_choice = st.selectbox(
            "🔍 Select Model Provider", ["OpenAI", "Gemini", "Mistral"], index=0
        )

        # Mode Selection
        mode = st.radio(
            "⚙️ Extraction Mode",
            ["Auto", "Manual", "Hybrid"],
            index=0,
            help="Select how the image analysis should be performed:\n"
            "- **Auto**: Extracts the image automatically without any extra information from users.\n"
            "- **Manual**: User provide specific instructions for image extraction.\n"
            "- **Hybrid**: Combined auto-processing mode with user-defined instructions.",
        )

        # Web Search Option (Enable/Disable DuckDuckGo)
        enable_search_option = st.radio("🌐 Enable Web Search?", ["Yes", "No"], index=1)
        enable_search = True if enable_search_option == "Yes" else False

    ####################################################################
    # Ensure Model is Initialized Properly
    ####################################################################
    if (
        "model_instance" not in st.session_state
        or st.session_state.get("model_choice", None) != model_choice
    ):
        if model_choice == "OpenAI":
            if not OPENAI_API_KEY:
                st.error(
                    "⚠️ OpenAI API key not found. Please set the OPENAI_API_KEY environment variable."
                )
            model = OpenAIChat(id="gpt-4o", api_key=OPENAI_API_KEY)
        elif model_choice == "Gemini":
            if not GOOGLE_API_KEY:
                st.error(
                    "⚠️ Google API key not found. Please set the GOOGLE_API_KEY environment variable."
                )
            model = Gemini(id="gemini-2.0-flash", api_key=GOOGLE_API_KEY)
        elif model_choice == "Mistral":
            if not MISTRAL_API_KEY:
                st.error(
                    "⚠️ Mistral API key not found. Please set the MISTRAL_API_KEY environment variable."
                )
            model = MistralChat(id="pixtral-12b-2409", api_key=MISTRAL_API_KEY)
        else:
            st.error(
                "⚠️ Unsupported model provider. Please select OpenAI, Gemini, or Mistral."
            )
            st.stop()  # Stop execution if model is not supported

        st.session_state["model_instance"] = model
    else:
        model = st.session_state["model_instance"]

    ####################################################################
    # Modify Agents Without Creating New Session
    ####################################################################
    if (
        "image_agent" not in st.session_state
        or "chat_agent" not in st.session_state
        or st.session_state.get("model_choice", None) != model_choice
        or st.session_state.get("enable_search", None) != enable_search
    ):
        logger.info(
            f"Updating Agents with model {model.id} and search enabled {enable_search}"
        )
        image_agent = image_processing_agent(model=model)
        st.session_state["image_agent"] = image_agent
        chat_agent = chat_followup_agent(model=model, enable_search=enable_search)
        st.session_state["chat_agent"] = chat_agent
        st.session_state["enable_search"] = enable_search

        ####################################################################
        # Store new selections in session_state
        ####################################################################
        st.session_state["model_choice"] = model_choice
        st.session_state["enable_search"] = enable_search

    else:
        image_agent = st.session_state["image_agent"]
        chat_agent = st.session_state["chat_agent"]

    ####################################################################
    # Load Runs from Memory (Chat History)
    ####################################################################
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    ####################################################################
    # Image Upload Section
    ####################################################################
    uploaded_file = st.file_uploader(
        "📤 Upload an Image (Max: 20MB) 📷", type=["png", "jpg", "jpeg"]
    )
    image_path = None

    if uploaded_file:
        temp_dir = Path("tmp/")
        temp_dir.mkdir(exist_ok=True)
        image_path = temp_dir / uploaded_file.name

        # Check if this is a new image different from the last one
        if (
            "last_extracted_image" in st.session_state
            and st.session_state["last_extracted_image"] is not None
            and str(st.session_state["last_extracted_image"]) != str(image_path)
        ):
            logger.info(
                f"New image detected. Resetting chat history and reinitializing agents."
            )
            clear_chat()

        with open(image_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

            # Display image preview in sidebar if an image is uploaded
            st.sidebar.markdown("#### 🖼️ Current Image")
            st.sidebar.image(uploaded_file, use_container_width=True)

        logger.info(f"✅ Image successfully saved at: {image_path}")

        # Show instruction input only for Manual & Hybrid Mode
        if mode in ["Manual", "Hybrid"]:
            instruction = st.text_area(
                "📝 Enter Extraction Instructions",
                placeholder="Extract number plates...",
            )
        else:
            instruction = None

        # ADD Extract Data Button
        if st.button("🔍 Extract Data"):
            if (
                image_path
                and (mode == "Auto" or instruction)
                and (
                    "last_image_response" not in st.session_state
                    or st.session_state["last_extracted_image"] != image_path
                )
            ):
                with st.spinner("📤 Processing Image! Extracting image data..."):
                    extracted_data = image_agent.run(
                        extraction_prompt,
                        images=[Image(filepath=image_path)],
                        instructions=instruction if instruction else None,
                    )

                # Store last extracted response for chat follow-ups
                st.session_state["last_image_response"] = extracted_data.content
                st.session_state["last_extracted_image"] = image_path

                # Create a temporary success message container
                success_message = st.empty()
                success_message.success("✅ Image processing completed successfully!")

                logger.info(f"Extracted Data Response: {extracted_data.content}")

                # Wait for 1 seconds, then clear the success message
                time.sleep(1)
                success_message.empty()

        # Display Extracted Image Data Persistently
        if st.session_state["last_image_response"]:
            st.write("### Extracted Image Insights:")
            st.write(st.session_state["last_image_response"])

    ####################################################################
    # Follow-up Chat Section
    ####################################################################
    st.markdown("---")
    st.markdown("### 💬 Chat with VisionAI")

    ####################################################################
    # Display Chat History First
    ####################################################################
    for message in st.session_state["messages"]:
        if message["role"] == "system":
            continue
        with st.chat_message(message["role"]):
            st.write(message["content"])

    if prompt := st.chat_input(
        "💬 Ask follow-up questions on the image extracted data..."
    ):
        # Display user message first
        with st.chat_message("user"):
            st.write(prompt)
        # Add user message to session state
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

    Extracted Image Data: {st.session_state["last_image_response"]}

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

    # Add clear chat button in sidebar
    if st.sidebar.button("🧹 Clear Chat History", key="clear_chat"):
        clear_chat()

    # About Section
    about_widget()


if __name__ == "__main__":
    main()
