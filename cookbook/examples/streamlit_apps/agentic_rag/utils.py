import streamlit as st
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat


def get_model_from_id(model_id: str):
    """Get a model instance from a model ID string."""
    if model_id.startswith("openai:"):
        return OpenAIChat(id=model_id.split("openai:")[1])
    elif model_id.startswith("anthropic:"):
        return Claude(id=model_id.split("anthropic:")[1])
    elif model_id.startswith("google:"):
        return Gemini(id=model_id.split("google:")[1])
    else:
        return OpenAIChat(id="gpt-4o")


def about_section():
    """About section"""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.markdown("""
    This Agentic RAG Assistant helps you analyze documents and web content using natural language queries.

    Built with:
    - 🚀 Agno
    - 💫 Streamlit
    """)


MODELS = [
    "gpt-4o",
    "o3-mini",
    "gpt-5",
    "claude-4-sonnet",
    "gemini-2.5-pro",
]
