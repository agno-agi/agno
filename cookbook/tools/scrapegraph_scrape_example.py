"""
Example demonstrating how to use the new Scrape endpoint with the ScrapeGraphTools.

This example shows how to:
1. Set up the ScrapeGraphTools with the scrape method enabled
2. Make API calls to get raw HTML content from websites
3. Handle the response and save the HTML content
4. Demonstrate both regular and heavy JS rendering modes
5. Display the results and metadata

Requirements:
- Python 3.7+
- agno
- scrapegraph-py
- python-dotenv
- A .env file with your SGAI_API_KEY

Example .env file:
SGAI_API_KEY=your_api_key_here
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from agno.agent import Agent
from agno.tools.scrapegraph import ScrapeGraphTools

# Load environment variables from .env file
load_dotenv()


def scrape_website_with_agent(
    agent: Agent,
    website_url: str,
    render_heavy_js: bool = False,
    headers: Optional[dict] = None,
) -> dict:
    """
    Get HTML content from a website using the ScrapeGraphTools scrape method.

    Args:
        agent: The Agno agent with ScrapeGraphTools
        website_url: The URL of the website to get HTML from
        render_heavy_js: Whether to render heavy JavaScript (defaults to False)
        headers: Optional headers to send with the request

    Returns:
        dict: A dictionary containing the HTML content and metadata

    Raises:
        Exception: If the API request fails
    """
    js_mode = "with heavy JS rendering" if render_heavy_js else "without JS rendering"
    print(f"Getting HTML content from: {website_url}")
    print(f"Mode: {js_mode}")

    start_time = time.time()
    
    try:
        # Prepare the tool call parameters
        params = {
            "website_url": website_url,
            "render_heavy_js": render_heavy_js,
        }
        if headers:
            params["headers"] = headers

        # Use the agent to call the scrape tool
        response = agent.run(f"Use the scrape tool to get HTML content from {website_url}", **params)
        
        execution_time = time.time() - start_time
        print(f"Execution time: {execution_time:.2f} seconds")
        
        # Parse the response
        if hasattr(response, 'content') and response.content:
            try:
                return json.loads(response.content)
            except json.JSONDecodeError:
                return {"error": "Failed to parse response", "content": response.content}
        else:
            return {"error": "No content in response"}
            
    except Exception as e:
        print(f"Error: {str(e)}")
        raise


def scrape_website_direct(
    scrape_tools: ScrapeGraphTools,
    website_url: str,
    render_heavy_js: bool = False,
    headers: Optional[dict] = None,
) -> dict:
    """
    Get HTML content from a website using ScrapeGraphTools directly.

    Args:
        scrape_tools: The ScrapeGraphTools instance
        website_url: The URL of the website to get HTML from
        render_heavy_js: Whether to render heavy JavaScript (defaults to False)
        headers: Optional headers to send with the request

    Returns:
        dict: A dictionary containing the HTML content and metadata

    Raises:
        Exception: If the API request fails
    """
    js_mode = "with heavy JS rendering" if render_heavy_js else "without JS rendering"
    print(f"Getting HTML content from: {website_url}")
    print(f"Mode: {js_mode}")

    start_time = time.time()
    
    try:
        result = scrape_tools.scrape(
            website_url=website_url,
            render_heavy_js=render_heavy_js,
            headers=headers,
        )
        execution_time = time.time() - start_time
        print(f"Execution time: {execution_time:.2f} seconds")
        return json.loads(result)
    except Exception as e:
        print(f"Error: {str(e)}")
        raise


def save_html_content(
    html_content: str, filename: str, output_dir: str = "scrape_output"
):
    """
    Save HTML content to a file.

    Args:
        html_content: The HTML content to save
        filename: The name of the file (without extension)
        output_dir: The directory to save the file in
    """
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # Save HTML file
    html_file = output_path / f"{filename}.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"HTML content saved to: {html_file}")
    return html_file


def analyze_html_content(html_content: str) -> dict:
    """
    Analyze HTML content and provide basic statistics.

    Args:
        html_content: The HTML content to analyze

    Returns:
        dict: Basic statistics about the HTML content
    """
    stats = {
        "total_length": len(html_content),
        "lines": len(html_content.splitlines()),
        "has_doctype": html_content.strip().startswith("<!DOCTYPE"),
        "has_html_tag": "<html" in html_content.lower(),
        "has_head_tag": "<head" in html_content.lower(),
        "has_body_tag": "<body" in html_content.lower(),
        "script_tags": html_content.lower().count("<script"),
        "style_tags": html_content.lower().count("<style"),
        "div_tags": html_content.lower().count("<div"),
        "p_tags": html_content.lower().count("<p"),
        "img_tags": html_content.lower().count("<img"),
        "link_tags": html_content.lower().count("<link"),
    }

    return stats


def main():
    """
    Main function demonstrating ScrapeGraphTools scrape method usage.
    """
    # Example websites to test
    test_websites = [
        {
            "url": "https://example.com",
            "name": "example",
            "render_heavy_js": False,
            "description": "Simple static website",
        },
        {
            "url": "https://httpbin.org/html",
            "name": "httpbin_html",
            "render_heavy_js": False,
            "description": "HTTP testing service",
        },
    ]

    print("ScrapeGraphTools Scrape Method Example")
    print("=" * 60)

    # Initialize the ScrapeGraphTools with scrape method enabled
    try:
        scrape_tools = ScrapeGraphTools(scrape=True, smartscraper=False)
        print("✅ ScrapeGraphTools initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize ScrapeGraphTools: {str(e)}")
        print("Make sure you have SGAI_API_KEY in your .env file")
        return

    # Method 1: Direct usage of ScrapeGraphTools
    print("\n" + "=" * 60)
    print("METHOD 1: Direct ScrapeGraphTools Usage")
    print("=" * 60)

    for website in test_websites:
        print(f"\nTesting: {website['description']}")
        print("-" * 40)

        try:
            # Get HTML content using direct method
            result = scrape_website_direct(
                scrape_tools=scrape_tools,
                website_url=website["url"],
                render_heavy_js=website["render_heavy_js"],
            )

            # Display response metadata
            print(f"Request ID: {result.get('scrape_request_id', 'N/A')}")
            print(f"Status: {result.get('status', 'N/A')}")
            print(f"Error: {result.get('error', 'None')}")

            # Analyze HTML content
            html_content = result.get("html", "")
            if html_content:
                stats = analyze_html_content(html_content)
                print(f"\nHTML Content Analysis:")
                print(f"  Total length: {stats['total_length']:,} characters")
                print(f"  Lines: {stats['lines']:,}")
                print(f"  Has DOCTYPE: {stats['has_doctype']}")
                print(f"  Has HTML tag: {stats['has_html_tag']}")
                print(f"  Has Head tag: {stats['has_head_tag']}")
                print(f"  Has Body tag: {stats['has_body_tag']}")
                print(f"  Script tags: {stats['script_tags']}")
                print(f"  Style tags: {stats['style_tags']}")
                print(f"  Div tags: {stats['div_tags']}")
                print(f"  Paragraph tags: {stats['p_tags']}")
                print(f"  Image tags: {stats['img_tags']}")
                print(f"  Link tags: {stats['link_tags']}")

                # Save HTML content
                filename = f"{website['name']}_{'js' if website['render_heavy_js'] else 'nojs'}"
                save_html_content(html_content, filename)

                # Show first 500 characters as preview
                preview = html_content[:500].replace("\n", " ").strip()
                print(f"\nHTML Preview (first 500 chars):")
                print(f"  {preview}...")
            else:
                print("No HTML content received")

        except Exception as e:
            print(f"Error processing {website['url']}: {str(e)}")

    # Method 2: Using with Agno Agent
    print("\n" + "=" * 60)
    print("METHOD 2: Using with Agno Agent")
    print("=" * 60)

    try:
        # Create an agent with ScrapeGraphTools
        agent = Agent(
            name="Web Scraper Agent",
            tools=[scrape_tools],
            instructions=[
                "You are a web scraping assistant that can retrieve raw HTML content from websites.",
                "Use the scrape tool to get complete HTML content from URLs.",
                "Always provide detailed analysis of the scraped content."
            ],
            show_tool_calls=True,
            markdown=True,
        )

        print("✅ Agent created successfully")

        # Test with one website using the agent
        test_url = "https://example.com"
        print(f"\nTesting agent with: {test_url}")
        print("-" * 40)

        response = agent.run(f"Use the scrape tool to get the complete HTML content from {test_url}")
        
        if hasattr(response, 'content'):
            print("Agent Response:")
            print(response.content)
        else:
            print("Agent Response:")
            print(response)

    except Exception as e:
        print(f"Error with agent method: {str(e)}")

    print("\n" + "=" * 60)
    print("✅ Example completed successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
