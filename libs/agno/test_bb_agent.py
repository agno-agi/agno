from agno.agent import Agent
from agno.tools.browserbase import BrowserbaseTools
from os import getenv


def create_web_automation_agent():
    """Create an agent specialized in web automation tasks"""
    agent = Agent(
        name="Web Automation Assistant",
        tools=[
            BrowserbaseTools(
                api_key=getenv("BROWSERBASE_API_KEY"),
                project_id=getenv("BROWSERBASE_PROJECT_ID")
            )
        ],
        instructions=[
            "You are a web automation assistant that can help with:",
            "1. Capturing screenshots of websites",
            "2. Extracting content from web pages",
            "3. Monitoring website changes",
            "4. Taking visual snapshots of responsive layouts",
            "5. Automated web testing and verification",
        ],
        show_tool_calls=True,
        markdown=True
    )
    return agent


def main():
    # Example use cases
    agent = create_web_automation_agent()

    # Use Case 1: Website Screenshot Archive
    agent.print_response("""
        Visit these news websites and take screenshots of their homepages:
        - https://news.ycombinator.com
        - https://techcrunch.com
        - https://theverge.com
        Save them with descriptive filenames.
        Also read through each of the website's content and summarize it.
    """)

    # Use Case 2: Content Extraction
    agent.print_response("""
        Go to https://news.ycombinator.com and extract:
        1. The page title
        2. The full HTML content
        3. Take a screenshot of the top stories section
    """)

    # Use Case 3: Responsive Testing
    agent.print_response("""
        Visit https://example.com and:
        1. Take a full page screenshot
        2. Extract the page content
        3. Verify if the page loaded successfully
    """)


if __name__ == "__main__":
    # Check for required environment variables
    if not all([getenv("BROWSERBASE_API_KEY"), getenv("BROWSERBASE_PROJECT_ID")]):
        print("Please set BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID environment variables")
        exit(1)

    main()
