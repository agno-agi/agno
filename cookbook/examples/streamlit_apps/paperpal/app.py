import json

import nest_asyncio
import pandas as pd
import streamlit as st
from agents import (
    ArxivSearchResults,
    SearchTerms,
    WebSearchResults,
    get_paperpal_agents,
)
from agno.utils.streamlit import (
    COMMON_CSS,
    MODELS,
    about_section,
    add_message,
    display_chat_messages,
    display_response,
    export_chat_history,
    reset_session_state,
    session_selector_widget,
)

nest_asyncio.apply()
st.set_page_config(
    page_title="Paperpal Research Assistant",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Add custom CSS
st.markdown(COMMON_CSS, unsafe_allow_html=True)


def get_main_agent(model_id: str = None, session_id: str = None):
    """Get the main research editor agent for session management"""
    agents = get_paperpal_agents(model_id=model_id, session_id=session_id)
    return agents["research_editor"]


def restart_session(model_id: str = None):
    target_model = model_id or st.session_state.get("current_model", MODELS[0])

    # Clear all research-related session state
    keys_to_clear = [
        "research_topic",
        "search_terms",
        "arxiv_results",
        "exa_results",
        "final_blog",
        "research_agents",
        "messages",
        "session_id",
    ]
    for key in keys_to_clear:
        st.session_state.pop(key, None)

    # Initialize new agents
    st.session_state["research_agents"] = get_paperpal_agents(model_id=target_model)
    st.session_state["current_model"] = target_model
    st.session_state["is_new_session"] = True


def on_model_change():
    selected_model = st.session_state.get("model_selector")
    if selected_model:
        if selected_model in MODELS:
            new_model_id = selected_model
            current_model = st.session_state.get("current_model")

            if current_model and current_model != new_model_id:
                try:
                    st.session_state["is_loading_session"] = False
                    restart_session(model_id=new_model_id)
                except Exception as e:
                    st.sidebar.error(f"Error switching to {selected_model}: {str(e)}")
        else:
            st.sidebar.error(f"Unknown model: {selected_model}")


def main():
    ####################################################################
    # App header
    ####################################################################
    st.markdown(
        "<h1 class='main-title'>Paperpal Research Assistant</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='subtitle'>AI-powered research workflow for technical blog generation</p>",
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
        on_change=on_model_change,
    )

    ####################################################################
    # Initialize Research Agents
    ####################################################################
    if (
        "research_agents" not in st.session_state
        or not st.session_state["research_agents"]
    ):
        st.session_state["research_agents"] = get_paperpal_agents(
            model_id=selected_model
        )
        st.session_state["current_model"] = selected_model

    # Get main agent for session management
    main_agent = get_main_agent(selected_model)
    reset_session_state(main_agent)

    if prompt := st.chat_input(
        "💭 Ask me anything about research or start a new research project!"
    ):
        add_message("user", prompt)

    ####################################################################
    # Research Configuration
    ####################################################################
    st.sidebar.markdown("#### 🔍 Research Configuration")

    # Topic input
    research_topic = st.sidebar.text_input(
        "Research Topic",
        value=st.session_state.get("research_topic", ""),
        placeholder="Enter your research topic...",
        help="Provide a specific research topic you want to explore",
    )

    # Research options
    col1, col2 = st.sidebar.columns([1, 1])
    with col1:
        enable_arxiv = st.sidebar.checkbox(
            "📚 ArXiv Search", value=True, help="Search academic papers"
        )
    with col2:
        enable_exa = st.sidebar.checkbox(
            "🌐 Web Search", value=True, help="Search web content"
        )

    num_search_terms = st.sidebar.number_input(
        "Search Terms",
        value=2,
        min_value=2,
        max_value=3,
        help="Number of strategic search terms to generate",
    )

    # Generate research button
    if st.sidebar.button("🚀 Start Research", type="primary", use_container_width=True):
        if research_topic.strip():
            st.session_state["research_topic"] = research_topic.strip()
            st.session_state["enable_arxiv"] = enable_arxiv
            st.session_state["enable_exa"] = enable_exa
            st.session_state["num_search_terms"] = num_search_terms
            add_message("user", f"🔬 Research Request: {research_topic}")
        else:
            st.sidebar.error("Please enter a research topic")

    ####################################################################
    # Trending Topics
    ####################################################################
    st.sidebar.markdown("#### 🔥 Trending Topics")
    trending_topics = [
        "Multimodal AI in autonomous systems",
        "Quantum machine learning algorithms",
        "LLM safety and alignment research",
        "Neural symbolic reasoning frameworks",
        "Federated learning in edge computing",
    ]

    for topic in trending_topics:
        if st.sidebar.button(f"📖 {topic}", use_container_width=True):
            st.session_state["research_topic"] = topic
            add_message("user", f"🔬 Research Request: {topic}")

    ###############################################################
    # Utility buttons
    ###############################################################
    st.sidebar.markdown("#### 🛠️ Utilities")
    col1, col2 = st.sidebar.columns([1, 1])
    with col1:
        if st.sidebar.button("🔄 New Research", use_container_width=True):
            restart_session()
            st.rerun()

    with col2:
        has_messages = (
            st.session_state.get("messages") and len(st.session_state["messages"]) > 0
        )

        if has_messages:
            session_id = st.session_state.get("session_id")
            if session_id:
                try:
                    session_name = main_agent.get_session_name()
                    if session_name:
                        filename = f"paperpal_research_{session_name}.md"
                    else:
                        filename = f"paperpal_research_{session_id}.md"
                except Exception:
                    filename = f"paperpal_research_{session_id}.md"
            else:
                filename = "paperpal_research_new.md"

            if st.sidebar.download_button(
                "💾 Export Research",
                export_chat_history("Paperpal Research"),
                file_name=filename,
                mime="text/markdown",
                use_container_width=True,
                help=f"Export {len(st.session_state['messages'])} messages",
            ):
                st.sidebar.success("Research exported!")
        else:
            st.sidebar.button(
                "💾 Export Research",
                disabled=True,
                use_container_width=True,
                help="No research to export",
            )

    ####################################################################
    # Display Chat Messages
    ####################################################################
    display_chat_messages()

    ####################################################################
    # Process Research Request
    ####################################################################
    last_message = (
        st.session_state["messages"][-1] if st.session_state["messages"] else None
    )
    if last_message and last_message.get("role") == "user":
        question = last_message["content"]

        # Check if this is a research request
        if question.startswith("🔬 Research Request:") and st.session_state.get(
            "research_topic"
        ):
            process_research_workflow()
        else:
            # Regular chat interaction
            display_response(main_agent, question)

    ####################################################################
    # Session management widgets
    ####################################################################
    session_selector_widget(main_agent, selected_model, get_main_agent)

    ####################################################################
    # About section
    ####################################################################
    about_section(
        "Paperpal is an AI-powered research assistant that helps you create comprehensive technical blogs "
        "by synthesizing information from academic papers and web sources."
    )


def process_research_workflow():
    """Process the complete research workflow"""
    topic = st.session_state.get("research_topic")
    if not topic:
        return

    agents = st.session_state.get("research_agents", {})
    if not agents:
        st.error("Research agents not initialized. Please refresh the page.")
        return

    with st.chat_message("assistant"):
        # Step 1: Generate Search Terms
        if not st.session_state.get("search_terms"):
            with st.status(
                "🔍 Generating strategic search terms...", expanded=True
            ) as status:
                try:
                    search_input = {
                        "topic": topic,
                        "num_terms": st.session_state.get("num_search_terms", 2),
                    }

                    response = agents["search_term_generator"].run(
                        json.dumps(search_input)
                    )
                    if isinstance(response.content, SearchTerms):
                        st.session_state["search_terms"] = response.content
                        st.json(response.content.model_dump())
                        status.update(
                            label="✅ Search terms generated",
                            state="complete",
                            expanded=False,
                        )
                    else:
                        raise ValueError(
                            "Invalid response format from search term generator"
                        )

                except Exception as e:
                    st.error(f"Error generating search terms: {str(e)}")
                    status.update(
                        label="❌ Search term generation failed", state="error"
                    )
                    return

        search_terms = st.session_state.get("search_terms")
        if not search_terms:
            return

        # Step 2: ArXiv Search
        if st.session_state.get("enable_arxiv", True) and not st.session_state.get(
            "arxiv_results"
        ):
            with st.status(
                "📚 Searching ArXiv for research papers...", expanded=True
            ) as status:
                try:
                    arxiv_response = agents["arxiv_search_agent"].run(
                        search_terms.model_dump_json(indent=2)
                    )
                    if isinstance(arxiv_response.content, ArxivSearchResults):
                        st.session_state["arxiv_results"] = arxiv_response.content

                        # Display results as table
                        if arxiv_response.content.results:
                            df_data = []
                            for result in arxiv_response.content.results:
                                df_data.append(
                                    {
                                        "Title": result.title[:80] + "..."
                                        if len(result.title) > 80
                                        else result.title,
                                        "Authors": ", ".join(result.authors[:3])
                                        + ("..." if len(result.authors) > 3 else ""),
                                        "ID": result.id,
                                        "Reasoning": result.reasoning[:100] + "..."
                                        if len(result.reasoning) > 100
                                        else result.reasoning,
                                    }
                                )

                            df = pd.DataFrame(df_data)
                            st.dataframe(df, use_container_width=True)
                            status.update(
                                label="✅ ArXiv search completed",
                                state="complete",
                                expanded=False,
                            )

                except Exception as e:
                    st.error(f"ArXiv search error: {str(e)}")
                    status.update(label="❌ ArXiv search failed", state="error")

        # Step 3: Web Search
        if st.session_state.get("enable_exa", True) and not st.session_state.get(
            "exa_results"
        ):
            with st.status(
                "🌐 Searching web for current insights...", expanded=True
            ) as status:
                try:
                    exa_response = agents["exa_search_agent"].run(
                        search_terms.model_dump_json(indent=2)
                    )
                    if isinstance(exa_response.content, WebSearchResults):
                        st.session_state["exa_results"] = exa_response.content

                        # Display results
                        if exa_response.content.results:
                            for i, result in enumerate(exa_response.content.results, 1):
                                st.write(f"**{i}. {result.title}**")
                                st.write(
                                    result.summary[:200] + "..."
                                    if len(result.summary) > 200
                                    else result.summary
                                )
                                st.write(f"*Reasoning:* {result.reasoning}")
                                if result.links:
                                    st.write(f"🔗 [Read more]({result.links[0]})")
                                st.write("---")

                            status.update(
                                label="✅ Web search completed",
                                state="complete",
                                expanded=False,
                            )

                except Exception as e:
                    st.error(f"Web search error: {str(e)}")
                    status.update(label="❌ Web search failed", state="error")

        # Display completed web search results
        exa_results = st.session_state.get("exa_results")
        arxiv_results = st.session_state.get("arxiv_results")

        # Step 4: Generate Final Blog
        if (arxiv_results or exa_results) and not st.session_state.get("final_blog"):
            with st.status(
                "📝 Generating comprehensive research blog...", expanded=True
            ) as status:
                try:
                    # Prepare research content
                    research_content = f"# Research Topic: {topic}\n\n"
                    research_content += (
                        f"## Search Terms\n{search_terms.model_dump_json(indent=2)}\n\n"
                    )

                    if arxiv_results:
                        research_content += "## ArXiv Research Papers\n\n"
                        research_content += (
                            f"{arxiv_results.model_dump_json(indent=2)}\n\n"
                        )

                    if exa_results:
                        research_content += "## Web Research Content\n\n"
                        research_content += (
                            f"{exa_results.model_dump_json(indent=2)}\n\n"
                        )

                    # Generate blog
                    blog_response = agents["research_editor"].run(research_content)
                    st.session_state["final_blog"] = blog_response.content

                    status.update(
                        label="✅ Research blog generated",
                        state="complete",
                        expanded=False,
                    )

                except Exception as e:
                    st.error(f"Blog generation error: {str(e)}")
                    status.update(label="❌ Blog generation failed", state="error")


if __name__ == "__main__":
    main()
