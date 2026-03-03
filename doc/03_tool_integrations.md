# Tool Integrations

Agno ships with **130+ pre-built tool integrations** organised into toolkits. Any Python function can also be a tool via the `@tool` decorator.

**Directory:** `libs/agno/agno/tools/`

---

## Custom tools — the `@tool` decorator

The simplest way to create a tool:

```python
from agno.tools import tool
from agno.agent import Agent
from agno.models.openai import OpenAIChat

@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The name of the city.

    Returns:
        A string describing current weather conditions.
    """
    # your implementation
    return f"Sunny, 22°C in {city}"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[get_weather],
)
agent.print_response("What is the weather in Paris?")
```

Key rules for tool functions:
- Must have a docstring (the LLM reads it to decide when to use the tool)
- Must return a `str` (or something JSON-serialisable cast to `str`)
- Parameters must be typed (Agno builds the JSON schema from type hints)

---

## Toolkit class

For grouping multiple related tools:

```python
from agno.tools import Toolkit

class WeatherTools(Toolkit):
    def current_weather(self, city: str) -> str:
        """Get current weather for a city."""
        ...

    def forecast(self, city: str, days: int) -> str:
        """Get weather forecast for a city."""
        ...

agent = Agent(tools=[WeatherTools()])
```

---

## Controlling tool use

```python
agent = Agent(
    tools=[DuckDuckGoTools(), CalculatorTools()],
    tool_choice="auto",          # model decides which tools to use
    # tool_choice="none"         # disable all tools
    # tool_choice="required"     # force at least one tool call
    max_tool_calls=5,            # cap tool invocations per run
    show_tool_calls=True,        # print tool call details
    stream_intermediate_steps=True,  # stream tool results in real-time
)
```

---

## Web & Search

| Toolkit | Import | Description |
|---------|--------|-------------|
| `DuckDuckGoTools` | `agno.tools.duckduckgo` | Free, no API key required |
| `TavilyTools` | `agno.tools.tavily` | AI-optimised search results |
| `ExaTools` | `agno.tools.exa` | Semantic neural search |
| `SerperApiTools` | `agno.tools.serper` | Google search via Serper |
| `SerpApiTools` | `agno.tools.serpapi` | Google search via SerpAPI |
| `BraveSearchTools` | `agno.tools.bravesearch` | Privacy-focused search |
| `SearxngTools` | `agno.tools.searxng` | Self-hosted meta-search |
| `JinaTools` | `agno.tools.jina` | Jina AI reader + search |
| `BaiduSearchTools` | `agno.tools.baidusearch` | Baidu search (Chinese) |
| `WebSearchTools` | `agno.tools.websearch` | Generic web search wrapper |

```python
from agno.tools.tavily import TavilyTools
agent = Agent(tools=[TavilyTools(search_depth="advanced", max_tokens=5000)])
```

---

## Web Scraping & Content Extraction

| Toolkit | Import | Description |
|---------|--------|-------------|
| `WebsiteTools` | `agno.tools.website` | Fetch + parse any URL |
| `FirecrawlTools` | `agno.tools.firecrawl` | Firecrawl API — markdown output |
| `Crawl4aiTools` | `agno.tools.crawl4ai` | Async scraping |
| `BrowserbaseTools` | `agno.tools.browserbase` | Headless browser in the cloud |
| `BrightdataTools` | `agno.tools.brightdata` | Proxy-based scraping |
| `OxylabsTools` | `agno.tools.oxylabs` | Oxylabs scraper API |
| `SpiderTools` | `agno.tools.spider` | Spider.cloud |
| `Newspaper4kTools` | `agno.tools.newspaper4k` | Article extraction |
| `TrafilaturaTools` | `agno.tools.trafilatura` | Main content extraction |
| `ScrapegraphTools` | `agno.tools.scrapegraph` | AI-powered scraping |
| `AgentQLTools` | `agno.tools.agentql` | Browser automation via AgentQL |

---

## Data Sources & Knowledge

| Toolkit | Import | Description |
|---------|--------|-------------|
| `ArxivTools` | `agno.tools.arxiv` | Search and download ArXiv papers |
| `PubMedTools` | `agno.tools.pubmed` | PubMed medical literature |
| `HackerNewsTools` | `agno.tools.hackernews` | HN stories and comments |
| `RedditTools` | `agno.tools.reddit` | Reddit posts and comments |
| `WikipediaTools` | `agno.tools.wikipedia` | Wikipedia search |
| `YoutubeTools` | `agno.tools.youtube` | Video metadata, transcripts |
| `OpenWeatherTools` | `agno.tools.openweather` | Weather forecasts |

