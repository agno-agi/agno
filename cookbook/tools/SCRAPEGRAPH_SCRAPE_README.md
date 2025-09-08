# ScrapeGraphTools - Scrape Method

This document describes the new `scrape` method added to ScrapeGraphTools, which provides raw HTML content extraction capabilities.

## Overview

The `scrape` method allows you to retrieve the complete raw HTML content from any website using the ScrapeGraphAI API. This is particularly useful when you need:

- Complete HTML source code
- Raw content for further processing
- HTML structure analysis
- Content that needs to be parsed differently than what smartscraper provides

## Features

- **Raw HTML Extraction**: Get the complete HTML source code
- **JavaScript Rendering**: Support for heavy JavaScript rendering
- **Custom Headers**: Ability to send custom HTTP headers
- **Error Handling**: Comprehensive error handling and status reporting
- **Metadata**: Returns request ID, status, and error information

## Usage

### Basic Usage

```python
from agno.tools.scrapegraph import ScrapeGraphTools

# Initialize with scrape method enabled
scrape_tools = ScrapeGraphTools(scrape=True, smartscraper=False)

# Get HTML content
result = scrape_tools.scrape(website_url="https://example.com")
```

### With JavaScript Rendering

```python
# Enable heavy JavaScript rendering
result = scrape_tools.scrape(
    website_url="https://example.com",
    render_heavy_js=True
)
```

### With Custom Headers

```python
# Send custom headers
headers = {
    "User-Agent": "Custom Bot 1.0",
    "Accept": "text/html,application/xhtml+xml"
}

result = scrape_tools.scrape(
    website_url="https://example.com",
    headers=headers
)
```

### Using with Agno Agent

```python
from agno.agent import Agent
from agno.tools.scrapegraph import ScrapeGraphTools

# Create agent with scrape tools
agent = Agent(
    tools=[ScrapeGraphTools(scrape=True, smartscraper=False)],
    show_tool_calls=True,
    markdown=True
)

# Use the agent to scrape content
response = agent.run("Use the scrape tool to get HTML content from https://example.com")
```

## Response Format

The scrape method returns a JSON string with the following structure:

```json
{
  "html": "<!DOCTYPE html><html>...</html>",
  "scrape_request_id": "req_123456789",
  "status": "success",
  "error": null,
  "url": "https://example.com",
  "render_heavy_js": false,
  "headers": null
}
```

### Response Fields

- `html`: The raw HTML content of the webpage
- `scrape_request_id`: Unique identifier for the scraping request
- `status`: Status of the operation ("success" or "error")
- `error`: Error message if the operation failed
- `url`: The URL that was scraped
- `render_heavy_js`: Whether JavaScript rendering was enabled
- `headers`: Custom headers that were sent (if any)

## Error Handling

The method includes comprehensive error handling:

- **URL Validation**: Ensures URLs are properly formatted
- **API Errors**: Catches and reports API-related errors
- **Network Issues**: Handles network connectivity problems
- **Response Parsing**: Safely parses API responses

## Examples

### Complete Example Script

See `scrapegraph_scrape_example.py` for a comprehensive example that demonstrates:

1. Direct usage of ScrapeGraphTools
2. Integration with Agno agents
3. HTML content analysis
4. File saving functionality
5. Error handling

### Test Script

Run `test_scrape_method.py` to verify the scrape method is working correctly.

## Requirements

- Python 3.7+
- agno
- scrapegraph-py
- python-dotenv
- SGAI_API_KEY environment variable

## Configuration

Set up your environment variables in a `.env` file:

```env
SGAI_API_KEY=your_scrapegraph_api_key_here
```

## Comparison with Other Methods

| Method | Purpose | Output | Best For |
|--------|---------|--------|----------|
| `smartscraper` | Extract structured data | JSON/structured data | Data extraction with AI |
| `markdownify` | Convert to markdown | Markdown text | Clean text content |
| `scrape` | Raw HTML extraction | Raw HTML | Complete source code |
| `crawl` | Multi-page crawling | Structured data | Site-wide extraction |
| `searchscraper` | Web search | Search results | Finding information |

## Troubleshooting

### Common Issues

1. **API Key Not Set**: Ensure `SGAI_API_KEY` is properly configured
2. **Invalid URL**: URLs must start with `http://` or `https://`
3. **Network Issues**: Check internet connectivity
4. **Rate Limiting**: ScrapeGraphAI may have rate limits

### Debug Mode

Enable debug logging by setting the logging level:

```python
from scrapegraph_py.logger import sgai_logger
sgai_logger.set_logging(level="DEBUG")
```

## Support

For issues related to:
- ScrapeGraphAI API: Check the [official documentation](https://docs.scrapegraphai.com/)
- Agno integration: Check the Agno documentation
- This implementation: Create an issue in the Agno repository
