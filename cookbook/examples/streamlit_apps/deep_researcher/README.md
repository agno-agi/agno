# Deep Researcher Agent

A multi-stage AI-powered research workflow agent that automates comprehensive web research, analysis, and report generation using Agno, Scrapegraph, and Nebius AI.

1. **Searcher**: Finds and extracts high-quality, up-to-date information from the web using Scrapegraph and Nebius AI.
2. **Analyst**: Synthesizes, interprets, and organizes the research findings, highlighting key insights and trends.
3. **Writer**: Crafts a clear, structured, and actionable report, including references and recommendations.


## Installation

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/deep_researcher/requirements.txt
```

### 3. Configure API Keys

Required:
```bash
export OPENAI_API_KEY=your_openai_key_here
export NEBIUS_API_KEY=your_nebius_api_key_here
export SGAI_API_KEY=your_scrapegraph_api_key_here
```


## Usage

You can use the Deep Researcher Agent in three ways. Each method below includes a demo image so you know what to expect.

### Web Interface

Run the Streamlit app:

```bash
streamlit run cookbook/examples/streamlit_apps/deep_researcher/app.py
```

Open your browser at [http://localhost:8501](http://localhost:8501)

### MCP Server

Add the following configuration to your .cursor/mcp.json or Claude/claude_desktop_config.json file (adjust paths and API keys as needed):

```json
{
  "mcpServers": {
    "deep_researcher_agent": {
      "command": "python",
      "args": [
        "--directory",
        "/Your/Path/to/directory/cookbook/examples/streamlit_apps/deep_researcher/server.py",
        "run",
        "server.py"
      ],
      "env": {
        "NEBIUS_API_KEY": "your_nebius_api_key_here",
        "SGAI_API_KEY": "your_scrapegraph_api_key_here"
      }
    }
  }
}
```

This allows tools like Claude Desktop to manage and launch the MCP server automatically.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request or open an issue.

## 📚 Documentation

For more detailed information:
- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