```python
from agno.tools.arxiv import ArxivTools
agent = Agent(
    tools=[ArxivTools()],
    instructions="Search ArXiv for relevant papers and summarise findings.",
)
agent.print_response("Latest papers on diffusion models for protein folding")
```

---

## Financial & Business

| Toolkit | Import | Description |
|---------|--------|-------------|
| `YFinanceTools` | `agno.tools.yfinance` | Yahoo Finance — stocks, crypto, news |
| `FinancialDatasetsTools` | `agno.tools.financial_datasets` | FRED, economic data |
| `OpenBBTools` | `agno.tools.openbb` | OpenBB investment platform |
| `ShopifyTools` | `agno.tools.shopify` | Shopify store operations (80+ methods) |

```python
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    tools=[YFinanceTools(
        stock_price=True,
        analyst_recommendations=True,
        company_news=True,
        income_statements=True,
    )],
)
agent.print_response("Analyse Apple's financial health and analyst sentiment")
```

---

## Database & SQL

| Toolkit | Import | Description |
|---------|--------|-------------|
| `SqlTools` | `agno.tools.sql` | Generic SQL execution |
| `PostgresTools` | `agno.tools.postgres` | PostgreSQL read/write |
| `DuckDbTools` | `agno.tools.duckdb` | DuckDB analytics queries |
| `Neo4jTools` | `agno.tools.neo4j` | Neo4j graph queries |
| `GoogleBigQueryTools` | `agno.tools.google.bigquery` | Google BigQuery |
| `RedshiftTools` | `agno.tools.redshift` | AWS Redshift |
| `PandasTools` | `agno.tools.pandas` | DataFrame operations |
| `CsvTools` | `agno.tools.csv_toolkit` | CSV file read/transform |

```python
from agno.tools.duckdb import DuckDbTools

agent = Agent(
    tools=[DuckDbTools()],
    instructions="Write and execute DuckDB SQL to answer data questions.",
)
agent.print_response("What are the top 5 countries by GDP in data.csv?")
```

---

## Cloud Platforms

### Google

| Toolkit | Import |
|---------|--------|
| `GmailTools` | `agno.tools.google.gmail` |
| `GoogleDriveTools` | `agno.tools.google.drive` |
| `GoogleSheetsTools` | `agno.tools.google.sheets` |
| `GoogleCalendarTools` | `agno.tools.google.calendar` |
| `GoogleMapsTools` | `agno.tools.google.maps` |
| `GoogleBigQueryTools` | `agno.tools.google.bigquery` |

### AWS

| Toolkit | Import |
|---------|--------|
| `AwsLambdaTools` | `agno.tools.aws_lambda` |
| `AwsSesTools` | `agno.tools.aws_ses` |

### Azure

| Toolkit | Import |
|---------|--------|
| `AzureBlobTools` | `agno.tools.azure_blob` |

### GitHub / Version Control

| Toolkit | Import |
|---------|--------|
| `GithubTools` | `agno.tools.github` (70KB — repos, PRs, issues, code, actions) |
| `BitbucketTools` | `agno.tools.bitbucket` |

```python
from agno.tools.github import GithubTools

agent = Agent(
    tools=[GithubTools(access_token="ghp_...")],
    instructions="Help manage the GitHub repository.",
)
agent.print_response("List open PRs and their review status for agno-agi/agno")
```

---

## Communication & Productivity

| Toolkit | Import | Description |
|---------|--------|-------------|
| `SlackTools` | `agno.tools.slack` | Send/read Slack messages |
| `DiscordTools` | `agno.tools.discord` | Discord bot operations |
| `TelegramTools` | `agno.tools.telegram` | Telegram messaging |
| `WhatsAppTools` | `agno.tools.whatsapp` | WhatsApp via Twilio |
| `EmailTools` | `agno.tools.email` | SMTP email |
| `ResendTools` | `agno.tools.resend` | Resend transactional email |
| `TwilioTools` | `agno.tools.twilio` | SMS + voice |

---

## Project Management

| Toolkit | Import | Description |
|---------|--------|-------------|
| `JiraTools` | `agno.tools.jira` | Issues, sprints, projects |
| `LinearTools` | `agno.tools.linear` | Linear issues and cycles |
| `ClickUpTools` | `agno.tools.clickup` | ClickUp tasks |
| `TodoistTools` | `agno.tools.todoist` | Personal task management |
| `TrelloTools` | `agno.tools.trello` | Boards, cards, lists |
| `NotionTools` | `agno.tools.notion` | Pages, databases, blocks |
| `ConfluenceTools` | `agno.tools.confluence` | Wiki pages |
| `ZendeskTools` | `agno.tools.zendesk` | Support tickets |
| `CalComTools` | `agno.tools.calcom` | Cal.com scheduling |
| `WebexTools` | `agno.tools.webex` | Webex meetings |
| `ZoomTools` | `agno.tools.zoom` | Zoom meetings |

