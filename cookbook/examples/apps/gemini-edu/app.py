"""
Gemini Tutor: Advanced Educational AI Assistant
"""

import nest_asyncio
import os
import streamlit as st
from agents import tutor_agent
from agno.utils.log import logger
from agno.media import Image, Audio, Video
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
    page_title="Gemini Tutor: Learn Anything",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load custom CSS with dark mode support
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Constants
ALLOWED_IMAGE_TYPES = ["png", "jpg", "jpeg", "webp"]
ALLOWED_AUDIO_TYPES = ["mp3", "wav", "ogg"]
ALLOWED_VIDEO_TYPES = ["mp4", "webm", "avi", "mov"]

def save_uploaded_file(uploaded_file):
    """Save an uploaded file to a temporary directory and return the path."""
    # Create a tmp directory if it doesn't exist
    if not os.path.exists("tmp"):
        os.makedirs("tmp")

    # Save the file
    file_path = os.path.join("tmp", uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return file_path

def main() -> None:
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>Gemini Tutor</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Your intelligent multimodal learning companion powered by Gemini 2.5 Pro</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model configuration - use Gemini 2.5 Pro Experimental
    ####################################################################
    available_models = {
        "Gemini 2.5 Pro Experimental (Recommended)": "gemini-2.5-pro-exp-03-25",
        "Gemini 2.0 Flash": "gemini-2.0-flash",
        "Gemini 1.5 Pro": "gemini-1.5-pro",
    }

    selected_model_name = st.sidebar.selectbox(
        "Model",
        options=list(available_models.keys()),
        index=0,  # Default to Gemini 2.5 Pro Experimental
        key="model_selector",
    )

    model_id = available_models[selected_model_name]

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
        if "gemini_tutor" in st.session_state:
            st.session_state["gemini_tutor"] = None

    # Reset agent if model changes
    if "current_model" in st.session_state and st.session_state["current_model"] != model_id:
        if "gemini_tutor" in st.session_state:
            st.session_state["gemini_tutor"] = None

    ####################################################################
    # Initialize Agent
    ####################################################################
    gemini_tutor: Agent
    if (
        "gemini_tutor" not in st.session_state
        or st.session_state["gemini_tutor"] is None
        or st.session_state.get("current_model") != model_id
    ):
        logger.info(f"---*--- Creating new Gemini Tutor agent with {model_id} ---*---")
        gemini_tutor = tutor_agent(
            model_id=model_id,
            education_level=st.session_state["education_level"],
        )
        st.session_state["gemini_tutor"] = gemini_tutor
        st.session_state["current_model"] = model_id
    else:
        gemini_tutor = st.session_state["gemini_tutor"]

    ####################################################################
    # Load Agent Session from the database
    ####################################################################
    try:
        st.session_state["gemini_tutor_session_id"] = gemini_tutor.load_session()
    except Exception:
        st.warning("Could not create Agent session, is the database running?")
        return

    ####################################################################
    # Load runs from memory
    ####################################################################
    agent_runs = gemini_tutor.memory.runs

    ####################################################################
    # Sidebar widgets
    ####################################################################
    sidebar_widget()

    ####################################################################
    # Chat interface
    ####################################################################
    # Display chat messages
    for message in st.session_state.get("messages", []):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            # Display uploaded media if any
            if message.get("image"):
                st.image(message["image"], caption="Uploaded Image")
            if message.get("audio"):
                st.audio(message["audio"], caption="Uploaded Audio")
            if message.get("video"):
                st.video(message["video"], caption="Uploaded Video")

            if message.get("tool_calls"):
                display_tool_calls(st.empty(), message["tool_calls"])

    ####################################################################
    # File upload options
    ####################################################################
    st.sidebar.markdown("### 📎 Upload Media")

    uploaded_image = st.sidebar.file_uploader(
        "Upload an image",
        type=ALLOWED_IMAGE_TYPES,
        key="image_uploader"
    )

    uploaded_audio = st.sidebar.file_uploader(
        "Upload audio",
        type=ALLOWED_AUDIO_TYPES,
        key="audio_uploader"
    )

    uploaded_video = st.sidebar.file_uploader(
        "Upload video",
        type=ALLOWED_VIDEO_TYPES,
        key="video_uploader"
    )

    # Initialize media containers
    images = []
    audio = None
    video = None

    # Process uploaded files
    if uploaded_image is not None:
        image_path = save_uploaded_file(uploaded_image)
        images.append(Image(path=image_path))
        st.sidebar.success(f"Image {uploaded_image.name} uploaded successfully!")

    if uploaded_audio is not None:
        audio_path = save_uploaded_file(uploaded_audio)
        audio = Audio(path=audio_path)
        st.sidebar.success(f"Audio {uploaded_audio.name} uploaded successfully!")

    if uploaded_video is not None:
        video_path = save_uploaded_file(uploaded_video)
        video = Video(path=video_path)
        st.sidebar.success(f"Video {uploaded_video.name} uploaded successfully!")

    # Chat input
    if prompt := st.chat_input("Ask me anything..."):
        # Prepare media message additions
        media_message = {}
        if uploaded_image:
            media_message["image"] = image_path
        if uploaded_audio:
            media_message["audio"] = audio_path
        if uploaded_video:
            media_message["video"] = video_path

        # Add user message to chat history
        add_message("user", prompt, **media_message)

        with st.chat_message("user"):
            st.markdown(prompt)

            # Display uploaded media
            if uploaded_image:
                st.image(image_path, caption="Uploaded Image")
            if uploaded_audio:
                st.audio(audio_path, caption="Uploaded Audio")
            if uploaded_video:
                st.video(video_path, caption="Uploaded Video")

        # Get the last message
        last_message = st.session_state["messages"][-1]

        if last_message and last_message.get("role") == "user":
            question = last_message["content"]
            with st.chat_message("assistant"):
                # Create container for tool calls
                tool_calls_container = st.empty()
                resp_container = st.empty()
                with st.spinner("🧠 Gemini Tutor is analyzing your content and researching..."):
                    response = ""
                    try:
                        # Run the agent with multimedia content if available
                        run_kwargs = {
                            "prompt": question,
                            "stream": True
                        }

                        # Add media to the run if available
                        if images:
                            run_kwargs["images"] = images
                        if audio:
                            run_kwargs["audio"] = audio
                        if video:
                            run_kwargs["video"] = video

                        # Run the agent and stream the response
                        run_response = gemini_tutor.run(**run_kwargs)

                        for _resp_chunk in run_response:
                            # Display tool calls if available
                            if _resp_chunk.tools and len(_resp_chunk.tools) > 0:
                                display_tool_calls(tool_calls_container, _resp_chunk.tools)

                            # Display response
                            if _resp_chunk.content is not None:
                                response += _resp_chunk.content
                                resp_container.markdown(response)

                        add_message("assistant", response, gemini_tutor.run_response.tools)
                    except Exception as e:
                        error_message = f"Sorry, I encountered an error: {str(e)}"
                        add_message("assistant", error_message)
                        st.error(error_message)

                    # Clear uploaded files after processing
                    if uploaded_image:
                        st.session_state["image_uploader"] = None
                    if uploaded_audio:
                        st.session_state["audio_uploader"] = None
                    if uploaded_video:
                        st.session_state["video_uploader"] = None

    ####################################################################
    # Session selector
    ####################################################################
    session_selector_widget(gemini_tutor, model_id)
    rename_session_widget(gemini_tutor)

    ####################################################################
    # About section
    ####################################################################
    about_widget()


if __name__ == "__main__":
    main()
