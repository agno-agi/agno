# Using anybrowse MCP with Agno

## Overview

Agents performing web research often fail on Cloudflare-protected or JavaScript-heavy websites when using standard HTTP tools.

anybrowse provides a hosted MCP server that uses a real browser to bypass these limitations and return clean Markdown.

---

## Installation

```bash
pip install anybrowse
```

---

## MCP Configuration

```json
{
  "mcpServers": {
    "anybrowse": {
      "type": "streamable-http",
      "url": "https://anybrowse.dev/mcp"
    }
  }
}
```

---

## Basic Python Usage

```python
from anybrowse import AnybrowseClient

client = AnybrowseClient()

result = client.scrape("https://example.com")
print(result["markdown"])
```

---

## Agent Example (Scrape → Reason)

```python
from agno.agent import Agent
from anybrowse import AnybrowseClient

client = AnybrowseClient()

def anybrowse_scrape(url: str) -> str:
    result = client.scrape(url)
    return result["markdown"]

agent = Agent(
    tools=[anybrowse_scrape]
)

response = agent.run(
    "Scrape https://example.com and summarize the key information"
)

print(response)
```

---

## When to Use

* Cloudflare-protected sites
* JavaScript-heavy pages
* When normal scraping fails