---

## AI / Media Generation

| Toolkit | Import | Description |
|---------|--------|-------------|
| `DalleTools` | `agno.tools.dalle` | DALL-E image generation |
| `LumaLabTools` | `agno.tools.lumalab` | Luma Dream Machine video |
| `FalTools` | `agno.tools.fal` | FAL.ai media models |
| `ReplicateTools` | `agno.tools.replicate` | Replicate model hosting |
| `ElevenLabsTools` | `agno.tools.eleven_labs` | ElevenLabs text-to-speech |
| `CartesiaTools` | `agno.tools.cartesia` | Cartesia TTS |
| `MlxTranscribeTools` | `agno.tools.mlx_transcribe` | Apple MLX transcription |
| `MoviePyTools` | `agno.tools.moviepy_video` | Video editing |
| `OpenCVTools` | `agno.tools.opencv` | Computer vision |
| `UnsplashTools` | `agno.tools.unsplash` | Stock photo search |
| `GiphyTools` | `agno.tools.giphy` | GIF search |
| `SpotifyTools` | `agno.tools.spotify` | Spotify playback/search |

---

## Code Execution & Development

| Toolkit | Import | Description |
|---------|--------|-------------|
| `CodingTools` | `agno.tools.coding` | Run Python code locally (28KB) |
| `E2BTools` | `agno.tools.e2b` | Cloud code sandbox (E2B) |
| `DaytonaTools` | `agno.tools.daytona` | Daytona dev environment |
| `DockerTools` | `agno.tools.docker` | Docker container management |
| `ShellTools` | `agno.tools.shell` | Local shell commands |
| `AirflowTools` | `agno.tools.airflow` | Apache Airflow DAG operations |
| `ApifyTools` | `agno.tools.apify` | Apify actor execution |

```python
from agno.tools.e2b import E2BTools

agent = Agent(
    tools=[E2BTools()],
    instructions="You are a Python coding assistant. Write and execute code.",
)
agent.print_response("Write and run code that generates the Fibonacci sequence up to 1000")
```

---

## MCP (Model Context Protocol)

See `doc/14_a2a_protocol.md` for the full MCP section. Quick reference:

| Toolkit | Import | Description |
|---------|--------|-------------|
| `MCPTools` | `agno.tools.mcp` | Single MCP server |
| `MultiMCPTools` | `agno.tools.mcp` | Multiple MCP servers |
| `MCPToolbox` | `agno.tools.mcp_toolbox` | MCP Toolbox for Databases |

```python
from agno.tools.mcp import MCPTools

async with MCPTools("npx -y @modelcontextprotocol/server-filesystem /tmp") as mcp:
    agent = Agent(tools=[mcp])
    await agent.aprint_response("List all files")
```

---

## Special Purpose

| Toolkit | Import | Description |
|---------|--------|-------------|
| `ParallelTools` | `agno.tools.parallel` | Execute multiple tools concurrently |
| `UserControlFlowTools` | `agno.tools.user_control_flow` | Pause and ask the human a question |
| `UserFeedbackTools` | `agno.tools.user_feedback` | Collect thumbs-up/down feedback |
| `ReasoningTools` | `agno.tools.reasoning` | Built-in chain-of-thought |
| `KnowledgeTools` | `agno.tools.knowledge` | Agentic RAG queries |
| `Mem0Tools` | `agno.tools.mem0` | Mem0 external memory service |
| `ZepTools` | `agno.tools.zep` | Zep memory service |
| `StreamlitComponents` | `agno.tools.streamlit` | Render Streamlit UI components |

### Parallel tool execution

```python
from agno.tools.parallel import ParallelTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.arxiv import ArxivTools

agent = Agent(
    tools=[
        ParallelTools(tools=[
            DuckDuckGoTools(),
            ArxivTools(),
        ])
    ],
    instructions="Search web and ArXiv simultaneously, then synthesise.",
)
```

### Human-in-the-loop via tools

```python
from agno.tools.user_control_flow import UserControlFlowTools

agent = Agent(
    tools=[UserControlFlowTools()],
    instructions="If unsure, ask the user before proceeding.",
)
```
