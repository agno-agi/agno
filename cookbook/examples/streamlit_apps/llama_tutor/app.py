import nest_asyncio
import streamlit as st
from agents import get_llama_tutor_agent
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

nest_asyncio.apply()
st.set_page_config(
    page_title="Llama Tutor",
    page_icon="🦙",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)

# Extended models list including Groq models for Llama Tutor
TUTOR_MODELS = MODELS + [
    "groq:llama-3.3-70b-versatile",
    "groq:llama-3.1-70b-versatile",
    "groq:mixtral-8x7b-32768",
]


def restart_agent(model_id: str = None, education_level: str = None):
    target_model = model_id or st.session_state.get("current_model", TUTOR_MODELS[0])
    target_education_level = education_level or st.session_state.get(
        "education_level", "High School"
    )

    new_agent = get_llama_tutor_agent(
        model_id=target_model, education_level=target_education_level, session_id=None
    )

    st.session_state["agent"] = new_agent
    st.session_state["session_id"] = new_agent.session_id
    st.session_state["messages"] = []
    st.session_state["current_model"] = target_model
    st.session_state["education_level"] = target_education_level
    st.session_state["is_new_session"] = True


def on_model_change():
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        if selected_model in TUTOR_MODELS:
            new_model_id = selected_model
            current_model = st.session_state.get("current_model")

            if current_model and current_model != new_model_id:
                try:
                    st.session_state["is_loading_session"] = False
                    # Start new chat with new model
                    restart_agent(model_id=new_model_id)

                except Exception as e:
                    st.sidebar.error(f"Error switching to {selected_model}: {str(e)}")
        else:
            st.sidebar.error(f"Unknown model: {selected_model}")


def on_education_level_change():
    selected_level = st.session_state.get("education_level_selector")
    current_level = st.session_state.get("education_level", "High School")

    if selected_level and selected_level != current_level:
        try:
            # Start new chat with new education level
            restart_agent(education_level=selected_level)
        except Exception as e:
            st.sidebar.error(f"Error switching to {selected_level}: {str(e)}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>Llama Tutor</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Your intelligent educational assistant powered by Agno</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector
    ####################################################################
    selected_model = st.sidebar.selectbox(
        "Select Model",
        options=TUTOR_MODELS,
        index=len(MODELS),  # Default to first Groq model
        key="model_selector",
        on_change=on_model_change,
    )

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
        on_change=on_education_level_change,
    )

    ####################################################################
    # Initialize Agent and Session
    ####################################################################
    # Store the education level in session state for agent creation
    if "education_level" not in st.session_state:
        st.session_state["education_level"] = selected_education_level

    llama_tutor_agent = initialize_agent(
        selected_model,
        lambda model_id, session_id: get_llama_tutor_agent(
            model_id=model_id,
            education_level=st.session_state.get("education_level", "High School"),
            session_id=session_id,
        ),
    )
    reset_session_state(llama_tutor_agent)

    if prompt := st.chat_input("✨ What would you like to learn about?"):
        add_message("user", prompt)

    ###############################################################
    # Sample Questions
    ###############################################################
    st.sidebar.markdown("#### ❓ Sample Questions")
    if st.sidebar.button("🧬 How does photosynthesis work?"):
        add_message(
            "user",
            "How does photosynthesis work?",
        )
    if st.sidebar.button("📚 Explain calculus basics"):
        add_message(
            "user",
            "What is calculus and how is it used in real life?",
        )
    if st.sidebar.button("🌍 Causes of World War I"):
        add_message(
            "user",
            "What were the main causes of World War I?",
        )
    if st.sidebar.button("⚛️ What is quantum physics?"):
        add_message(
            "user",
            "Explain quantum physics in simple terms",
        )

    ###############################################################
    # Utility buttons
    ###############################################################
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
            if session_id:
                try:
                    session_name = llama_tutor_agent.get_session_name()
                    if session_name:
                        filename = f"llama_tutor_analysis_{session_name}.md"
                    else:
                        filename = f"llama_tutor_analysis_{session_id}.md"
                except Exception:
                    filename = f"llama_tutor_analysis_{session_id}.md"
            else:
                filename = "llama_tutor_analysis_new.md"

            if st.sidebar.download_button(
                "💾 Export Chat",
                export_chat_history("Llama Tutor"),
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
        display_response(llama_tutor_agent, question)

    ####################################################################
    # Session management widgets
    ####################################################################
    session_selector_widget(
        llama_tutor_agent,
        selected_model,
        lambda model_id, session_id: get_llama_tutor_agent(
            model_id=model_id,
            education_level=st.session_state.get("education_level", "High School"),
            session_id=session_id,
        ),
    )

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This Llama Tutor provides personalized educational assistance across all subjects and education levels."
    )


if __name__ == "__main__":
    main()
