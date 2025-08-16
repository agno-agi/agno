import base64
import json
import time
from datetime import datetime
from os import getenv

import streamlit as st
from agents import DeepResearcherAgent

st.set_page_config(
    page_title="Deep Research Agent",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize session state for chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

with open(
    "cookbook/examples/streamlit_apps/deep_researcher/assets/scrapegraph.png", "rb"
) as scrapegraph_file:
    scrapegraph_base64 = base64.b64encode(scrapegraph_file.read()).decode()

    title_html = f"""
    <div style="display: flex; justify-content: center; align-items: center; width: 100%; padding: 32px 0 24px 0;">
        <h1 style="margin: 0; padding: 0; font-size: 2.5rem; font-weight: bold;">
            <span style="font-size:2.5rem;">🔎</span> Agentic Deep Searcher with 
            <span style="color: #fb542c;">Agno</span> & 
            <span style="color: #8564ff;">Scrapegraph</span>
            <img src="data:image/png;base64,{scrapegraph_base64}" style="height: 60px; margin-left: 12px; vertical-align: middle;"/>
        </h1>
    </div>
    """
    st.markdown(title_html, unsafe_allow_html=True)

with st.sidebar:
    st.image(
        "cookbook/examples/streamlit_apps/deep_researcher/assets/nebius.png", width=150
    )
    nebius_api_key = getenv("NEBIUS_API_KEY")
    if not nebius_api_key:
        nebius_api_key = st.text_input("Enter your Nebius API key", type="password")

    scrapegraph_api_key = getenv("SGAI_API_KEY")
    if not scrapegraph_api_key:
        scrapegraph_api_key = st.text_input(
            "Enter your Scrapegraph API key", type="password"
        )

    st.divider()

    # Example research topics
    st.header("🔍 Try These Examples")
    st.markdown("Click any topic below to start an instant deep research:")

    example_topics = [
        "🚀 Latest developments in AI and machine learning in 2024",
        "🌱 Current trends in sustainable energy technologies",
        "💊 Recent breakthroughs in personalized medicine and genomics",
    ]

    if "trigger_research" not in st.session_state:
        st.session_state.trigger_research = None

    for topic in example_topics:
        topic_text = topic.split(" ", 1)[1]  # Remove emoji and space
        if st.button(topic, use_container_width=True, key=f"example_{topic_text}"):
            st.session_state.trigger_research = topic_text
            st.rerun()

    st.divider()

    # Chat management buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🆕 New Chat", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()

        with col2:
            if st.session_state.chat_history:
                markdown_content = "# 🔎 Deep Research Agent - Chat History\n\n"

                for i, conversation in enumerate(st.session_state.chat_history, 1):
                    markdown_content += f"## {conversation['question']}\n\n"
                    markdown_content += f"{conversation['response']}\n\n"
                    if i < len(st.session_state.chat_history):
                        markdown_content += "---\n\n"

                st.download_button(
                    label="📥 Export Chat",
                    data=markdown_content,
                    file_name=f"deep_research_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            else:
                st.button("📥 Export Chat", use_container_width=True, disabled=True)

    st.divider()

    st.header("About")
    st.markdown(
        """
    This Deep Researcher workflow leverages multiple AI agents for a comprehensive research process:
    - **Searcher**: Finds and extracts information from the web.
    - **Analyst**: Synthesizes and interprets the research findings.
    - **Writer**: Produces a final, polished report.

    Built with:
    - 🚀 Agno
    - 💫 Streamlit
    """
    )

# Display chat history
if st.session_state.chat_history:
    st.subheader("💬 Chat History")

    for i, conversation in enumerate(st.session_state.chat_history):
        with st.container():
            with st.chat_message("user"):
                st.write(conversation["question"])

            with st.chat_message("assistant"):
                st.markdown(conversation["response"])
                st.caption(f"Research completed at: {conversation['timestamp']}")

            if i < len(st.session_state.chat_history) - 1:
                st.divider()

user_input = st.chat_input("Ask a question...")

if st.session_state.trigger_research:
    user_input = st.session_state.trigger_research
    st.session_state.trigger_research = None

    with st.chat_message("user"):
        st.write(user_input)

if user_input:
    try:
        agent = DeepResearcherAgent()

        current_conversation = {
            "question": user_input,
            "response": "",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        with st.status("Executing research plan...", expanded=True) as status:
            # PHASE 1: Researching
            phase1_msg = "🧠 **Phase 1: Researching** - Finding and extracting relevant information from the web..."
            status.write(phase1_msg)
            research_content = agent.searcher.run(user_input)

            # PHASE 2: Analyzing
            phase2_msg = "🔬 **Phase 2: Analyzing** - Synthesizing and interpreting the research findings..."
            status.write(phase2_msg)
            analysis = agent.analyst.run(research_content.content)

            # PHASE 3: Writing Report
            phase3_msg = (
                "✍️ **Phase 3: Writing Report** - Producing a final, polished report..."
            )
            status.write(phase3_msg)
            report_iterator = agent.writer.run(analysis.content, stream=True)

        # Collect the full report
        full_report = ""
        report_container = st.empty()
        with st.spinner("🤔 Thinking..."):
            for chunk in report_iterator:
                if chunk.content:
                    full_report += chunk.content
                    report_container.markdown(full_report)

        # Store the complete conversation
        current_conversation["response"] = full_report
        st.session_state.chat_history.append(current_conversation)

        st.rerun()

    except Exception as e:
        st.error(f"An error occurred: {e}")
