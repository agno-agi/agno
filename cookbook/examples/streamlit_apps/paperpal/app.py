import json
from typing import Optional

import pandas as pd
import streamlit as st
from technical_writer import (
    ArxivSearchResults,
    SearchTerms,
    WebSearchResults,
    arxiv_search_agent,
    arxiv_toolkit,
    exa_search_agent,
    research_editor,
    search_term_generator,
)

# Streamlit App Configuration
st.set_page_config(
    page_title="AI Researcher Workflow",
    page_icon=":orange_heart:",
)
st.title("Paperpal")
st.markdown("##### :orange_heart: built by [agno](https://github.com/agno-agi/agno)")


def main() -> None:
    # Get topic for report
    input_topic = st.sidebar.text_input(
        ":female-scientist: Enter a topic",
        value="LLM evals in multi-agentic space",
    )
    # Button to generate blog
    generate_report = st.sidebar.button("Generate Blog")
    if generate_report:
        st.session_state["topic"] = input_topic

    # Checkboxes for search
    st.sidebar.markdown("## Agents")
    search_exa = st.sidebar.checkbox("Exa Search", value=True)
    search_arxiv = st.sidebar.checkbox("ArXiv Search", value=False)
    # search_pubmed = st.sidebar.checkbox("PubMed Search", disabled=True)  # noqa
    # search_google_scholar = st.sidebar.checkbox("Google Scholar Search", disabled=True)  # noqa
    # use_cache = st.sidebar.toggle("Use Cache", value=False, disabled=True)  # noqa
    num_search_terms = st.sidebar.number_input(
        "Number of Search Terms",
        value=2,
        min_value=2,
        max_value=3,
        help="This will increase latency.",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("## Trending Topics")
    topic = "Humanoid and Autonomous Agents"
    if st.sidebar.button(topic):
        st.session_state["topic"] = topic

    topic = "Gene Editing for Disease Treatment"
    if st.sidebar.button(topic):
        st.session_state["topic"] = topic

    topic = "Multimodal AI in healthcare"
    if st.sidebar.button(topic):
        st.session_state["topic"] = topic

    topic = "Brain Aging and Neurodegenerative Diseases"
    if st.sidebar.button(topic):
        st.session_state["topic"] = topic

    if "topic" in st.session_state:
        report_topic = st.session_state["topic"]

        search_terms: Optional[SearchTerms] = None
        with st.status("Generating Search Terms", expanded=True) as status:
            with st.container():
                search_terms_container = st.empty()
                search_generator_input = {
                    "topic": report_topic,
                    "num_terms": num_search_terms,
                }
                search_terms = search_term_generator.run(
                    json.dumps(search_generator_input)
                ).content
                if search_terms:
                    search_terms_container.json(search_terms.model_dump())
            status.update(
                label="Search Terms Generated", state="complete", expanded=False
            )

        if not search_terms:
            st.write("Sorry report generation failed. Please try again.")
            return

        exa_content: Optional[str] = None
        arxiv_content: Optional[str] = None

        if search_exa:
            with st.status("Searching Exa", expanded=True) as status:
                with st.container():
                    exa_container = st.empty()
                    try:
                        exa_search_results = exa_search_agent.run(
                            search_terms.model_dump_json(indent=4)
                        )
                        if isinstance(exa_search_results, str):
                            raise ValueError(
                                "Unexpected string response from exa_search_agent"
                            )

                        if isinstance(exa_search_results.content, WebSearchResults):
                            exa_container.json(exa_search_results.content.results)
                            if (
                                exa_search_results
                                and exa_search_results.content
                                and len(exa_search_results.content.results) > 0
                            ):
                                exa_content = (
                                    exa_search_results.content.model_dump_json(indent=4)
                                )
                                exa_container.json(exa_search_results.content.results)
                                status.update(
                                    label="Exa Search Complete",
                                    state="complete",
                                    expanded=False,
                                )
                        else:
                            raise TypeError("Unexpected response from exa_search_agent")

                    except Exception as e:
                        st.error(f"An error occurred during Exa search: {e}")
                        status.update(
                            label="Exa Search Failed", state="error", expanded=True
                        )
                        exa_content = None

        if search_arxiv:
            with st.status(
                "Searching ArXiv (this takes a while)", expanded=True
            ) as status:
                with st.container():
                    arxiv_container = st.empty()
                    arxiv_search_results = arxiv_search_agent.run(
                        search_terms.model_dump_json(indent=4)
                    )
                    if isinstance(arxiv_search_results.content, ArxivSearchResults):
                        if (
                            arxiv_search_results
                            and arxiv_search_results.content
                            and arxiv_search_results.content.results
                        ):
                            arxiv_container.json(
                                [
                                    result.model_dump()
                                    for result in arxiv_search_results.content.results
                                ]
                            )
                    else:
                        raise TypeError("Unexpected response from arxiv_search_agent")

                status.update(
                    label="ArXiv Search Complete", state="complete", expanded=False
                )

            if (
                arxiv_search_results
                and arxiv_search_results.content
                and arxiv_search_results.content.results
            ):
                paper_summaries = []
                for result in arxiv_search_results.content.results:
                    summary = {
                        "ID": result.id,
                        "Title": result.title,
                        "Authors": ", ".join(result.authors)
                        if result.authors
                        else "No authors available",
                        "Summary": result.summary[:200] + "..."
                        if len(result.summary) > 200
                        else result.summary,
                    }
                    paper_summaries.append(summary)

                if paper_summaries:
                    with st.status(
                        "Displaying ArXiv Paper Summaries", expanded=True
                    ) as status:
                        with st.container():
                            st.subheader("ArXiv Paper Summaries")
                            df = pd.DataFrame(paper_summaries)
                            st.dataframe(df, use_container_width=True)
                        status.update(
                            label="ArXiv Paper Summaries Displayed",
                            state="complete",
                            expanded=False,
                        )

                    arxiv_paper_ids = [summary["ID"] for summary in paper_summaries]
                    if arxiv_paper_ids:
                        with st.status("Reading ArXiv Papers", expanded=True) as status:
                            with st.container():
                                arxiv_content = arxiv_toolkit.read_arxiv_papers(
                                    arxiv_paper_ids, pages_to_read=2
                                )
                                st.write(f"Read {len(arxiv_paper_ids)} ArXiv papers")
                            status.update(
                                label="Reading ArXiv Papers Complete",
                                state="complete",
                                expanded=False,
                            )

        report_input = ""
        report_input += f"# Topic: {report_topic}\n\n"
        report_input += "## Search Terms\n\n"
        report_input += f"{search_terms}\n\n"
        if arxiv_content:
            report_input += "## ArXiv Papers\n\n"
            report_input += "<arxiv_papers>\n\n"
            report_input += f"{arxiv_content}\n\n"
            report_input += "</arxiv_papers>\n\n"
        if exa_content:
            report_input += "## Web Search Content from Exa\n\n"
            report_input += "<exa_content>\n\n"
            report_input += f"{exa_content}\n\n"
            report_input += "</exa_content>\n\n"

        # Only generate the report if we have content
        if arxiv_content or exa_content:
            with st.spinner("Generating Blog"):
                final_report_container = st.empty()
                research_report = research_editor.run(report_input)
                final_report_container.markdown(research_report.content)
        else:
            st.error(
                "Report generation cancelled due to search failure. Please try again or select another search option."
            )

    st.sidebar.markdown("---")
    if st.sidebar.button("Restart"):
        st.rerun()


main()
