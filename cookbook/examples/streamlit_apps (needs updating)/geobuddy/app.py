import os
from pathlib import Path

import streamlit as st
from geography_buddy import analyze_image
from PIL import Image

# Streamlit App Configuration
st.set_page_config(
    page_title="Geography Location Buddy",
    page_icon="🌍",
)
st.title("GeoBuddy 🌍")
st.markdown("##### :orange_heart: built by [agno](https://github.com/agno-agi/agno)")
st.markdown(
    """
    **Upload your image** and let model guess the location based on visual cues such as landmarks, architecture, and more.
    """
)


def main() -> None:
    # Sidebar Design
    with st.sidebar:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("let me guess the location based on visible cues from your image!")

        # Upload Image
        uploaded_file = st.file_uploader(
            "📷 Upload here..", type=["jpg", "jpeg", "png"]
        )
        st.markdown("---")

    # App Logic
    if uploaded_file:
        col1, col2 = st.columns([1, 2])

        # Display Uploaded Image
        with col1:
            st.markdown("#### Uploaded Image")
            image = Image.open(uploaded_file)
            resized_image = image.resize((400, 400))
            image_path = Path("temp_image.png")
            with open(image_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.image(resized_image, caption="Your Image", use_container_width=True)

        # Analyze Button and Output
        with col2:
            st.markdown("#### Location Analysis")
            analyze_button = st.button("🔍 Analyze Image")

            if analyze_button:
                with st.spinner("Analyzing the image... please wait."):
                    try:
                        result = analyze_image(image_path)
                        if result:
                            st.success("🌍 Here's my guess:")
                            st.markdown(result)
                        else:
                            st.warning(
                                "Sorry, I couldn't determine the location. Try another image."
                            )
                    except Exception as e:
                        st.error(f"An error occurred: {e}")

                # Cleanup after analysis
                if image_path.exists():
                    os.remove(image_path)
            else:
                st.info("Click the **Analyze** button to get started!")
    else:
        st.info("📷 Please upload an image to begin location analysis.")

    # Footer Section
    st.markdown("---")
    st.markdown(
        """
        **🌟 Features**:
        - Identify locations based on uploaded images.
        - Advanced reasoning based on landmarks, architecture, and cultural clues.

        **📢 Disclaimer**: GeoBuddy's guesses are based on visual cues and analysis and may not always be accurate.
        """
    )
    st.markdown(":orange_heart: Thank you for using GeoBuddy!")


main()
