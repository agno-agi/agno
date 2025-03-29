import datetime
import os
import time

import streamlit as st
from agno.models.mistral.mistral import MistralChat
from agno.models.openai import OpenAIChat
from agno.utils.log import logger
from config import PostType
from dotenv import load_dotenv
from scheduler import schedule_and_publish
from utils import about_widget, clear_generated_content, create_iso_date
from workflow import ContentPlanningWorkflow

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# Set page configuration
st.set_page_config(
    page_title="Content Creator Workflow",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_session_state():
    """Initialize session state variables"""
    if "generated_content" not in st.session_state:
        st.session_state.generated_content = None
    if "current_blog_url" not in st.session_state:
        st.session_state.current_blog_url = ""


def main():
    ####################################################################
    # App Header
    ####################################################################
    st.markdown(
        """
        <style>
            .title {
                text-align: center;
                font-size: 3em;
                font-weight: bold;
                color: white;
            }
            .subtitle {
                text-align: center;
                font-size: 1.5em;
                color: #bbb;
                margin-top: -15px;
            }
        </style>
        <h1 class='title'>Content Creator 📝</h1>
        <p class='subtitle'>Your AI-powered content generation and scheduling agent</p>
        """,
        unsafe_allow_html=True,
    )

    ####################################################################
    # Ensure session state variables are initialized
    ####################################################################
    init_session_state()

    ####################################################################
    # Sidebar Configuration
    ####################################################################
    with st.sidebar:
        st.markdown("#### 🧠 Social Media Content Creator")

        # Model Provider Selection
        model_provider = st.selectbox(
            "Select Model Provider", ["OpenAI", "Mistral"], index=0
        )

        ####################################################################
        # Ensure Model is Initialized Properly
        ####################################################################
        if (
            "model_instance" not in st.session_state
            or st.session_state.get("model_provider", None) != model_provider
        ):
            if model_provider == "OpenAI":
                if not OPENAI_API_KEY:
                    st.error(
                        "⚠️ OpenAI API key not found. Please set the OPENAI_API_KEY environment variable."
                    )
                model = OpenAIChat(id="gpt-4o", api_key=OPENAI_API_KEY)
            elif model_provider == "Mistral":
                if not MISTRAL_API_KEY:
                    st.error(
                        "⚠️ Mistral API key not found. Please set the MISTRAL_API_KEY environment variable."
                    )
                model = MistralChat(id="mistral-large-latest", api_key=MISTRAL_API_KEY)

            else:
                st.error(
                    "⚠️ Unsupported model provider. Please select OpenAI, Gemini, or Mistral."
                )
                st.stop()  # Stop execution if model is not supported

            st.session_state["model_instance"] = model
            st.session_state["model_provider"] = model_provider
        else:
            model = st.session_state["model_instance"]

        post_type = st.selectbox(
            "📱 Post On (Platform)", ["Twitter", "LinkedIn"], index=0
        )

        st.markdown("---")

        # Add clear button for content
        if st.button("🧹 Clear Current Content"):
            clear_generated_content()
            st.success("Content cleared!")

        # About section
        about_widget()

    ####################################################################
    # Main Content Area
    ####################################################################
    # Main container
    with st.container():
        st.markdown("### 🚀 Create Social Media Content")
        st.markdown(
            "Generate engaging content from blog posts and schedule it automatically."
        )

        # Input row: Blog URL, Date, Time
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            blog_url = st.text_input(
                "🔗 Blog Post URL",
                placeholder="https://example.com/blog-post",
                value=st.session_state.current_blog_url,
            )

        with col2:
            schedule_date = st.date_input("Date", value=datetime.date.today())

        with col3:
            schedule_time = st.time_input(
                "Time", value=datetime.time(hour=12, minute=0)
            )

        # Analyze Button
        if st.button("🔍 Analyze Blog & Generate Content"):
            if not blog_url:
                st.warning("⚠️ Please enter a blog post URL")
            else:
                st.session_state.current_blog_url = blog_url

                with st.spinner("🧠 Analyzing blog post and generating content..."):
                    try:
                        # Map the selected post type to the enum
                        selected_post_type = (
                            PostType.TWITTER
                            if post_type == "Twitter"
                            else PostType.LINKEDIN
                        )

                        # Generate content without scheduling
                        workflow = ContentPlanningWorkflow()
                        print(model)
                        post_content = workflow.run(
                            model=model,
                            blog_post_url=blog_url,
                            post_type=selected_post_type,
                        )

                        st.session_state.generated_content = post_content.content

                        # Create a temporary success message
                        success_message = st.empty()
                        success_message.success("✅ Content generation completed!")
                        # Wait for 1 second, then clear the success message
                        time.sleep(1)
                        success_message.empty()

                    except Exception as e:
                        st.markdown(
                            f'<div class="error-alert">❌ Error: {str(e)}</div>',
                            unsafe_allow_html=True,
                        )
                        logger.error(f"Error generating content: {str(e)}")

        # Display generated content if available
        if st.session_state.generated_content:
            if hasattr(st.session_state.generated_content, "model_dump"):
                content_data = st.session_state.generated_content.model_dump()
            else:
                content_data = st.session_state.generated_content

            st.markdown("---")
            st.markdown("### 📄 Content Preview")

            # Display Twitter thread
            if isinstance(content_data, dict) and "tweets" in content_data:
                st.write(f"#### Twitter Thread: {content_data.get('topic', '')}")

                for i, tweet in enumerate(content_data["tweets"]):
                    is_hook = tweet.get("is_hook", False)
                    tweet_class = "tweet-box hook-tweet" if is_hook else "tweet-box"

                    st.markdown(f'<div class="{tweet_class}">', unsafe_allow_html=True)
                    st.markdown(
                        f"**Tweet {i + 1}**" + (" (Hook Tweet)" if is_hook else "")
                    )

                    # Make tweet content editable
                    new_content = st.text_area(
                        f"Edit content",
                        tweet["content"],
                        height=100,
                        key=f"tweet_{i}",
                        label_visibility="collapsed",
                    )

                    # Update the content in the session state
                    if new_content != tweet["content"]:
                        content_data["tweets"][i]["content"] = new_content

                    # Show media URLs if available
                    if "media_urls" in tweet and tweet["media_urls"]:
                        st.markdown("**Media:**")
                        for url in tweet["media_urls"]:
                            st.text_input(f"Media URL {i}", url, key=f"media_{i}")

                    st.markdown("</div>", unsafe_allow_html=True)

            # Display LinkedIn post
            elif isinstance(content_data, dict) and "content" in content_data:
                st.markdown("#### LinkedIn Post")

                # Make LinkedIn content editable
                new_content = st.text_area(
                    "Edit content",
                    content_data["content"],
                    height=300,
                    label_visibility="collapsed",
                )

                # Update content in session state if edited
                if new_content != content_data["content"]:
                    content_data["content"] = new_content

                # Show media URL if available
                if "media_url" in content_data and content_data["media_url"]:
                    st.markdown("**Media:**")
                    for i, url in enumerate(content_data["media_url"]):
                        st.text_input(f"Media URL {i}", url, key=f"li_media_{i}")

            # Schedule Button (only shown when content is generated)
            st.markdown("<div style='text-align: right;'>", unsafe_allow_html=True)

            if st.button("📆 Schedule & Publish", key="schedule_button"):
                with st.spinner("📤 Scheduling content..."):
                    try:
                        # Map the selected post type to the enum
                        selected_post_type = (
                            PostType.TWITTER
                            if post_type == "Twitter"
                            else PostType.LINKEDIN
                        )

                        # Create ISO date string
                        try:
                            iso_date = create_iso_date(schedule_date, schedule_time)
                        except (TypeError, ValueError) as e:
                            st.error(f"Scheduling error: {str(e)}")
                            st.stop()

                        response = schedule_and_publish(
                            content_data, selected_post_type, iso_date
                        )

                        # Handle scheduling result
                        if (
                            response
                            and hasattr(response, "content")
                            and response.content == "Content is scheduled!"
                        ):
                            st.success("✅ Content successfully scheduled!")
                        else:
                            st.error("❌ Failed to schedule content.")
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
                        logger.error(f"Error scheduling content: {str(e)}")

            st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
