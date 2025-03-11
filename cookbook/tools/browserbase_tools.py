from agno.tools.browserbase import BrowserbaseTools
import json
from os import getenv


def main():
    # Initialize the Browserbase tools
    browserbase = BrowserbaseTools(
        api_key=getenv("BROWSERBASE_API_KEY"),
        project_id=getenv("BROWSERBASE_PROJECT_ID")
    )

    # Create a new browser session
    print("Creating browser session...")
    session_response = json.loads(browserbase.create_session())

    session_id = session_response["session_id"]
    connect_url = session_response["connect_url"]
    print(f"Session created with ID: {session_id}")

    try:
        # Navigate to a website
        url = "https://news.ycombinator.com"
        print(f"\nNavigating to {url}...")
        nav_result = json.loads(browserbase.navigate_to(connect_url, url))
        print(f"Page title: {nav_result['title']}")

        # Take a screenshot
        print("\nTaking screenshot...")
        screenshot_result = json.loads(
            browserbase.screenshot(
                connect_url, "hn_screenshot.png", full_page=True)
        )
        print(f"Screenshot saved to: {screenshot_result['path']}")

        # Get page content
        print("\nGetting page content...")
        content = browserbase.get_page_content(connect_url)
        print(f"Page content length: {len(content)} characters")

    except Exception as e:
        print(f"An error occurred: {str(e)}")

    finally:
        # Close the session
        print("\nClosing browser session...")
        close_result = json.loads(browserbase.close_session(session_id))
        print(f"Session closed with status: {close_result['status']}")
        print(f"View replay at https://browserbase.com/sessions/{session_id}")


if __name__ == "__main__":
    # Check for required environment variables
    if not getenv("BROWSERBASE_API_KEY"):
        print("Please set BROWSERBASE_API_KEY environment variable")
        exit(1)
    if not getenv("BROWSERBASE_PROJECT_ID"):
        print("Please set BROWSERBASE_PROJECT_ID environment variable")
        exit(1)

    main()
