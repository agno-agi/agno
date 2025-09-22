import nest_asyncio
import streamlit as st
from agents import get_deep_researcher_workflow
from agno.utils.streamlit import (
    COMMON_CSS,
    about_section,
    add_message,
    display_chat_messages,
    export_chat_history,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="Deep Researcher",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown("<h1 class='main-title'>Deep Researcher</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='subtitle'>Your AI-powered research assistant with multi-agent workflow</p>",
        unsafe_allow_html=True,
    )

    ####################################################################
    # Initialize Workflow
    ####################################################################
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    if prompt := st.chat_input("🔎 What would you like me to research?"):
        add_message("user", prompt)

    ####################################################################
    # API Configuration
    ####################################################################
    st.sidebar.markdown("#### 🔑 Configuration")

    nebius_api_key = st.sidebar.text_input(
        "Nebius API Key",
        type="password",
        help="Required for powering the research agents",
        placeholder="nebius_xxxxxxxxxxxx",
    )

    scrapegraph_api_key = st.sidebar.text_input(
        "ScrapeGraph API Key",
        type="password",
        help="Required for web scraping and content extraction",
        placeholder="sgai_xxxxxxxxxxxx",
    )

    if nebius_api_key and scrapegraph_api_key:
        st.sidebar.success("✅ API keys configured")
    else:
        st.sidebar.warning("⚠️ Please configure your API keys to start researching")

    ###############################################################
    # Example Research Topics
    ###############################################################
    st.sidebar.markdown("#### 🔍 Example Topics")

    if st.sidebar.button("🚀 AI & ML Developments 2024"):
        add_message("user", "Latest developments in AI and machine learning in 2024")

    if st.sidebar.button("🌱 Sustainable Energy"):
        add_message("user", "Current trends in sustainable energy technologies")

    if st.sidebar.button("💊 Personalized Medicine"):
        add_message(
            "user", "Recent breakthroughs in personalized medicine and genomics"
        )

    if st.sidebar.button("🔒 Quantum Cybersecurity"):
        add_message("user", "Impact of quantum computing on cybersecurity")

    ###############################################################
    # Utility buttons
    ###############################################################
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns([1, 1])

    with col1:
        if st.sidebar.button("🔄 New Research", use_container_width=True):
            st.session_state["messages"] = []
            st.rerun()

    with col2:
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            if st.sidebar.download_button(
                "💾 Export Report",
                export_chat_history("Deep Research Report"),
                file_name="research_report.md",
                mime="text/markdown",
                use_container_width=True,
                help=f"Export {len(st.session_state['messages'])} messages",
            ):
                st.sidebar.success("Research report exported!")
        else:
            st.sidebar.button(
                "💾 Export Report",
                disabled=True,
                use_container_width=True,
                help="No research to export",
            )

    ####################################################################
    # Display Chat Messages
    ####################################################################
    display_chat_messages()

    ####################################################################
    # Generate research response
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )
    if last_message and last_message.get("role") == "user":
        if not (nebius_api_key and scrapegraph_api_key):
            st.error(
                "🔑 Please configure your API keys in the sidebar to start research."
            )
            return

        research_topic = last_message["content"]

        with st.chat_message("assistant"):
            # Create containers for different phases
            response_container = st.empty()

            try:
                # Get the workflow
                app = get_deep_researcher_workflow()

                # Execute the research workflow with status updates
                with st.status(
                    "🔎 Executing research workflow...", expanded=True
                ) as status:
                    status.write(
                        "🧠 **Phase 1: Researching** - Finding and extracting relevant information..."
                    )
                    status.write(
                        "📊 **Phase 2: Analyzing** - Synthesizing and interpreting the research findings..."
                    )
                    status.write(
                        "📝 **Phase 3: Writing** - Crafting the final report..."
                    )

                    result = app.run(topic=research_topic)

                    full_report = ""
                    if result and result.content:
                        full_report = result.content
                        response_container.markdown(full_report)
                    else:
                        full_report = (
                            "❌ Failed to generate research report. Please try again."
                        )
                        response_container.markdown(full_report)

                    status.update(label="✅ Research completed!", state="complete")

                # Add the complete response to messages
                add_message("assistant", full_report)

            except Exception as e:
                st.error(f"❌ Research failed: {str(e)}")
                st.info("💡 Please check your API keys and try again.")

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "This Deep Researcher uses a multi-agent workflow to conduct comprehensive research, analysis, and report generation. Built with Agno, ScrapeGraph, and Nebius AI."
    )


if __name__ == "__main__":
    main()
