import streamlit as st
from agents import generate_podcast

# Streamlit App Configuration
st.set_page_config(
    page_title="Podify AI 🎙️",
    page_icon="🎧",
    layout="wide",
)

# Sidebar Section
with st.sidebar:
    st.title("🎧 Podify AI")
    st.markdown("AI voices to generate an **engaging podcast**!")

    # Voice Selection
    voice_options = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    selected_voice = st.selectbox("🎤 Choose a Voice:", voice_options, index=0)

    st.markdown("---")
    st.subheader("🔥 Suggested Topics:")
    trending_topics = [
        "🎭 Impact of AI on Creativity and Art",
        "💡 Elon Musk vs Sam Altman",
        "🏥 Using AI in healthcare",
        "🚀 The Future of Space Exploration",
    ]

    # Create row-wise aligned buttons
    num_cols = 1  # Change this to 3 for three buttons in a row
    cols = st.columns(num_cols)  # Define columns

    for i, topic in enumerate(trending_topics):
        with cols[i % num_cols]:  # Distribute buttons evenly across columns
            if st.button(topic):
                st.session_state["topic"] = topic
                st.session_state["generate"] = True

    st.markdown("---")
    st.subheader("ℹ️ About")
    st.markdown(
        """
        - Enter a **topic** <br>
        - **Select a voice** <br>
        - **Click Generate Podcast** <br>
        - **Listen & Download** the AI-generated audio
        """,
        unsafe_allow_html=True,
    )

# Main Content
st.title("Podify AI🎙️")
st.markdown(":orange_heart: **powered by Agno**")

st.markdown(
    "Create high-quality podcasts on **any topic**! Simply enter a topic and let Podify AI generate a professional podcast with **realistic AI voices**. 🚀"
)

# Get pre-selected topic from sidebar
pre_selected_topic = st.session_state.get("topic", "")

# Input for Podcast Topic
topic = st.text_input(
    "📖 **Enter Your Podcast Topic Below:**",
    placeholder="E.g., How AI is Changing the Job Market",
    value=pre_selected_topic,
)

# Check if auto-generation is triggered
generate_now = st.session_state.get("generate", False)


# Generate Podcast Function
def generate_and_display_podcast(topic):
    with st.spinner("⏳ Generating Podcast... This may take up to 2 minute..."):
        audio_path = generate_podcast(topic, selected_voice)

    if audio_path:
        st.success("✅ Podcast generated successfully!")

        st.subheader("🎧 Your AI Podcast")
        st.audio(audio_path, format="audio/wav")

        with open(audio_path, "rb") as audio_file:
            st.download_button(
                "⬇️ Download Podcast",
                audio_file,
                file_name="podcast.wav",
                mime="audio/wav",
            )

    else:
        st.error("❌ Failed to generate podcast. Please try again.")


# Auto-generate podcast if a trending topic is selected
if generate_now and topic:
    generate_and_display_podcast(topic)
    st.session_state["generate"] = False  # Reset the flag after generation

# Manual Generate Podcast Button
if st.button("🎬 Generate Podcast"):
    if topic:
        generate_and_display_podcast(topic)
    else:
        st.warning("⚠️ Please enter a topic before generating.")

# Footer Section
st.markdown("---")
st.markdown(
    """
    🌟 **Features:**
    - 🎙️ AI-generated podcast scripts based on **real-time research**.
    - 🗣️ Multiple **realistic voices** for narration.
    - 📥 **Download & share** your podcasts instantly.

    📢 **Disclaimer:** AI-generated content is based on available online data and may not always be accurate.
    """,
    unsafe_allow_html=True,
)
st.markdown("---")
st.markdown(":orange_heart: **Thank you for using Podify AI!**")
