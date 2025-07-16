import streamlit as st
from agno.agent import Agent
from agno.utils.log import logger


def knowledge_base_info_widget(agent: Agent) -> None:
    if not agent.knowledge:
        st.sidebar.info("No knowledge base configured")
        return

    vector_store = getattr(agent.knowledge, "vector_store", None)
    if not vector_store:
        st.sidebar.info("No vector store configured")
        return

    try:
        doc_count = vector_store.get_count()
        if doc_count == 0:
            st.sidebar.info("💡 Upload documents to populate the knowledge base")
        else:
            st.sidebar.metric("Documents Loaded", doc_count)
    except Exception as e:
        logger.error(f"Error getting knowledge base info: {e}")
        st.sidebar.warning("Could not retrieve knowledge base information")
