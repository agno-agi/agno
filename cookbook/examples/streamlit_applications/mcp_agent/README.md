# UAgI: Universal Agent Interface powered by MCP

> [!IMPORTANT]
> This is a work in progress (see [open issues](#-open-issues) below), please contribute and help improve.

UAgI (Universal Agent Interface) is a powerful agent application that leverages the Model Context Protocol (MCP) to provide a unified interface for interacting with various MCP servers. This application allows you to connect to different data sources and tools through MCP servers, providing a seamless experience for working with external services.

## 🌟 Features

- **Multiple Model Support**: Works with various LLM providers including:
  - OpenAI (o3-mini, gpt-4o, gpt-4.5)
  - Anthropic (claude-3-7-sonnet, claude-3-7-sonnet-thinking)
  - Google (gemini-2.0-flash, gemini-2.0-pro)
  - Groq (llama-3.3-70b-versatile)

- **MCP Server Integration**: Connect to the following MCP servers:
  - GitHub: Access repositories, issues, and more
  - Filesystem: Browse and manipulate files on your local system

- **Knowledge Base**: Built-in knowledge of MCP documentation to help answer questions about the protocol

- **Session Management**: Save and restore chat sessions using SQLite storage

- **Chat History Export**: Export your conversations as markdown files

- **Streamlit UI**: User-friendly interface with customizable settings

## 🐞 Open Issues

- Only works with 1 MCP server at a time
- Changing MCP servers resets the agent
- Only supports 2 MCP servers at the moment
- Chat history is broken
- MCP Cleanup is not working, so memory leaks are possible

## 🚀 Quick Start

### 1. Environment Setup

Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r cookbook/examples/apps/mcp_agent/requirements.txt
```

### 3. Configure API Keys

Required:
```bash
export OPENAI_API_KEY=your_openai_key_here
```

Optional (for additional models):
```bash
export ANTHROPIC_API_KEY=your_anthropic_key_here
export GOOGLE_API_KEY=your_google_key_here
export GROQ_API_KEY=your_groq_key_here
```

For GitHub MCP server:
```bash
export GITHUB_TOKEN=your_github_token_here
```

### 4. Launch the Application

```bash
streamlit run cookbook/examples/apps/mcp_agent/app.py
```

Visit [localhost:8501](http://localhost:8501) to access the UAgI application.

## 🔧 How It Works

UAgI connects to MCP servers using the Model Context Protocol, which standardizes how applications provide context to LLMs. When you ask a question:

1. The agent analyzes your request and determines which MCP tools might be helpful
2. It connects to the appropriate MCP server (GitHub, Filesystem, etc.)
3. The agent executes the necessary tools through the MCP server
4. Results are processed and returned in a natural language response
5. All interactions are saved in your session history

## 📚 Understanding MCP

The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context to LLMs. Think of MCP like a USB-C port for AI applications - it provides a standardized way to connect AI models to different data sources and tools.

MCP helps you build agents and complex workflows on top of LLMs by providing:
- A growing list of pre-built integrations that your LLM can directly plug into
- The flexibility to switch between LLM providers and vendors
- Best practices for securing your data within your infrastructure

## 🛠️ Customization

### Adding New MCP Servers

The application is designed to be extensible. To add new MCP servers:

1. Update the `get_mcp_server_config()` function in `utils.py`
2. Add server-specific example inputs in the `example_inputs()` function

### Modifying Agent Behavior

The agent configuration is in `agents.py`:
- Adjust the agent description and instructions to change its behavior
- Modify the knowledge base to include additional documentation
- Add new tools or capabilities as needed

## 📚 Documentation

For more detailed information:
- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
