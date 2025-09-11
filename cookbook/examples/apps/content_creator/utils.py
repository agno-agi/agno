import streamlit as st


def clear_generated_content():
    """Clear the currently generated content"""
    st.session_state.generated_content = None


def about_widget() -> None:
    """Display an about section in the sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ About")
    st.sidebar.markdown("""
    **Content Creator Workflow** helps you analyze blog posts and create social media content for LinkedIn and Twitter automatically.

    Features:
    - Scraping Blog and analysis with AI
    - Twitter thread generation
    - LinkedIn post creation
    - Automatic scheduling

    Built with:
    - 🚀 Agno
    - 💫 Streamlit
    """)


def create_iso_date(date, time):
    """
    Create ISO format date string from date and time objects with validation.

    Args:
        date: datetime.date object
        time: datetime.time object

    Returns:
        str: ISO 8601 formatted date string with UTC timezone (e.g., "2025-03-20T15:30:00Z")
    """
    import datetime

    # Validate inputs
    if not isinstance(date, datetime.date):
        raise TypeError("date must be a datetime.date object")
    if not isinstance(time, datetime.time):
        raise TypeError("time must be a datetime.time object")

    # Check if date is in the past
    if date < datetime.date.today():
        raise ValueError("Scheduled date cannot be in the past")

    # If date is today, check if time is in the past
    if date == datetime.date.today() and time < datetime.datetime.now().time():
        raise ValueError("Scheduled time cannot be in the past")

    # Combine date and time
    dt = datetime.datetime.combine(date, time)

    # Convert to ISO format with Z suffix for UTC
    return dt.isoformat() + "Z"
