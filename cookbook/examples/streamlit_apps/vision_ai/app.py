from pathlib import Path

import streamlit as st
from agno.media import Image
from agno.utils.streamlit import (
    COMMON_CSS,
    MODELS,
    about_section,
    add_message,
)
from agents import EXTRACTION_PROMPT, get_chat_agent, get_vision_agent

st.set_page_config(
    page_title="Vision AI",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


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
        help="Choose the AI model for image analysis"
    )

    ####################################################################
    # Analysis Settings
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
        """
    )
    
    enable_search = st.sidebar.checkbox(
        "Enable Web Search",
        value=False,
        help="Allow the agent to search for additional context"
    )

    ####################################################################
    # Initialize session state
    ####################################################################
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "last_analysis" not in st.session_state:
        st.session_state["last_analysis"] = None
    if "current_image_path" not in st.session_state:
        st.session_state["current_image_path"] = None

    ####################################################################
    # Image Upload Section
    ####################################################################
    uploaded_file = st.file_uploader(
        "📤 Upload an Image",
        type=["png", "jpg", "jpeg"],
        help="Supported formats: PNG, JPG, JPEG (Max: 200MB)"
    )

    if uploaded_file:
        # Display image preview
        st.sidebar.markdown("#### 🖼️ Current Image")
        st.sidebar.image(uploaded_file, use_container_width=True)
        
        # Save uploaded file
        temp_dir = Path("tmp")
        temp_dir.mkdir(exist_ok=True)
        image_path = temp_dir / uploaded_file.name
        
        with open(image_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        st.session_state["current_image_path"] = str(image_path)
        
        # Check if this is a new image (reset analysis if so)
        if st.session_state.get("last_image_name") != uploaded_file.name:
            st.session_state["last_analysis"] = None
            st.session_state["messages"] = []
            st.session_state["last_image_name"] = uploaded_file.name

    ####################################################################
    # Analysis Instructions (for Manual/Hybrid modes)
    ####################################################################
    custom_instructions = None
    if analysis_mode in ["Manual", "Hybrid"]:
        st.sidebar.markdown("#### 📝 Custom Instructions")
        custom_instructions = st.sidebar.text_area(
            "Analysis Instructions",
            placeholder="e.g., Focus on text extraction, identify people, analyze colors...",
            help="Provide specific instructions for image analysis"
        )

    ####################################################################
    # Analyze Image Button
    ####################################################################
    st.sidebar.markdown("#### 🔍 Image Analysis")
    
    if st.sidebar.button("🖼️ Analyze Image", type="primary", use_container_width=True):
        if not st.session_state.get("current_image_path"):
            st.sidebar.warning("⚠️ Please upload an image first.")
        elif analysis_mode == "Manual" and not custom_instructions:
            st.sidebar.warning("⚠️ Please provide analysis instructions for Manual mode.")
        else:
            with st.spinner("🔍 Analyzing image... This may take a moment..."):
                try:
                    # Get vision agent
                    vision_agent = get_vision_agent(model_id=selected_model)
                    
                    # Prepare analysis prompt
                    if analysis_mode == "Auto":
                        prompt = EXTRACTION_PROMPT
                    elif analysis_mode == "Manual":
                        prompt = custom_instructions
                    else:  # Hybrid
                        prompt = f"{EXTRACTION_PROMPT}\n\nAdditional Instructions:\n{custom_instructions}"
                    
                    # Analyze image
                    response = vision_agent.run(
                        prompt,
                        images=[Image(filepath=st.session_state["current_image_path"])]
                    )
                    
                    st.session_state["last_analysis"] = response.content
                    st.success("✅ Image analysis completed!")
                    
                except Exception as e:
                    st.error(f"❌ Error analyzing image: {str(e)}")

    ####################################################################
    # Display Analysis Results
    ####################################################################
    if st.session_state["last_analysis"]:
        st.markdown("### 🔍 Analysis Results")
        st.markdown(st.session_state["last_analysis"])
        
        st.markdown("---")
        st.markdown("### 💬 Ask Follow-up Questions")
        st.markdown("You can now ask questions about the analyzed image!")

    elif st.session_state.get("current_image_path"):
        st.markdown("### 🎯 Ready to Analyze")
        st.info("Image uploaded! Click 'Analyze Image' in the sidebar to start the analysis.")
        
        # Show image preview in main area
        st.image(st.session_state["current_image_path"], caption="Uploaded Image", use_container_width=True)

    else:
        st.markdown("### 🖼️ How to Get Started")
        st.markdown("""
        1. **Upload an Image** - Select a PNG, JPG, or JPEG file
        2. **Choose Analysis Mode** - Auto, Manual, or Hybrid
        3. **Add Instructions** (if using Manual/Hybrid mode)
        4. **Analyze** - Click 'Analyze Image' to start
        5. **Ask Questions** - Chat about the analysis results

        💡 **Tip:** Try different analysis modes to get the insights you need!
        """)

    ####################################################################
    # Chat Interface
    ####################################################################
    if st.session_state["last_analysis"]:
        # Display chat messages
        for message in st.session_state["messages"]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # Chat input
        if prompt := st.chat_input("💬 Ask about the image..."):
            add_message("user", prompt)
            
            with st.chat_message("user"):
                st.markdown(prompt)
            
            with st.chat_message("assistant"):
                response_container = st.empty()
                with st.spinner("🤔 Thinking..."):
                    try:
                        # Get chat agent
                        chat_agent = get_chat_agent(
                            model_id=selected_model,
                            enable_search=enable_search
                        )
                        
                        # Prepare context with image analysis
                        context_prompt = f"""
                        Previous Image Analysis:
                        {st.session_state["last_analysis"]}
                        
                        User Question: {prompt}
                        
                        Please answer the user's question based on the image analysis above.
                        """
                        
                        response = chat_agent.run(context_prompt)
                        response_text = response.content
                        
                        response_container.markdown(response_text)
                        add_message("assistant", response_text)
                        
                    except Exception as e:
                        error_message = f"❌ Error: {str(e)}"
                        response_container.error(error_message)
                        add_message("assistant", error_message)

    ####################################################################
    # Utility buttons
    ####################################################################
    if st.session_state["last_analysis"] or st.session_state["messages"]:
        st.sidebar.markdown("#### 🛠️ Utilities")
        
        if st.sidebar.button("🗑️ Clear Analysis", use_container_width=True):
            st.session_state["last_analysis"] = None
            st.session_state["messages"] = []
            st.session_state["current_image_path"] = None
            if "last_image_name" in st.session_state:
                del st.session_state["last_image_name"]
            st.rerun()

    ####################################################################
    # Sample Questions
    ####################################################################
    if st.session_state["last_analysis"]:
        st.sidebar.markdown("#### ❓ Sample Questions")
        sample_questions = [
            "🔍 What are the main objects?",
            "📝 Is there any text to read?",
            "🎨 Describe the colors and mood",
            "👥 Are there people in the image?",
            "📍 What's the setting or location?",
            "🔧 Any technical details?",
        ]
        
        for question in sample_questions:
            if st.sidebar.button(question, key=f"sample_{question}", use_container_width=True):
                # Remove emoji and use as prompt
                clean_question = question[2:]  # Remove emoji and space
                add_message("user", clean_question)
                st.rerun()

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This Vision AI assistant analyzes images and answers questions about visual content using "
        "advanced vision-language models."
    )


if __name__ == "__main__":
    main()
