"""
TrafilaturaTools Cookbook

This cookbook demonstrates various ways to use TrafilaturaTools for web scraping and text extraction.
TrafilaturaTools provides powerful capabilities for extracting clean, readable text from web pages
and converting raw HTML into structured, meaningful data.

Prerequisites:
- Install trafilatura: pip install trafilatura
- No API keys required
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.trafilatura import TrafilaturaTools

# =============================================================================
# Example 1: Basic Text Extraction
# =============================================================================


def basic_text_extraction():
    """
    Basic text extraction from a single URL.
    Perfect for simple content extraction tasks.
    """
    print("=== Example 1: Basic Text Extraction ===")

    agent = Agent(
        tools=[TrafilaturaTools()],  # Default configuration
        markdown=True,
    )

    agent.print_response(
        "Please extract and summarize the main content from https://github.com/agno-agi/agno"
    )


# =============================================================================
# Example 2: JSON Output with Metadata
# =============================================================================


def json_with_metadata():
    """
    Extract content in JSON format with metadata.
    Useful when you need structured data including titles, authors, dates, etc.
    """
    print("\n=== Example 2: JSON Output with Metadata ===")

    # Configure tool for JSON output with metadata
    agent = Agent(
        tools=[
            TrafilaturaTools(
                output_format="json",
                with_metadata=True,
                include_comments=True,
                include_tables=True,
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Extract the article content from https://en.wikipedia.org/wiki/Web_scraping in JSON format with metadata"
    )


# =============================================================================
# Example 3: Markdown Output with Formatting
# =============================================================================


def markdown_with_formatting():
    """
    Extract content in Markdown format preserving structure.
    Great for maintaining document structure and readability.
    """
    print("\n=== Example 3: Markdown with Formatting ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                output_format="markdown",
                include_formatting=True,
                include_links=True,
                with_metadata=True,
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Convert https://docs.python.org/3/tutorial/introduction.html to markdown format while preserving the structure and links"
    )


# =============================================================================
# Example 4: Metadata-Only Extraction
# =============================================================================


def metadata_only_extraction():
    """
    Extract only metadata without main content.
    Perfect for getting quick information about pages.
    """
    print("\n=== Example 4: Metadata-Only Extraction ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                include_tools=["extract_metadata_only"],
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Get the metadata (title, author, date, etc.) from https://techcrunch.com/2024/01/15/ai-news-update/"
    )


# =============================================================================
# Example 5: High Precision Extraction
# =============================================================================


def high_precision_extraction():
    """
    Extract with high precision settings.
    Use when you need clean, accurate content and don't mind missing some text.
    """
    print("\n=== Example 5: High Precision Extraction ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                favor_precision=True,
                include_comments=False,  # Skip comments for cleaner output
                include_tables=True,
                output_format="txt",
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Extract the main article content from https://www.bbc.com/news with high precision, excluding comments and ads"
    )


# =============================================================================
# Example 6: High Recall Extraction
# =============================================================================


def high_recall_extraction():
    """
    Extract with high recall settings.
    Use when you want to capture as much content as possible.
    """
    print("\n=== Example 6: High Recall Extraction ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                favor_recall=True,
                include_comments=True,
                include_tables=True,
                include_formatting=True,
                output_format="markdown",
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Extract comprehensive content from https://stackoverflow.com/questions/1732348/regex-match-open-tags-except-xhtml-self-contained-tags including all comments and discussions"
    )


# =============================================================================
# Example 7: Language-Specific Extraction
# =============================================================================


def language_specific_extraction():
    """
    Extract content with language filtering.
    Useful for multilingual websites or language-specific content.
    """
    print("\n=== Example 7: Language-Specific Extraction ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                target_language="en",  # Filter for English content
                output_format="json",
                with_metadata=True,
                deduplicate=True,
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Extract English content from https://www.reddit.com/r/MachineLearning/ and provide a summary"
    )


# =============================================================================
# Example 8: Website Crawling (if spider available)
# =============================================================================


def website_crawling():
    """
    Crawl a website to discover and extract content from multiple pages.
    Note: Requires trafilatura spider module to be available.
    """
    print("\n=== Example 8: Website Crawling ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                enable_crawl_website=True,
                max_crawl_urls=5,  # Limit for demo
                output_format="json",
                with_metadata=True,
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Crawl https://example.com and extract content from up to 5 internal pages"
    )


# =============================================================================
# Example 9: HTML to Text Conversion
# =============================================================================


def html_to_text_conversion():
    """
    Convert raw HTML content to clean text.
    Useful when you already have HTML content that needs cleaning.
    """
    print("\n=== Example 9: HTML to Text Conversion ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                enable_html_to_text=True,
            )
        ],
        markdown=True,
    )

    # Example with HTML content
    html_content = """
    <html>
    <body>
        <h1>Sample Article</h1>
        <p>This is a paragraph with <strong>bold</strong> and <em>italic</em> text.</p>
        <ul>
            <li>List item 1</li>
            <li>List item 2</li>
        </ul>
        <div class="advertisement">This is an ad</div>
    </body>
    </html>
    """

    agent.print_response(f"Convert this HTML to clean text: {html_content}")


# =============================================================================
# Example 10: Workflow Integration Example
# =============================================================================


def research_assistant_agent():
    """
    Create a specialized research assistant using TrafilaturaTools.
    This agent is optimized for extracting and analyzing research content.
    """
    research_agent = Agent(
        name="Research Assistant",
        model=OpenAIChat(id="gpt-4"),
        tools=[
            TrafilaturaTools(
                output_format="json",
                with_metadata=True,
                include_tables=True,
                include_links=True,
                favor_recall=True,
                target_language="en",
            )
        ],
        instructions="""
        You are a research assistant specialized in gathering and analyzing information from web sources.
        
        When extracting content:
        1. Always include source metadata (title, author, date, URL)
        2. Preserve important structural elements like tables and lists
        3. Maintain links for citation purposes
        4. Focus on comprehensive content extraction
        5. Provide structured analysis of the extracted content
        
        Format your responses with:
        - Executive Summary
        - Key Findings
        - Important Data/Statistics
        - Source Information
        - Recommendations for further research
        """,
        markdown=True,
    )

    research_agent.print_response("""
        Research the current state of AI in healthcare by analyzing:
        https://www.nature.com/articles/s41591-021-01614-0
        
        Provide a comprehensive analysis including key findings, 
        methodologies mentioned, and implications for future research.
    """)


# =============================================================================
# Example 11: Multiple URLs with Different Configurations
# =============================================================================


def multiple_urls_different_configs():
    """
    Process multiple URLs with different extraction strategies.
    Demonstrates flexibility in handling various content types.
    """
    print("\n=== Example 10: Multiple URLs with Different Configurations ===")

    # Different agents for different content types
    news_agent = Agent(
        tools=[
            TrafilaturaTools(
                output_format="json",
                with_metadata=True,
                include_comments=False,
                favor_precision=True,
            )
        ],
        markdown=True,
    )

    documentation_agent = Agent(
        tools=[
            TrafilaturaTools(
                output_format="markdown",
                include_formatting=True,
                include_links=True,
                include_tables=True,
                favor_recall=True,
            )
        ],
        markdown=True,
    )

    print("Processing news article...")
    news_agent.print_response(
        "Extract and summarize this news article: https://techcrunch.com"
    )

    print("\nProcessing documentation...")
    documentation_agent.print_response(
        "Extract the documentation content from https://docs.python.org/3/tutorial/ preserving structure"
    )


# =============================================================================
# Example 12: Advanced Customization
# =============================================================================


def advanced_customization():
    """
    Advanced configuration with all customization options.
    Shows how to fine-tune extraction for specific needs.
    """
    print("\n=== Example 11: Advanced Customization ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                output_format="xml",
                include_comments=False,
                include_tables=True,
                include_images=True,
                include_formatting=True,
                include_links=True,
                with_metadata=True,
                favor_precision=True,
                target_language="en",
                deduplicate=True,
                max_tree_size=10000,
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Extract comprehensive structured content from https://en.wikipedia.org/wiki/Artificial_intelligence in XML format with all metadata and structural elements"
    )


# =============================================================================
# Example 13: Comparative Analysis
# =============================================================================


def comparative_analysis():
    """
    Compare content from multiple sources using different extraction strategies.
    Useful for research and content analysis tasks.
    """
    print("\n=== Example 12: Comparative Analysis ===")

    agent = Agent(
        model=OpenAIChat(id="gpt-4"),
        tools=[
            TrafilaturaTools(
                output_format="json",
                with_metadata=True,
                include_tables=True,
                favor_precision=True,
            )
        ],
        markdown=True,
    )

    agent.print_response("""
        Compare and analyze the content about artificial intelligence from these sources:
        1. https://en.wikipedia.org/wiki/Artificial_intelligence
        2. https://www.ibm.com/cloud/learn/what-is-artificial-intelligence
        
        Provide a comparative analysis highlighting the key differences in how they present AI concepts.
    """)


# =============================================================================
# Example 14: Content Research Pipeline
# =============================================================================


def content_research_pipeline():
    """
    Create a content research pipeline using TrafilaturaTools.
    Demonstrates how to use the tool for systematic content research.
    """
    print("\n=== Example 13: Content Research Pipeline ===")

    agent = Agent(
        model=OpenAIChat(id="gpt-4"),
        tools=[
            TrafilaturaTools(
                output_format="markdown",
                with_metadata=True,
                include_links=True,
                include_tables=True,
                favor_recall=True,
            )
        ],
        instructions="""
        You are a research assistant that helps gather and analyze information from web sources.
        Use TrafilaturaTools to extract content and provide comprehensive analysis.
        Always include source metadata in your analysis.
        """,
        markdown=True,
    )

    agent.print_response("""
        Research the topic of "web scraping best practices" by:
        1. Extracting content from https://blog.apify.com/web-scraping-best-practices/
        2. Analyzing the main points and recommendations
        3. Providing a summary with key takeaways
        
        Include metadata about the source and structure your response with clear sections.
    """)


# =============================================================================
# Example 15: Performance Optimized Extraction
# =============================================================================


def performance_optimized():
    """
    Optimized configuration for fast, efficient extraction.
    Best for high-volume processing or when speed is critical.
    """
    print("\n=== Example 14: Performance Optimized Extraction ===")

    agent = Agent(
        tools=[
            TrafilaturaTools(
                output_format="txt",
                include_comments=False,
                include_tables=False,
                include_images=False,
                include_formatting=False,
                include_links=False,
                with_metadata=False,
                favor_precision=True,  # Faster processing
                deduplicate=False,  # Skip deduplication for speed
            )
        ],
        markdown=True,
    )

    agent.print_response(
        "Quickly extract just the main text content from https://news.ycombinator.com optimized for speed"
    )


# =============================================================================
# Main Execution
# =============================================================================

if __name__ == "__main__":
    """
    Run specific examples or all examples.
    Uncomment the examples you want to test.
    """
    print("TrafilaturaTools Cookbook - Web Scraping and Text Extraction Examples")
    print("=" * 80)

    # Basic examples
    basic_text_extraction()

    # Format-specific examples
    # json_with_metadata()
    # markdown_with_formatting()

    # Extraction strategy examples
    # high_precision_extraction()
    # high_recall_extraction()

    # Advanced examples
    # language_specific_extraction()
    # website_crawling()
    # html_to_text_conversion()
    # research_assistant_agent()

    # Complex workflows
    # multiple_urls_different_configs()
    # advanced_customization()
    # comparative_analysis()
    # content_research_pipeline()
    # performance_optimized()

    print("\n" + "=" * 80)
    print("Cookbook execution completed!")
    print("\n")
