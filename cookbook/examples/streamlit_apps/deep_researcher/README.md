# Deep Researcher

**Deep Researcher** is an AI-powered research assistant that uses a multi-agent workflow to conduct comprehensive research, analysis, and report generation.
The system automates the entire research process from web scraping to final report creation using specialized AI agents.

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
export NEBIUS_API_KEY=your_nebius_api_key_here
export SGAI_API_KEY=your_scrapegraph_api_key_here
```

Optional (for additional models):

```bash
export OPENAI_API_KEY=your_openai_key_here
export ANTHROPIC_API_KEY=your_anthropic_key_here
export GOOGLE_API_KEY=your_google_key_here
```

### 4. Run Deep Researcher App

```shell
streamlit run cookbook/examples/streamlit_apps/deep_researcher/app.py
```

## 🔧 How It Works

### Multi-Agent Workflow

The Deep Researcher uses a three-stage workflow:

1. **🔍 Searcher Agent**: Finds and extracts high-quality, up-to-date information from the web using ScrapeGraph
2. **🔬 Analyst Agent**: Synthesizes and interprets research findings, identifying key insights and trends
3. **✍️ Writer Agent**: Crafts clear, structured reports with actionable recommendations

### How to Use

- Open [localhost:8501](http://localhost:8501) in your browser.
- Configure your Nebius and ScrapeGraph API keys in the sidebar.
- Enter your research topic in the chat interface or click on example topics:
  - "Latest developments in AI and machine learning in 2024"
  - "Current trends in sustainable energy technologies"
  - "Recent breakthroughs in personalized medicine and genomics"
  - "Impact of quantum computing on cybersecurity"
- Watch the multi-agent workflow execute in real-time with streaming results.

### Key Features

- **Multi-Agent Pipeline**: Specialized agents for research, analysis, and writing
- **Real-Time Web Scraping**: Uses ScrapeGraph for comprehensive content extraction
- **Streaming Results**: See research progress and results in real-time
- **Structured Reports**: Professional formatting with references and recommendations
- **Example Topics**: Quick-start buttons for common research areas


## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)
- [ScrapeGraph Documentation](https://scrapegraphai.com)
- [Nebius AI Documentation](https://nebius.ai)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
