import nest_asyncio
import streamlit as st
from agents import EDUCATION_LEVELS, GEMINI_MODELS, get_gemini_tutor_agent
from agno.utils.streamlit import (
    COMMON_CSS,
    about_section,
    add_message,
    display_chat_messages,
    display_response,
    export_chat_history,
    initialize_agent,
    reset_session_state,
    session_selector_widget,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="Gemini Tutor",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)

# Educational-specific CSS
st.markdown(
    """
<style>
    .education-level {
        background: linear-gradient(45deg, #FF6B6B, #4ECDC4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: bold;
        font-size: 1.1em;
    }
    
    .learning-objective {
        background-color: rgba(76, 175, 80, 0.1);
        border-left: 4px solid #4CAF50;
        padding: 15px;
        margin: 10px 0;
        border-radius: 5px;
    }
    
    .assessment-box {
        background-color: rgba(33, 150, 243, 0.1);
        border-left: 4px solid #2196F3;
        padding: 15px;
        margin: 10px 0;
        border-radius: 5px;
    }
    
    .interactive-element {
        background-color: rgba(255, 152, 0, 0.1);
        border-left: 4px solid #FF9800;
        padding: 15px;
        margin: 10px 0;
        border-radius: 5px;
    }
</style>
""",
    unsafe_allow_html=True,
)


def restart_tutor(model_id: str = None, education_level: str = None):
    """Restart the tutor with new settings."""
    target_model = model_id or st.session_state.get("current_model", GEMINI_MODELS[0])
    target_level = education_level or st.session_state.get(
        "education_level", EDUCATION_LEVELS[1]
    )

    new_agent = get_gemini_tutor_agent(
        model_id=target_model,
        education_level=target_level,
        session_id=None,
    )

    st.session_state["agent"] = new_agent
    st.session_state["session_id"] = new_agent.session_id
    st.session_state["messages"] = []
    st.session_state["current_model"] = target_model
    st.session_state["education_level"] = target_level
    st.session_state["is_new_session"] = True


def on_education_level_change():
    """Handle education level changes."""
    selected_level = st.session_state.get("education_level_selector")
    if selected_level:
        current_level = st.session_state.get("education_level")
        if current_level and current_level != selected_level:
            try:
                st.session_state["is_loading_session"] = False
                restart_tutor(education_level=selected_level)
            except Exception as e:
                st.sidebar.error(f"Error changing education level: {str(e)}")


