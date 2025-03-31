"""
Utility functions for the GitHub Repository Analyzer.
"""

import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import streamlit as st
from github import Github, GithubException

# Import prompts - change from relative to direct import
# from .prompts import ABOUT_TEXT
from prompts import ABOUT_TEXT

# Keep only necessary CSS styles
CUSTOM_CSS = """
<style>
    .main-header {
        font-size: 2.5rem;
        margin-bottom: 1rem;
        color: #0366d6;
        font-weight: 600;
    }
    .sub-header {
        font-size: 1.5rem;
        margin-top: 1rem;
        margin-bottom: 0.5rem;
        color: #2f363d;
        font-weight: 500;
    }
    .metric-card {
        background-color: #f6f8fa;
        border-radius: 8px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        border-left: 5px solid #0366d6;
    }
    .pr-card {
        background-color: #f1f8ff;
        border-radius: 8px;
        padding: 1.2rem;
        margin-bottom: 1.2rem;
        border-left: 5px solid #6f42c1;
    }
</style>
"""

# Predefined list of popular repositories
POPULAR_REPOS = [
    "agno-agi/agno",  # Ensure agno is included
    "facebook/react",
    "tensorflow/tensorflow",
    "microsoft/vscode",
    "torvalds/linux",
    "openai/openai-python",  # Added one more popular repo
]

# Add logging configuration
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def add_message(
    role: str, content: str, tool_calls: Optional[List[Dict]] = None
) -> None:
    """Add a message to the chat history."""
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    message = {"role": role, "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls

    st.session_state["messages"].append(message)


def about_widget() -> None:
    """Display the about section with application information."""
    st.sidebar.markdown("### About GitHub Repo Chat")
    st.sidebar.markdown(ABOUT_TEXT)


def get_combined_repositories(
    token: Optional[str], user_repo_limit: int = 5
) -> list[str]:
    """
    Fetches user repositories (if token provided) and combines them with
    a predefined list of popular repositories.

    Args:
        token: Optional GitHub Personal Access Token.
        user_repo_limit: Max number of user-specific repos to fetch.

    Returns:
        A combined list of unique repository names.
    """
    user_repos = []
    if token:
        try:
            g = Github(token)
            user = g.get_user()
            logging.info(f"Authenticated as GitHub user: {user.login}")
            repos = user.get_repos(
                affiliation="owner,collaborator,organization_member",
                sort="updated",
                direction="desc",
            )

            count = 0
            for repo in repos:
                if count >= user_repo_limit:
                    break
                user_repos.append(repo.full_name)
                count += 1
            logging.info(f"Fetched {len(user_repos)} user repositories: {user_repos}")
        except GithubException as e:
            logging.error(
                f"GitHub API error while fetching user repositories: {e.status} - {e.data}"
            )
            # Don't show error in UI here, let the main app handle UI feedback if needed
        except Exception as e:
            logging.error(
                f"An unexpected error occurred while fetching user repositories: {e}"
            )
            # Don't show error in UI here
    else:
        logging.warning(
            "GitHub token not provided via environment variable. Only showing popular repositories."
        )

    # Combine user repos with popular repos, ensuring uniqueness and order
    combined_list = []
    seen = set()

    # Add user repos first
    for repo in user_repos:
        if repo not in seen:
            combined_list.append(repo)
            seen.add(repo)

    # Add popular repos
    for repo in POPULAR_REPOS:
        if repo not in seen:
            combined_list.append(repo)
            seen.add(repo)

    logging.info(
        f"Final combined repository list ({len(combined_list)}): {combined_list}"
    )
    return combined_list
