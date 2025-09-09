import streamlit as st
from agents import generate_podcast
from agno.utils.streamlit import (
    COMMON_CSS,
    MODELS,
    about_section,
)

st.set_page_config(
    page_title="Podcast Generator",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>🎙️ Podcast Generator</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Create engaging AI podcasts on any topic</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Model selector (filter for OpenAI models only)
    ####################################################################
    openai_models = [model for model in MODELS if model in ["gpt-4o", "o3-mini", "gpt-5"]]
    selected_model = st.sidebar.selectbox(
        "Select Model",
        options=openai_models,
        index=0,
        key="model_selector",
        help="Only OpenAI models support audio generation"
    )

    ####################################################################
    # Voice Selection
    ####################################################################
    st.sidebar.markdown("#### 🎤 Voice Settings")
    voice_options = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    selected_voice = st.sidebar.selectbox(
        "Choose Voice",
        options=voice_options,
        index=0,
        help="Select the AI voice for your podcast"
    )

    ####################################################################
    # Topic Input
    ####################################################################
    st.sidebar.markdown("#### 📖 Podcast Topic")
    topic = st.sidebar.text_area(
        "Enter Topic",
        placeholder="e.g., The Future of AI in Healthcare",
        help="Describe the topic you want your podcast to cover"
    )

    ####################################################################
    # Sample Topics
    ####################################################################
    st.sidebar.markdown("#### 🔥 Suggested Topics")
    sample_topics = [
        "🎭 Impact of AI on Creativity",
        "💡 Future of Renewable Energy",
        "🏥 AI in Healthcare Revolution",
        "🚀 Space Exploration Updates",
        "🌱 Climate Change Solutions",
        "💻 Quantum Computing Explained",
    ]

    for sample_topic in sample_topics:
        if st.sidebar.button(sample_topic, key=f"topic_{sample_topic}", use_container_width=True):
            st.session_state["selected_topic"] = sample_topic[2:]  # Remove emoji
            st.rerun()

    # Use selected topic if available
    if "selected_topic" in st.session_state:
        topic = st.session_state["selected_topic"]
        # Clear the selected topic to avoid persistence
        if "selected_topic" in st.session_state:
            del st.session_state["selected_topic"]

    ####################################################################
    # Generate Podcast
    ####################################################################
    st.sidebar.markdown("#### 🎬 Generate")
    
    if st.sidebar.button("🎙️ Create Podcast", type="primary", use_container_width=True):
        if topic:
            with st.spinner("⏳ Generating podcast... This may take up to 2 minutes..."):
                try:
                    audio_path = generate_podcast(topic, selected_voice, f"openai:{selected_model}")
                    
                    if audio_path:
                        st.success("✅ Podcast generated successfully!")
                        
                        st.subheader("🎧 Your AI Podcast")
                        st.audio(audio_path, format="audio/wav")
                        
                        # Download button
                        with open(audio_path, "rb") as audio_file:
                            st.download_button(
                                "⬇️ Download Podcast",
                                audio_file,
                                file_name=f"podcast_{topic[:30].replace(' ', '_')}.wav",
                                mime="audio/wav",
                                use_container_width=True
                            )
                    else:
                        st.error("❌ Failed to generate podcast. Please try again.")
                        
                except Exception as e:
                    st.error(f"❌ Error generating podcast: {str(e)}")
        else:
            st.sidebar.warning("⚠️ Please enter a topic before generating.")

    ####################################################################
    # Current Topic Display
    ####################################################################
    if topic:
        st.markdown("### 📝 Current Topic")
        st.info(f"**Topic:** {topic}")
        st.markdown("Click 'Create Podcast' in the sidebar to generate your AI podcast!")
    else:
        st.markdown("### 🎯 How to Get Started")
        st.markdown("""
        1. **Choose a Model** - Select your preferred AI model
        2. **Pick a Voice** - Choose from 6 realistic AI voices  
        3. **Enter a Topic** - Describe what you want your podcast to cover
        4. **Generate** - Click 'Create Podcast' and wait for the magic!
        
        💡 **Tip:** Try the suggested topics for quick inspiration!
        """)

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
