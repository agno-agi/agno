# Universal MCP Agent

**Universal MCP Agent (UAgI)** is a powerful agent application that leverages the Model Context Protocol (MCP) to provide a unified interface for interacting with various MCP servers. This application allows you to connect to different data sources and tools through MCP servers, providing a seamless experience for working with external services.

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/mcp_agent/requirements.txt
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

### 4. Install MCP Servers

The application requires Node.js and npm to run MCP servers:

For GitHub server:
```bash
npm install -g @modelcontextprotocol/server-github
```

### 5. Run PgVector

> Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) first.

- Run using a helper script

```shell
./cookbook/scripts/run_pgvector.sh
```

- OR run using the docker run command

```shell
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgvolume:/var/lib/postgresql/data \
  -p 5532:5432 \
  --name pgvector \
  agno/pgvector:16
```

### 6. Run the App

```shell
streamlit run cookbook/examples/streamlit_apps/mcp_agent/app.py
```

- Open [localhost:8501](http://localhost:8501) to view your app.

### Features

- **Multiple Model Support**: Works with various LLM providers (OpenAI, Anthropic, Google, Groq)
- **MCP Server Integration**: Connect to GitHub MCP server
- **Knowledge Base**: Built-in knowledge of MCP documentation
- **Session Management**: Save and restore chat sessions
- **Real-time Interaction**: Stream responses and display tool executions
- **Export Functionality**: Export chat history as markdown files

### Available MCP Servers

#### GitHub Server
- Search repositories
- Access repository information
- View issues and pull requests
- Interact with GitHub API

### How to Use

1. **Select Model**: Choose your preferred AI model from the sidebar
2. **Choose MCP Server**: Select which MCP server to connect to
3. **Start Chatting**: Ask questions or request actions that leverage the MCP server
4. **Monitor Connections**: View server status and connection information
5. **Export Conversations**: Save your chat history for later reference

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)