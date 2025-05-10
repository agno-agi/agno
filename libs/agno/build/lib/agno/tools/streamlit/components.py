from os import environ, getenv
from typing import Optional

try:
    import streamlit as st
except ImportError:
    raise ImportError("`streamlit` library not installed. Please install using `pip install streamlit`")


def get_username_sidebar() -> Optional[str]:
    """Sidebar component to get username"""

    # Get username from user if not in session state
    if "username" not in st.session_state:
        username_input_container = st.sidebar.empty()
        username = username_input_container.text_input(":technologist: Enter username")
        if username != "":
            st.session_state["username"] = username
            username_input_container.empty()

    # Get username from session state
    username = st.session_state.get("username")  # type: ignore
    return username


def reload_button_sidebar(text: str = "Reload Session", **kwargs) -> None:
    """Sidebar component to show reload button"""

    if st.sidebar.button(text, **kwargs):
        st.session_state.clear()
        st.rerun()


def check_password(password_env_var: str = "APP_PASSWORD") -> bool:
    """Component to check if a password entered by the user is correct.
    To use this component, set the environment variable `APP_PASSWORD`.

    Args:
        password_env_var (str, optional): The environment variable to use for the password. Defaults to "APP_PASSWORD".

    Returns:
        bool: `True` if the user had the correct password.
    """

    app_password = getenv(password_env_var)
    if app_password is None:
        return True

    def check_first_run_password():
        """Checks whether a password entered on the first run is correct."""

        if "first_run_password" in st.session_state:
            password_to_check = st.session_state["first_run_password"]
            if password_to_check == app_password:
                st.session_state["password_correct"] = True
                # don't store password
                del st.session_state["first_run_password"]
            else:
                st.session_state["password_correct"] = False

    def check_updated_password():
        """Checks whether an updated password is correct."""

        if "updated_password" in st.session_state:
            password_to_check = st.session_state["updated_password"]
            if password_to_check == app_password:
                st.session_state["password_correct"] = True
                # don't store password
                del st.session_state["updated_password"]
            else:
                st.session_state["password_correct"] = False

    # First run, show input for password.
    if "password_correct" not in st.session_state:
        st.text_input(
            "Password",
            type="password",
            on_change=check_first_run_password,
            key="first_run_password",
        )
        return False
    # Password incorrect, show input for updated password + error.
    elif not st.session_state["password_correct"]:
        st.text_input(
            "Password",
            type="password",
            on_change=check_updated_password,
            key="updated_password",
        )
        st.error("😕 Password incorrect")
        return False
    # Password correct.
    else:
        return True


def get_openai_key_sidebar() -> Optional[str]:
    """Sidebar component to get OpenAI API key"""

    # Get OpenAI API key from environment variable
    openai_key: Optional[str] = getenv("OPENAI_API_KEY")
    # If not found, get it from user input
    if openai_key is None or openai_key == "" or openai_key == "sk-***":
        api_key = st.sidebar.text_input("OpenAI API key", placeholder="sk-***", key="api_key")
        if api_key != "sk-***" or api_key != "" or api_key is not None:
            openai_key = api_key

    # Store it in session state and environment variable
    if openai_key is not None and openai_key != "":
        st.session_state["OPENAI_API_KEY"] = openai_key
        environ["OPENAI_API_KEY"] = openai_key

    return openai_key
