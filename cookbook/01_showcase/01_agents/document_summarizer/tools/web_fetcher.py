"""
Web Fetcher Tool
================

Fetches and extracts content from web pages.
"""

from urllib.parse import urlparse

from agno.utils.log import logger

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    raise ImportError(
        "`requests` and `beautifulsoup4` not installed. "
        "Please install using `pip install requests beautifulsoup4`"
    )


# ============================================================================
# Web Fetcher Tool
# ============================================================================
def fetch_url(url: str, timeout: int = 30) -> str:
    """Fetch and extract main content from a web page.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Extracted text content from the web page.
    """
    # Validate URL
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return f"Error: Invalid URL: {url}"
    except Exception:
        return f"Error: Could not parse URL: {url}"

    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; DocumentSummarizer/1.0)"}
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        logger.info(f"Fetched URL: {url} ({len(response.content)} bytes)")

        # Parse HTML
        soup = BeautifulSoup(response.text, "html.parser")

        # Remove unwanted elements
        for element in soup.find_all(
            ["script", "style", "nav", "header", "footer", "aside", "noscript"]
        ):
            element.decompose()

        # Try to find main content
        main_content = None

        # Look for common main content containers
        for selector in ["main", "article", '[role="main"]', ".content", "#content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break

        # Fall back to body if no main content found
        if not main_content:
            main_content = soup.body or soup

        # Extract text
        text = main_content.get_text(separator="\n", strip=True)

        # Clean up excessive whitespace
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        content = "\n".join(lines)

        if not content:
            return "Warning: No text content found on page."

        # Add metadata
        title = soup.title.string if soup.title else "Unknown"
        word_count = len(content.split())
        metadata = f"URL: {url}\nTitle: {title}\nWords: {word_count}"

        return f"{metadata}\n\n{content}"

    except requests.exceptions.Timeout:
        return f"Error: Request timed out after {timeout} seconds"
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching URL {url}: {e}")
        return f"Error fetching URL: {e}"
    except Exception as e:
        logger.error(f"Error processing URL {url}: {e}")
        return f"Error processing page: {e}"