def on_model_change():
    """Handle model changes."""
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        if selected_model in GEMINI_MODELS:
            current_model = st.session_state.get("current_model")
            if current_model and current_model != selected_model:
                try:
                    st.session_state["is_loading_session"] = False
                    restart_tutor(model_id=selected_model)
                except Exception as e:
                    st.sidebar.error(f"Error switching to {selected_model}: {str(e)}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>Gemini Tutor</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Your intelligent educational AI assistant powered by Google Gemini</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Sidebar - Authentication
    ####################################################################
    st.sidebar.header("🔑 Authentication")
    google_api_key = st.sidebar.text_input(
        "Google API Key",
        type="password",
        help="Get your API key from Google AI Studio (makersuite.google.com)",
    )

    if google_api_key:
        import os

        os.environ["GOOGLE_API_KEY"] = google_api_key
        st.sidebar.success("✅ Google API key configured")
    else:
        st.sidebar.warning("⚠️ Google API key required for Gemini models")
        st.sidebar.info(
            "💡 Get your free API key from [Google AI Studio](https://makersuite.google.com)"
        )

    ####################################################################
    # Model and Education Level selectors
    ####################################################################
    st.sidebar.markdown("---")
    selected_model = st.sidebar.selectbox(
        "Select Gemini Model",
        options=GEMINI_MODELS,
        index=0,
        key="model_selector",
        on_change=on_model_change,
    )

    selected_education_level = st.sidebar.selectbox(
        "Select Education Level",
        options=EDUCATION_LEVELS,
        index=1,  # Default to High School
        key="education_level_selector",
        on_change=on_education_level_change,
    )

    ####################################################################
    # Initialize Tutor Agent and Session
    ####################################################################
    gemini_tutor_agent = initialize_agent(
        selected_model,
        lambda model_id, session_id: get_gemini_tutor_agent(
            model_id=model_id,
            education_level=selected_education_level,
            session_id=session_id,
        ),
    )
    reset_session_state(gemini_tutor_agent)

    # Display current education level
    st.sidebar.markdown(
        f"**Current Level:** <span class='education-level'>{selected_education_level}</span>",
        unsafe_allow_html=True,
    )

    if prompt := st.chat_input("🎓 What would you like to learn about today?"):
        add_message("user", prompt)

    ####################################################################
    # Learning Templates
    ####################################################################
    st.sidebar.markdown("#### 📚 Learning Templates")

    if st.sidebar.button("🔬 Science Concepts"):
        add_message(
            "user",
            f"Explain a fundamental science concept appropriate for {selected_education_level} level with interactive examples and practice questions.",
        )

    if st.sidebar.button("📊 Math Problem Solving"):
        add_message(
            "user",
            f"Teach me a math concept with step-by-step problem solving examples suitable for {selected_education_level} students.",
        )

    if st.sidebar.button("🌍 History & Culture"):
        add_message(
            "user",
            f"Create a learning module about a historical event or cultural topic, adapted for {selected_education_level} level.",
        )

    if st.sidebar.button("💻 Technology & Programming"):
        add_message(
            "user",
            f"Explain a technology or programming concept with hands-on examples for {selected_education_level} learners.",
        )

    ####################################################################
    # Sample Learning Questions
    ####################################################################
    st.sidebar.markdown("#### ❓ Sample Questions")

    if st.sidebar.button("🧬 How does DNA work?"):
        add_message(
            "user",
            "How does DNA work? Please explain with examples and create an interactive learning experience.",
        )

    if st.sidebar.button("🚀 Physics of Space Travel"):
        add_message(
            "user",
            "Explain the physics behind space travel with practical examples and thought experiments.",
        )

    if st.sidebar.button("🎨 Art History Overview"):
        add_message(
            "user",
            "Give me an overview of Renaissance art with visual analysis and interactive elements.",
        )

    ####################################################################
    # Study Tools
    ####################################################################
    st.sidebar.markdown("#### 🛠️ Study Tools")

    if st.sidebar.button("📝 Create Study Guide"):
        add_message(
            "user",
            "Create a comprehensive study guide for my last learning topic with key points, practice questions, and review materials.",
        )

    if st.sidebar.button("🧪 Practice Quiz"):
        add_message(
            "user",
            "Generate a practice quiz based on our recent learning session with different question types and detailed explanations.",
        )

    if st.sidebar.button("🔍 Deep Dive Analysis"):
        add_message(
            "user",
            "Let's do a deep dive analysis of the most complex topic we've discussed, breaking it down into simpler components.",
        )

    ####################################################################
    # Utility buttons
    ####################################################################
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns([1, 1])

    with col1:
        if st.sidebar.button("🔄 New Learning Session", use_container_width=True):
            restart_tutor()
            st.rerun()

    with col2:
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            session_id = st.session_state.get("session_id")
            if session_id and gemini_tutor_agent.get_session_name():
                filename = (
                    f"gemini_tutor_session_{gemini_tutor_agent.get_session_name()}.md"
                )
            elif session_id:
                filename = f"gemini_tutor_session_{session_id}.md"
            else:
                filename = "gemini_tutor_session_new.md"

            if st.sidebar.download_button(
                "💾 Export Learning",
                export_chat_history("Gemini Tutor"),
                file_name=filename,
                mime="text/markdown",
                use_container_width=True,
                help=f"Export {len(st.session_state['messages'])} learning interactions",
            ):
                st.sidebar.success("Learning session exported!")
        else:
            st.sidebar.button(
                "💾 Export Learning",
                disabled=True,
                use_container_width=True,
                help="No learning content to export",
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
        display_response(gemini_tutor_agent, question)

    ####################################################################
    # Session management widgets
    ####################################################################
    session_selector_widget(
        gemini_tutor_agent,
        selected_model,
        lambda model_id, session_id: get_gemini_tutor_agent(
            model_id=model_id,
            education_level=selected_education_level,
            session_id=session_id,
        ),
    )

    ####################################################################
    # About section
    ####################################################################
    about_section(
        f"This Gemini Tutor provides personalized educational experiences for {selected_education_level} students using Google's advanced Gemini AI models with multimodal learning capabilities."
    )


if __name__ == "__main__":
    main()
