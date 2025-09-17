import streamlit as st
from agents import generate_podcast, generate_podcast_agent
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
    page_title="Podcast Generator",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def restart_agent(model_id: str = None):
    target_model = model_id or st.session_state.get("current_model", "openai:gpt-4o")

    new_agent = generate_podcast_agent(model_id=target_model, session_id=None)

    st.session_state["agent"] = new_agent
    st.session_state["session_id"] = new_agent.session_id
    st.session_state["messages"] = []
    st.session_state["current_model"] = target_model
    st.session_state["is_new_session"] = True


def on_model_change():
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        new_model_id = selected_model
        current_model = st.session_state.get("current_model")

        if current_model and current_model != new_model_id:
            try:
                st.session_state["is_loading_session"] = False
                # Start new chat
                restart_agent(model_id=new_model_id)
            except Exception as e:
                st.sidebar.error(f"Error switching to {selected_model}: {str(e)}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>🎙️ Podcast Generator</h1>", unsafe_allow_html=True
    )
    st.markdown(
        "<p class='subtitle'>Create engaging AI podcasts on any topic</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector (filter for OpenAI models only)
    ####################################################################
    openai_models = [
        model
        for model in MODELS
        if model in ["gpt-4o", "o3-mini", "gpt-5", "gemini-2.5-pro"]
    ]
    selected_model = st.sidebar.selectbox(
        "Select Model",
        options=openai_models,
        index=0,
        key="model_selector",
        on_change=on_model_change,
        help="Only OpenAI models support audio generation",
    )

    ####################################################################
    # Initialize Agent and Session
    ####################################################################
    podcast_agent = initialize_agent(selected_model, generate_podcast_agent)
    reset_session_state(podcast_agent)

    if prompt := st.chat_input("💬 Ask about podcasts or request a specific topic!"):
        add_message("user", prompt)

    ####################################################################
    # Voice Selection
    ####################################################################
    st.sidebar.markdown("#### 🎤 Voice Settings")
    voice_options = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    selected_voice = st.sidebar.selectbox(
        "Choose Voice",
        options=voice_options,
        index=0,
        help="Select the AI voice for your podcast",
    )

    ####################################################################
    # Sample Topics
    ####################################################################
    st.sidebar.markdown("#### 🔥 Suggested Topics")
    sample_topics = [
        "🎭 Impact of AI on Creativity",
        "💡 Future of Renewable Energy",
        "🏥 AI in Healthcare Revolution",
        "� Space Exploration Updates",
        "🌱 Climate Change Solutions",
        "💻 Quantum Computing Explained",
    ]

    # Handle sample topic selection
    for sample_topic in sample_topics:
        if st.sidebar.button(
            sample_topic, key=f"topic_{sample_topic}", use_container_width=True
        ):
            add_message("user", sample_topic[2:])  # Remove emoji and add to chat
            st.rerun()

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
            if session_id:
                try:
                    session_name = podcast_agent.get_session_name()
                    if session_name:
                        filename = f"podcast_chat_{session_name}.md"
                    else:
                        filename = f"podcast_chat_{session_id}.md"
                except Exception:
                    filename = f"podcast_chat_{session_id}.md"
            else:
                filename = "podcast_chat_new.md"

            if st.sidebar.download_button(
                "💾 Export Chat",
                export_chat_history("Podcast Generator"),
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
    # Generate Podcast
    ####################################################################
    st.sidebar.markdown("#### 🎬 Generate")

    if st.sidebar.button("🎙️ Create Podcast", type="primary", use_container_width=True):
        # Get the latest user message as the topic
        user_messages = [
            msg
            for msg in st.session_state.get("messages", [])
            if msg.get("role") == "user"
        ]
        if user_messages:
            latest_topic = user_messages[-1]["content"]
            with st.spinner(
                "⏳ Generating podcast... This may take up to 2 minutes..."
            ):
                try:
                    audio_path = generate_podcast(
                        latest_topic, selected_voice, selected_model
                    )

                    if audio_path:
                        st.success("✅ Podcast generated successfully!")

                        st.subheader("🎧 Your AI Podcast")
                        st.audio(audio_path, format="audio/wav")

                        # Download button
                        with open(audio_path, "rb") as audio_file:
                            st.download_button(
                                "⬇️ Download Podcast",
                                audio_file,
                                file_name=f"podcast_{latest_topic[:30].replace(' ', '_')}.wav",
                                mime="audio/wav",
                                use_container_width=True,
                            )
                    else:
                        st.error("❌ Failed to generate podcast. Please try again.")

                except Exception as e:
                    st.error(f"❌ Error generating podcast: {str(e)}")
        else:
            st.sidebar.warning("⚠️ Please enter a topic in the chat first.")

    ####################################################################
    # Getting Started Guide
    ####################################################################
    if not st.session_state.get("messages"):
        st.markdown("### 🎯 How to Get Started")
        st.markdown("""
        1. **Choose a Model** - Select your preferred AI model
        2. **Pick a Voice** - Choose from 6 realistic AI voices  
        3. **Enter a Topic** - Type your podcast topic in the chat below or click a suggested topic
        4. **Generate** - Click 'Create Podcast' and wait for the magic!
        """)

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
        display_response(podcast_agent, question)

    ####################################################################
    # Session management widgets
    ####################################################################
    session_selector_widget(podcast_agent, selected_model, generate_podcast_agent)

    ####################################################################
    # Features Section
    ####################################################################
    st.markdown("---")
    st.markdown("### 🌟 Features")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        **🔬 AI Research**
        - Real-time topic research
        - Credible source analysis
        - Latest information gathering
        """)

    with col2:
        st.markdown("""
        **📝 Script Generation**
        - Engaging narratives
        - Professional structure
        - Conversational tone
        """)

    with col3:
        st.markdown("""
        **🎵 Audio Creation**
        - 6 realistic AI voices
        - High-quality audio
        - Instant download
        """)

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This Podcast Generator creates professional podcasts on any topic using AI research, "
        "script writing, and text-to-speech technology."
    )


if __name__ == "__main__":
    main()
