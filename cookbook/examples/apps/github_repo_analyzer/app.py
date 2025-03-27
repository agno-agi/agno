"""
GitHub Repository Analyzer App - Chat Focused
"""

import json
import logging
import os
import re

import streamlit as st

# Import agent functionality
from agents import get_github_chat_agent
from dotenv import load_dotenv
from prompts import SIDEBAR_EXAMPLE_QUERIES  # Import example queries

# Import utilities and prompts
from utils import (
    CUSTOM_CSS,
    about_widget,
    add_message,
    get_combined_repositories,
)

# App configuration
st.set_page_config(
    page_title="🐙 GitHub Repo Chat",
    page_icon="🐙",
    layout="wide",
)

# Add custom styles
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- Basic Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Load Environment Variables ---
load_dotenv()

# --- Page Header ---
st.markdown("<h1 class='main-header'>🐙 GitHub Repo Chat</h1>", unsafe_allow_html=True)
st.markdown("Chat with your GitHub repositories using natural language.")

# --- Session State Initialization ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "selected_repo" not in st.session_state:
    st.session_state.selected_repo = None
if "github_token" not in st.session_state:
    # Only get token from environment, default to None if not found
    st.session_state.github_token = os.environ.get("GITHUB_ACCESS_TOKEN")
    if not st.session_state.github_token:
        logging.warning("GITHUB_ACCESS_TOKEN environment variable not set.")
    else:
        # Mask token in logs if needed, or just log its presence
        logging.info("GITHUB_ACCESS_TOKEN found in environment.")

if "repo_list" not in st.session_state:
    st.session_state.repo_list = []
if "agent" not in st.session_state:
    st.session_state.agent = None  # Initialize agent later

# --- Sidebar for Repository Selection ---
with st.sidebar:
    # Fetch/Update repositories list
    # Fetch only if the list is currently empty
    if not st.session_state.repo_list:
        with st.spinner("Fetching repositories..."):
            # Pass the token from session state (which came from env var)
            st.session_state.repo_list = get_combined_repositories(
                st.session_state.github_token, user_repo_limit=5
            )
            if not st.session_state.repo_list:  # Handle case where even combined list is empty (shouldn't happen with POPULAR_REPOS)
                st.sidebar.warning("Could not load any repositories.")

    # Repository Selection Dropdown
    if st.session_state.repo_list:
        st.header("Select Repository")
        # Ensure agno-agi/agno is the default if nothing is selected yet
        default_repo = "agno-agi/agno"
        options = st.session_state.repo_list
        try:
            # Set default index to agno-agi/agno if available, otherwise 0
            default_index = (
                options.index(default_repo) if default_repo in options else 0
            )
        except ValueError:
            default_index = 0  # Fallback

        # Determine current selection index for persistence
        current_selection_index = default_index  # Start with default
        if st.session_state.selected_repo in options:
            try:
                current_selection_index = options.index(st.session_state.selected_repo)
            except ValueError:
                # Selected repo might have disappeared if token changed/expired and user repos are gone
                st.session_state.selected_repo = None  # Reset selection
                st.session_state.agent = None
                logging.warning(
                    "Previously selected repo not found in current list. Resetting."
                )
                st.rerun()  # Rerun to reflect reset

        selected_repo = st.selectbox(
            "Choose a repository to chat with:",
            options=options,
            index=current_selection_index,
            key="repo_selector",
        )

        # Update selected repo in session state if changed
        if selected_repo != st.session_state.selected_repo:
            st.session_state.selected_repo = selected_repo
            st.session_state.messages = []  # Clear messages when repo changes
            st.session_state.agent = None  # Re-initialize agent for the new repo
            logging.info(f"Selected repository changed to: {selected_repo}")
            st.rerun()  # Rerun to clear chat and potentially update agent context

    # Show info message if token is missing
    if not st.session_state.github_token:
        st.sidebar.info(
            "Set GITHUB_ACCESS_TOKEN environment variable to see your private/org repos."
        )

    st.markdown("---")
    st.markdown("### Example Queries")
    # Use the imported list
    for query in SIDEBAR_EXAMPLE_QUERIES:
        st.markdown(f"- {query}")

    st.markdown("---")
    about_widget()  # This now uses text from prompts.py

# --- Agent Initialization (Using agents.py function) ---
if st.session_state.selected_repo and not st.session_state.agent:
    # Check for token presence for agent tools (GithubTools relies on it)
    if not st.session_state.github_token:
        # Display persistent error if token is missing, as agent won't work
        st.error(
            "GitHub token (GITHUB_ACCESS_TOKEN env var) is missing. Agent cannot function."
        )
        st.stop()  # Stop execution if token is required for the agent

    # Proceed with agent initialization if token exists
    st.session_state.agent = get_github_chat_agent(
        st.session_state.selected_repo, debug_mode=True
    )

    if not st.session_state.agent:
        # Error handling is now within get_github_chat_agent, but we can add UI feedback
        st.error("Failed to initialize the AI agent. Check logs for details.")
    else:
        logging.info("Agent initialized successfully via agents.py function.")

# --- Main Chat Interface ---
if st.session_state.selected_repo:
    st.markdown(f"### Chatting about: `{st.session_state.selected_repo}`")
else:
    st.info("👈 Please select a repository from the sidebar to start chatting.")

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input(
    "Ask something about the repository..."
    if st.session_state.selected_repo
    else "Please select a repository first",
    disabled=not st.session_state.selected_repo,
):
    logging.info(f"User input received: {prompt}")
    # Add user message to chat history using the utility function
    add_message("user", prompt)
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)

    # Prepare query for the agent
    full_query = prompt
    logging.info(f"Query prepared for agent: {full_query}")

    # Get assistant response
    if st.session_state.agent:
        with st.spinner("Thinking..."):
            try:
                logging.info("Running agent...")
                # Use the stored agent instance
                # The agent.run() call implicitly uses the agent's memory
                # (managed by the Agno framework) to consider previous turns.
                result = st.session_state.agent.run(full_query)
                assistant_response = (
                    str(result.content) if hasattr(result, "content") else str(result)
                )
                logging.info(f"Agent raw response: {assistant_response}")

                # Display assistant response in chat message container
                with st.chat_message("assistant"):
                    st.markdown(assistant_response)
                # Add assistant response to chat history using the utility function
                add_message("assistant", assistant_response)

            except Exception as e:
                logging.error(f"Error during agent execution: {e}", exc_info=True)
                st.error(f"An error occurred: {e}")
                # Optionally add error message to chat
                error_message = f"Sorry, I encountered an error: {e}"
                with st.chat_message("assistant"):
                    st.markdown(error_message)
                # Add error message to chat history
                add_message("assistant", error_message)
    else:
        # Update error message if agent failed init due to missing token earlier
        if not st.session_state.github_token:
            st.error(
                "Agent cannot run because the GitHub token (GITHUB_ACCESS_TOKEN env var) is missing."
            )
        else:
            st.error("Agent is not initialized. Please check configuration and logs.")
        logging.warning("Agent run skipped: Agent not initialized.")
