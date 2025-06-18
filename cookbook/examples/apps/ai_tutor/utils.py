import streamlit as st
from db import create_user, get_users


def authenticate_user(user_id):
    """Handle user login."""
    if user_id:
        existing_user = get_users(user_id)
        if not existing_user:
            create_user(user_id)  # Save user in DB
        st.session_state["user_id"] = user_id
        st.success(f"Welcome, {user_id}!")
        st.rerun()
    else:
        st.error("Name cannot be empty.")


def apply_custom_css():
    st.markdown(
        """
    <style>
        /* Main container styling */
        .main {
            background-color: #000000;
            border-radius: 15px;
            padding: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        /* Button styling */

        .stButton>button:hover {
            background-color: #FF9A40;
            box-shadow: 0 4px 8px rgba(255, 127, 0, 0.4);
            transform: translateY(-2px);
        }


        /* Chat styling */
        .chat-message {
            padding: 15px;
            border-radius: 15px;
            margin-bottom: 10px;
            display: flex;
            flex-direction: row;
            align-items: flex-start;
            gap: 10px;
            color: #FFFFFF;
        }
        .user-message {
            background-color: #252525;
            margin-left: 40px;
            border-bottom-right-radius: 5px;
        }
        .agent-message {
            background-color: #353535;
            margin-left: 40px;
            border-bottom-left-radius: 5px;
        }

        /* Header styling */
        .app-header {
            text-align: center;
            padding: 20px 0;
        }
        .app-title {
            font-size: 2.8em;
            font-weight: bold;
            color: #FF7F00;
            margin-bottom: 5px;
        }
        .app-subtitle {
            font-size: 1.3em;
            color: #FFFFFF;
            margin-bottom: 30px;
        }

        /* Form styling */
        .form-container {
            max-width: 450px;
            margin: 0 auto;
            padding: 25px;
            background-color: #151515;
            border-radius: 12px;
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
            color: #FFFFFF;
        }
        .form-header {
            text-align: center;
            margin-bottom: 25px;
            color: #FF7F00;
        }

        /* Quiz styling */

        .quiz-question {
            font-size: 1.3em;
            font-weight: 500;
            margin-bottom: 15px;
            color: #FF7F00;
        }
        .quiz-option {
            padding: 10px;
            margin: 5px 0;
            border-radius: 8px;
            transition: all 0.2s;
            color: #FFFFFF;
        }
        .quiz-option:hover {
            background-color: #252525;
        }
        .quiz-result {
            text-align: center;
            padding: 20px;
            background-color: #252525;
            border-radius: 12px;
            font-size: 1.5em;
            font-weight: bold;
            color: #FF7F00;
        }

        /* Sidebar styling */
        .sidebar .sidebar-content {
            background-color: #151515;
            color: #FFFFFF;
        }

        /* Progress bar */
        .stProgress > div > div > div > div {
            background-color: #FF7F00;
        }

        /* Text input */
        .stTextInput>div>div>input {
            color: #FFFFFF;
            background-color: #252525;
        }

        /* Radio buttons */
        .stRadio>div {
            color: #FFFFFF;
        }

        /* All text elements */
        p, h1, h2, h3, h4, h5, h6, .stMarkdown, div {
            color: #FFFFFF;
        }
    </style>
    """,
        unsafe_allow_html=True,
    )


def extract_day_content(learning_path, day):
    """Extract content for a specific day from a learning path.

    This utility function uses regex to extract the content for a specific
    day from the learning path markdown text.

    Args:
        learning_path: The full learning path markdown text
        day: The day number to extract

    Returns:
        The content for the specified day, or None if not found
    """
    import re

    # Pattern to match day heading and all content until the next day heading or end
    print(type(day), day)
    print(f"## Day {day}:.*?(?=## Day \d+:|$)")
    day_pattern = rf"## Day {day}:.*?(?=## Day \d+:|$)"

    match = re.search(day_pattern, learning_path, re.DOTALL)
    if match:
        return match.group(0)

    return None
