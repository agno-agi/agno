from pathlib import Path

import streamlit as st
from agents import get_vision_agent
from agno.media import Image
from agno.utils.streamlit import (
    COMMON_CSS,
    MODELS,
    about_section,
    add_message,
    display_chat_messages,
    display_response,
    export_chat_history,
    initialize_agent,
    reset_session_state,
    session_selector_widget,
)

st.set_page_config(
    page_title="Vision AI",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(COMMON_CSS, unsafe_allow_html=True)


def restart_agent(model_id: str = None):
    target_model = model_id or st.session_state.get("current_model", MODELS[0])

    st.session_state["agent"] = None
    st.session_state["session_id"] = None
    st.session_state["messages"] = []
    st.session_state["current_model"] = target_model
    st.session_state["is_new_session"] = True

    # Clear current image
    if "current_image" in st.session_state:
        del st.session_state["current_image"]


def on_model_change():
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        if selected_model in MODELS:
            new_model_id = selected_model
            current_model = st.session_state.get("current_model")

            if current_model and current_model != new_model_id:
                try:
                    st.session_state["is_loading_session"] = False
                    restart_agent(model_id=new_model_id)

                except Exception as e:
                    st.sidebar.error(f"Error switching to {selected_model}: {str(e)}")
        else:
            st.sidebar.error(f"Unknown model: {selected_model}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>🖼️ Vision AI</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Smart image analysis and understanding</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    selected_model = st.sidebar.selectbox(
        "Select Model",
        options=MODELS,
        index=0,
        key="model_selector",
        on_change=on_model_change,
        help="Choose the AI model for image analysis",
    )

    ####################################################################
    # Vision AI Settings
    ####################################################################
    st.sidebar.markdown("#### 🔍 Analysis Settings")

    analysis_mode = st.sidebar.radio(
        "Analysis Mode",
        ["Auto", "Manual", "Hybrid"],
        index=0,
        help="""
        - **Auto**: Automatic comprehensive image analysis
        - **Manual**: Analysis based on your specific instructions  
        - **Hybrid**: Automatic analysis + your custom instructions
        """,
    )

    enable_search = st.sidebar.checkbox(
        "Enable Web Search",
        value=False,
        key="enable_search",
        help="Allow the agent to search for additional context",
    )

    ####################################################################
    # Initialize Agent and Session
    ####################################################################
    # Create unified agent with search capability
    def get_vision_agent_with_settings(model_id: str, session_id: str = None):
        return get_vision_agent(
            model_id=model_id, enable_search=enable_search, session_id=session_id
        )

    vision_agent = initialize_agent(selected_model, get_vision_agent_with_settings)
    reset_session_state(vision_agent)

    if prompt := st.chat_input("👋 Ask me anything!"):
        add_message("user", prompt)

    ####################################################################
    # File upload
    ####################################################################
    st.sidebar.markdown("#### 🖼️ Image Analysis")

    uploaded_file = st.sidebar.file_uploader(
        "Upload an Image", type=["png", "jpg", "jpeg"]
    )

    if uploaded_file:
        temp_dir = Path("tmp")
        temp_dir.mkdir(exist_ok=True)
        image_path = temp_dir / uploaded_file.name

        with open(image_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.session_state["current_image"] = {
            "path": str(image_path),
            "name": uploaded_file.name,
            "analysis_mode": analysis_mode,
        }

        st.sidebar.image(uploaded_file, caption=uploaded_file.name, width=200)
        st.sidebar.success(f"Image '{uploaded_file.name}' uploaded")

    # Analysis
    if st.session_state.get("current_image") and not prompt:
        if st.sidebar.button(
            "🔍 Analyze Image", type="primary", use_container_width=True
        ):
            image_info = st.session_state["current_image"]

            if analysis_mode == "Manual":
                custom_instructions = st.sidebar.text_area(
                    "Analysis Instructions", key="manual_instructions"
                )
                if custom_instructions:
                    add_message(
                        "user",
                        f"Analyze this image with instructions: {custom_instructions}",
                    )
                else:
                    add_message("user", f"Analyze this image: {image_info['name']}")
            elif analysis_mode == "Hybrid":
                custom_instructions = st.sidebar.text_area(
                    "Additional Instructions", key="hybrid_instructions"
                )
                if custom_instructions:
                    add_message(
                        "user",
                        f"Analyze this image with additional focus: {custom_instructions}",
                    )
                else:
                    add_message("user", f"Analyze this image: {image_info['name']}")
            else:
                add_message("user", f"Analyze this image: {image_info['name']}")

    ###############################################################
    # Sample Questions
    ###############################################################
    st.sidebar.markdown("#### ❓ Sample Questions")
    if st.sidebar.button("🔍 What are the main objects?"):
        add_message("user", "What are the main objects?")
    if st.sidebar.button("📝 Is there any text to read?"):
        add_message("user", "Is there any text to read?")
    if st.sidebar.button("🎨 Describe the colors and mood"):
        add_message("user", "Describe the colors and mood")

    ####################################################################
    # Display Chat Messages
    ####################################################################
    display_chat_messages()

    ####################################################################
    # Generate response for user message
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )
    if last_message and last_message.get("role") == "user":
        question = last_message["content"]

        images_to_include = []
        if st.session_state.get("current_image"):
            image_info = st.session_state["current_image"]
            images_to_include = [Image(filepath=image_info["path"])]

        if images_to_include:
            with st.chat_message("assistant"):
                response_container = st.empty()
                with st.spinner("🤔 Thinking..."):
                    try:
                        response = vision_agent.run(question, images=images_to_include)
                        response_container.markdown(response.content)
                        add_message("assistant", response.content)
                    except Exception as e:
                        error_message = f"❌ Error: {str(e)}"
                        response_container.error(error_message)
                        add_message("assistant", error_message)
        else:
            # Use the same unified agent for all responses (maintains session)
            display_response(vision_agent, question)

    ####################################################################
    # Utility buttons
    ####################################################################
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns([1, 1])
    with col1:
        if st.sidebar.button("🔄 New Chat", use_container_width=True):
            restart_agent()
            st.rerun()

    with col2:
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            session_id = st.session_state.get("session_id")
            session_name = None

            try:
                if session_id and vision_agent:
                    session_name = vision_agent.get_session_name()
            except Exception:
                session_name = None

            if session_id and session_name:
                filename = f"vision_ai_chat_{session_name}.md"
            elif session_id:
                filename = f"vision_ai_chat_{session_id[:8]}.md"
            else:
                filename = "vision_ai_chat_new.md"

            if st.sidebar.download_button(
                "💾 Export Chat",
                export_chat_history("Vision AI"),
                file_name=filename,
                mime="text/markdown",
                use_container_width=True,
                help=f"Export {len(st.session_state['messages'])} messages",
            ):
                st.sidebar.success("Chat history exported!")
        else:
            st.sidebar.button(
                "💾 Export Chat",
                disabled=True,
                use_container_width=True,
                help="No messages to export",
            )

    ####################################################################
    # Session management widgets
    ####################################################################
    is_new_session = st.session_state.get("is_new_session", False)
    has_messages = (
        st.session_state.get("messages") and len(st.session_state["messages"]) > 0
    )

    if not is_new_session or has_messages:
        session_selector_widget(
            vision_agent, selected_model, get_vision_agent_with_settings
        )
        if is_new_session and has_messages:
            st.session_state["is_new_session"] = False
    else:
        st.sidebar.info("🆕 New Chat - Start your conversation!")

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This Vision AI assistant analyzes images and answers questions about visual content using "
        "advanced vision-language models."
    )


if __name__ == "__main__":
    main()
