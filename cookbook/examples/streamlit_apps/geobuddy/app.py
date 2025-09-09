import os
import tempfile
from pathlib import Path

import streamlit as st
from agents import analyze_image_location, get_geobuddy_agent
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
    page_title="GeoBuddy",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def restart_geobuddy(model_id: str = None):
    """Restart GeoBuddy with new settings."""
    target_model = model_id or st.session_state.get("current_model", MODELS[0])

    new_agent = get_geobuddy_agent(
        model_id=target_model,
        session_id=None,
    )

    st.session_state["agent"] = new_agent
    st.session_state["session_id"] = new_agent.session_id
    st.session_state["messages"] = []
    st.session_state["current_model"] = target_model
    st.session_state["is_new_session"] = True


def on_model_change():
    """Handle model changes."""
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        if selected_model in MODELS:
            current_model = st.session_state.get("current_model")
            if current_model and current_model != selected_model:
                try:
                    st.session_state["is_loading_session"] = False
                    restart_geobuddy(model_id=selected_model)
                except Exception as e:
                    st.sidebar.error(f"Error switching to {selected_model}: {str(e)}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>GeoBuddy</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Your AI-powered geography detective for location identification</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    st.sidebar.header("🔧 Configuration")
    selected_model = st.sidebar.selectbox(
        "Select Model",
        options=MODELS,
        index=0,
        key="model_selector",
        on_change=on_model_change,
    )

    ####################################################################
    # Sidebar - Authentication
    ####################################################################
    st.sidebar.markdown("---")
    st.sidebar.header("🔑 Authentication")

    if "api_keys" not in st.session_state:
        st.session_state["api_keys"] = {}

    if "gpt" in selected_model.lower() or "openai" in selected_model.lower():
        api_key_label = "OpenAI API Key"
        api_key_env = "OPENAI_API_KEY"
        api_key_help = "Set your OpenAI API key"
    elif "gemini" in selected_model.lower() or "google" in selected_model.lower():
        api_key_label = "Google API Key"
        api_key_env = "GOOGLE_API_KEY"
        api_key_help = "Set your Google API key"
    else:
        api_key_label = "OpenAI API Key"  # Default to OpenAI
        api_key_env = "OPENAI_API_KEY"
        api_key_help = "Set your OpenAI API key"

    current_api_key = st.session_state["api_keys"].get(api_key_env, "")

    api_key = st.sidebar.text_input(
        api_key_label,
        value=current_api_key,
        type="password",
        help=api_key_help,
    )

    if api_key:
        st.session_state["api_keys"][api_key_env] = api_key
        os.environ[api_key_env] = api_key
        st.sidebar.success(f"✅ {api_key_label} configured")
    else:
        st.sidebar.warning(f"⚠️ {api_key_label} required")

    ####################################################################
    # Initialize GeoBuddy Agent and Session
    ####################################################################
    geobuddy_agent = initialize_agent(
        selected_model,
        lambda model_id, session_id: get_geobuddy_agent(
            model_id=model_id,
            session_id=session_id,
        ),
    )
    reset_session_state(geobuddy_agent)

    if prompt := st.chat_input(
        "🗺️ Ask me anything about geography or location analysis!"
    ):
        add_message("user", prompt)

    ####################################################################
    # Image Upload Section
    ####################################################################
    st.markdown("### 📷 Image Analysis")

    # Create a clean upload area
    with st.container():
        uploaded_file = st.file_uploader(
            "Choose an image to analyze",
            type=["jpg", "jpeg", "png", "webp"],
            help="Upload a clear image with visible landmarks, architecture, or geographical features",
        )

    if uploaded_file is not None:
        col1, col2 = st.columns([3, 2], gap="large")

        with col1:
            st.markdown("#### 🖼️ Uploaded Image")
            st.image(
                uploaded_file, caption="Image for Analysis", use_container_width=True
            )

        with col2:
            st.markdown("#### 🔍 Controls")

            st.markdown("")
            analyze_button = st.button(
                "🌍 Analyze Location",
                type="primary",
                use_container_width=True,
                help="Click to analyze the geographical location of this image",
            )

            if analyze_button:
                if not api_key:
                    st.error(
                        f"❌ Please provide your {api_key_label} in the sidebar first!"
                    )
                else:
                    with st.spinner("🔍 Analyzing image for geographical clues..."):
                        try:
                            # Save uploaded file temporarily
                            with tempfile.NamedTemporaryFile(
                                delete=False,
                                suffix=f".{uploaded_file.name.split('.')[-1]}",
                            ) as tmp_file:
                                tmp_file.write(uploaded_file.getvalue())
                                tmp_path = Path(tmp_file.name)

                            # Analyze the image
                            result = analyze_image_location(geobuddy_agent, tmp_path)

                            # Clean up temporary file
                            tmp_path.unlink()

                            if result:
                                add_message(
                                    "user",
                                    "Please analyze this uploaded image for geographical location identification.",
                                )
                                add_message("assistant", result)
                                st.success(
                                    "✅ Analysis complete! Check the results below."
                                )
                                st.rerun()
                            else:
                                st.warning(
                                    "⚠️ Could not analyze the image. Please try a different image."
                                )

                        except Exception as e:
                            st.error(f"❌ Error during analysis: {str(e)}")
                            # Clean up on error
                            if "tmp_path" in locals() and tmp_path.exists():
                                tmp_path.unlink()

    ####################################################################
    # Sample Analysis Options
    ####################################################################
    st.sidebar.markdown("#### 🌍 Sample Locations")

    if st.sidebar.button("🗽 Famous Landmarks"):
        add_message(
            "user",
            "I'd like to test GeoBuddy with famous landmarks. Can you provide tips for analyzing landmark photos?",
        )

    if st.sidebar.button("🏛️ Architectural Styles"):
        add_message(
            "user",
            "How can GeoBuddy identify locations based on architectural styles? What should I look for in buildings?",
        )

    if st.sidebar.button("🏔️ Natural Features"):
        add_message(
            "user",
            "What natural geographical features help GeoBuddy identify locations? How do you analyze landscapes?",
        )

    if st.sidebar.button("🌆 Urban Analysis"):
        add_message(
            "user",
            "How does GeoBuddy analyze urban environments and city characteristics for location identification?",
        )

    ####################################################################
    # Utility buttons
    ####################################################################
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns([1, 1])

    with col1:
        if st.sidebar.button("🔄 New Analysis Session", use_container_width=True):
            restart_geobuddy()
            st.rerun()

    with col2:
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            session_id = st.session_state.get("session_id")
            if session_id:
                try:
                    session_name = geobuddy_agent.get_session_name()
                    if session_name:
                        filename = f"geobuddy_analysis_{session_name}.md"
                    else:
                        filename = f"geobuddy_analysis_{session_id}.md"
                except Exception:
                    filename = f"geobuddy_analysis_{session_id}.md"
            else:
                filename = "geobuddy_analysis_new.md"

            if st.sidebar.download_button(
                "💾 Export Analysis",
                export_chat_history("GeoBuddy"),
                file_name=filename,
                mime="text/markdown",
                use_container_width=True,
                help=f"Export {len(st.session_state['messages'])} analysis results",
            ):
                st.sidebar.success("Analysis exported!")
        else:
            st.sidebar.button(
                "💾 Export Analysis",
                disabled=True,
                use_container_width=True,
                help="No analysis to export",
            )

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
        display_response(geobuddy_agent, question)

    ####################################################################
    # Session management widgets
    ####################################################################
    session_selector_widget(
        geobuddy_agent,
        selected_model,
        lambda model_id, session_id: get_geobuddy_agent(
            model_id=model_id,
            session_id=session_id,
        ),
    )

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This GeoBuddy agent analyzes images to predict geographical locations using advanced visual analysis of landmarks, architecture, and cultural clues."
    )


if __name__ == "__main__":
    main()
