# Agno Library API Documentation

Agno is a Python framework for building AI agents, teams, and workflows. This document provides comprehensive API documentation for all major components.

## Installation

```bash
pip install agno
```

## Core Components

### 1. Agent

**Import Path**: `from agno import Agent`

**Description**: Core agent class for building AI agents with models, tools, memory, and knowledge.

**Constructor**:
```python
Agent(
    model: Optional[Model] = None,
    name: Optional[str] = None,
    agent_id: Optional[str] = None,
    introduction: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    session_name: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    memory: Optional[Union[AgentMemory, Memory]] = None,
    context: Optional[Dict[str, Any]] = None,
    add_context: bool = False,
    resolve_context: bool = True
)
```

**Key Methods**:
- `run(message, *, stream=False, **kwargs)` - Execute agent with message
- `print_response()` - Print agent response

**Example**:
```python
from agno import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4"),
    name="MyAgent"
)
response = agent.run("Hello, world!")
```

### 2. Team

**Import Path**: `from agno import Team`

**Description**: Orchestrates multiple agents working together in different modes.

**Constructor**:
```python
Team(
    members: List[Union[Agent, "Team"]],  # Required
    mode: Literal["route", "coordinate", "collaborate"] = "coordinate",
    model: Optional[Model] = None,
    name: Optional[str] = None,
    team_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    session_name: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    team_session_state: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    instructions: Optional[Union[str, List[str], Callable]] = None
)
```

**Key Methods**:
- `run(message, *, stream=False, **kwargs)` - Execute team with message
- `print_response()` - Print team response
- `add_tool(tool)` - Add tool to team

**Example**:
```python
from agno import Team

team = Team(
    members=[agent1, agent2],
    mode="coordinate",
    name="MyTeam"
)
response = team.run("Solve this problem together")
```

### 3. Workflow

**Import Path**: `from agno import Workflow`

**Description**: Base class for creating multi-step AI workflows.

**Constructor**:
```python
Workflow(
    name: Optional[str] = None,
    workflow_id: Optional[str] = None,
    app_id: Optional[str] = None,
    description: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    session_name: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    memory: Optional[Union[WorkflowMemory, Memory]] = None,
    storage: Optional[Storage] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    debug_mode: bool = False,
    monitoring: bool = False,
    telemetry: bool = True
)
```

**Key Methods**:
- `run(**kwargs)` - Execute workflow (must be implemented in subclass)
- `run_workflow(**kwargs)` - Run the workflow

**Example**:
```python
from agno import Workflow

class MyWorkflow(Workflow):
    def run(self, **kwargs):
        # Implementation here
        pass

workflow = MyWorkflow(name="MyWorkflow")
```


## Models

### Base Model Class

**Import Path**: `from agno.models.base import Model`

**Description**: Abstract base class for all AI models.

**Key Attributes**:
- `id: str` - ID of the model to use
- `name: Optional[str]` - Name for this Model
- `provider: Optional[str]` - Provider for this Model

### OpenAI Models

**Import Path**: `from agno.models.openai import OpenAIChat`

**Constructor**:
```python
OpenAIChat(
    id: str = "gpt-4",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None
)
```

**Example**:
```python
from agno.models.openai import OpenAIChat

model = OpenAIChat(id="gpt-4", temperature=0.7)
```

### Anthropic Models

**Import Path**: `from agno.models.anthropic import Claude`

**Constructor**:
```python
Claude(
    id: str = "claude-3-5-sonnet-20241022",
    api_key: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None
)
```

### Other Available Models

- **Google Gemini**: `from agno.models.google import Gemini`
- **Groq**: `from agno.models.groq import Groq`
- **Ollama**: `from agno.models.ollama import OllamaChat`
- **Cohere**: `from agno.models.cohere import CohereChat`
- **Mistral**: `from agno.models.mistral import Mistral`
- **Azure OpenAI**: `from agno.models.azure import AzureOpenAIChat`
- **AWS Bedrock**: `from agno.models.aws import AWSBedrock`
- **Hugging Face**: `from agno.models.huggingface import HuggingFace`

## Tools

### Core Tool Classes

**Function**: `from agno.tools import Function`

**Constructor**:
```python
Function(
    name: str,
    description: Optional[str] = None,
    parameters: Dict[str, Any] = {}
)
```

**Toolkit**: `from agno.tools import Toolkit`

**Constructor**:
```python
Toolkit(
    name: str,
    tools: List[Callable],
    instructions: Optional[str] = None
)
```

### Built-in Tools

- **PythonTools**: `from agno.tools.python import PythonTools`
- **ShellTools**: `from agno.tools.shell import ShellTools`
- **WebsiteTools**: `from agno.tools.website import WebsiteTools`
- **GithubTools**: `from agno.tools.github import GithubTools`
- **SerperTools**: `from agno.tools.serper import SerperTools`
- **DuckDuckGoTools**: `from agno.tools.duckduckgo import DuckDuckGoTools`
- **FileTools**: `from agno.tools.file import FileTools`
- **EmailTools**: `from agno.tools.email import EmailTools`

**Example**:
```python
from agno.tools.python import PythonTools
from agno.tools.shell import ShellTools
from agno.tools import Toolkit

toolkit = Toolkit(
    name="dev_tools",
    tools=[PythonTools(), ShellTools()],
    instructions="Development tools for code execution"
)

agent = Agent(
    model=OpenAIChat(),
    tools=[toolkit]
)
```


## Knowledge & RAG

### AgentKnowledge

**Import Path**: `from agno.knowledge import AgentKnowledge`

**Constructor**:
```python
AgentKnowledge(
    reader: Optional[Reader] = None,
    vector_db: Optional[VectorDb] = None,
    num_documents: int = 5
)
```

**Description**: Manages document reading and vector storage for RAG (Retrieval-Augmented Generation).

**Example**:
```python
from agno.knowledge import AgentKnowledge
from agno.vectordb.chroma import ChromaDb
from agno.document.reader.pdf_reader import PDFReader

knowledge = AgentKnowledge(
    reader=PDFReader(),
    vector_db=ChromaDb(collection="docs"),
    num_documents=10
)

agent = Agent(
    model=OpenAIChat(),
    knowledge=knowledge
)
```

## Document Processing

### Document Readers

**Base Reader**: `from agno.document.reader import Reader`

**Available Readers**:
- **PDFReader**: `from agno.document.reader.pdf_reader import PDFReader`
- **TextReader**: `from agno.document.reader.text_reader import TextReader`
- **CSVReader**: `from agno.document.reader.csv_reader import CSVReader`
- **DocxReader**: `from agno.document.reader.docx_reader import DocxReader`
- **JSONReader**: `from agno.document.reader.json_reader import JSONReader`
- **URLReader**: `from agno.document.reader.url_reader import URLReader`
- **WebsiteReader**: `from agno.document.reader.website_reader import WebsiteReader`
- **ArxivReader**: `from agno.document.reader.arxiv_reader import ArxivReader`
- **YoutubeReader**: `from agno.document.reader.youtube_reader import YoutubeReader`

### Chunking Strategies

- **FixedSizeChunking**: `from agno.document.chunking.fixed import FixedSizeChunking`
- **RecursiveChunking**: `from agno.document.chunking.recursive import RecursiveChunking`
- **SemanticChunking**: `from agno.document.chunking.semantic import SemanticChunking`

**Example**:
```python
from agno.document.reader.pdf_reader import PDFReader
from agno.document.chunking.semantic import SemanticChunking
from agno.embedder.openai import OpenAIEmbedder

reader = PDFReader(
    chunking_strategy=SemanticChunking(
        embedder=OpenAIEmbedder(),
        chunk_size=1000,
        similarity_threshold=0.7
    )
)
```

## Embedders

### Base Embedder

**Import Path**: `from agno.embedder import Embedder`

### Available Embedders

- **OpenAIEmbedder**: `from agno.embedder.openai import OpenAIEmbedder`
- **AzureOpenAIEmbedder**: `from agno.embedder.azure_openai import AzureOpenAIEmbedder`
- **CohereEmbedder**: `from agno.embedder.cohere import CohereEmbedder`
- **SentenceTransformerEmbedder**: `from agno.embedder.sentence_transformer import SentenceTransformerEmbedder`
- **OllamaEmbedder**: `from agno.embedder.ollama import OllamaEmbedder`
- **HuggingFaceEmbedder**: `from agno.embedder.huggingface import HuggingFaceEmbedder`
- **VoyageAIEmbedder**: `from agno.embedder.voyageai import VoyageAIEmbedder`
- **GoogleEmbedder**: `from agno.embedder.google import GoogleEmbedder`

**Example**:
```python
from agno.embedder.openai import OpenAIEmbedder

embedder = OpenAIEmbedder(
    id="text-embedding-3-small",
    dimensions=1536
)
```


## Vector Databases

### Base VectorDb

**Import Path**: `from agno.vectordb import VectorDb`

### Available Vector Databases

- **ChromaDb**: `from agno.vectordb.chroma import ChromaDb`
- **PineconeDb**: `from agno.vectordb.pineconedb import PineconeDb`
- **PgVector**: `from agno.vectordb.pgvector import PgVector`
- **QdrantDb**: `from agno.vectordb.qdrant import QdrantDb`
- **LanceDb**: `from agno.vectordb.lancedb import LanceDb`
- **Weaviate**: `from agno.vectordb.weaviate import Weaviate`
- **Milvus**: `from agno.vectordb.milvus import Milvus`
- **ClickHouse**: `from agno.vectordb.clickhouse import ClickHouse`

**Example**:
```python
from agno.vectordb.chroma import ChromaDb
from agno.embedder.openai import OpenAIEmbedder

vector_db = ChromaDb(
    collection="my_docs",
    embedder=OpenAIEmbedder(),
    path="./chroma_db"
)
```

## Memory

### AgentMemory

**Import Path**: `from agno.memory import AgentMemory`

**Constructor**:
```python
AgentMemory(
    runs: List[AgentRun] = [],
    messages: List[Message] = [],
    create_session_summary: bool = False
)
```

### Memory Classes

- **Memory**: `from agno.memory import Memory`
- **MemoryRow**: `from agno.memory import MemoryRow`
- **TeamMemory**: `from agno.memory import TeamMemory`

**Example**:
```python
from agno.memory import AgentMemory

memory = AgentMemory(
    create_session_summary=True
)

agent = Agent(
    model=OpenAIChat(),
    memory=memory
)
```

## Storage

### Base Storage

**Import Path**: `from agno.storage.base import Storage`

### Available Storage Backends

- **PostgresAgentStorage**: `from agno.storage.agent.postgres import PostgresAgentStorage`
- **SqliteAgentStorage**: `from agno.storage.agent.sqlite import SqliteAgentStorage`
- **JsonStorage**: `from agno.storage.json import JsonStorage`
- **MongoDbStorage**: `from agno.storage.mongodb import MongoDbStorage`
- **DynamoDbStorage**: `from agno.storage.dynamodb import DynamoDbStorage`

**Example**:
```python
from agno.storage.agent.postgres import PostgresAgentStorage

storage = PostgresAgentStorage(
    db_url="postgresql://user:pass@localhost/db"
)

agent = Agent(
    model=OpenAIChat(),
    storage=storage
)
```


## App Frameworks

### FastAPI Integration

**Import Path**: `from agno.app.fastapi import FastAPIApp`

**Constructor**:
```python
FastAPIApp(
    agents: Optional[List[Agent]] = None,
    teams: Optional[List[Team]] = None,
    workflows: Optional[List[Workflow]] = None
)
```

**Example**:
```python
from agno.app.fastapi import FastAPIApp

app = FastAPIApp(
    agents=[agent],
    teams=[team]
)

# Run with: uvicorn app:app
```

### Other App Integrations

- **SlackAPI**: `from agno.app.slack import SlackAPI`
- **DiscordClient**: `from agno.app.discord import DiscordClient`
- **WhatsAppApp**: `from agno.app.whatsapp import WhatsAppApp`
- **PlaygroundApp**: `from agno.app.playground import PlaygroundApp`

## CLI Commands

### Workspace Management

```bash
# Create new workspace
ag ws create

# Start workspace resources
ag ws start

# Stop workspace resources
ag ws stop

# Restart workspace resources
ag ws restart

# Update workspace resources
ag ws patch
```

### Configuration

```bash
# Initialize Agno
ag init

# Configuration management
ag config

# Health check
ag ping
```

## Complete Examples

### Basic Agent with Tools

```python
from agno import Agent
from agno.models.openai import OpenAIChat
from agno.tools.python import PythonTools
from agno.tools.shell import ShellTools

agent = Agent(
    model=OpenAIChat(id="gpt-4"),
    name="DevAgent",
    tools=[PythonTools(), ShellTools()],
    instructions="You are a helpful development assistant."
)

response = agent.run("Create a Python script to calculate fibonacci numbers")
print(response.content)
```

### Agent with Knowledge Base

```python
from agno import Agent
from agno.models.openai import OpenAIChat
from agno.knowledge import AgentKnowledge
from agno.vectordb.chroma import ChromaDb
from agno.document.reader.pdf_reader import PDFReader
from agno.embedder.openai import OpenAIEmbedder

# Setup knowledge base
knowledge = AgentKnowledge(
    reader=PDFReader(),
    vector_db=ChromaDb(
        collection="docs",
        embedder=OpenAIEmbedder()
    ),
    num_documents=5
)

# Load documents
knowledge.load_documents(["document1.pdf", "document2.pdf"])

# Create agent
agent = Agent(
    model=OpenAIChat(id="gpt-4"),
    name="RAGAgent",
    knowledge=knowledge,
    instructions="Answer questions based on the provided documents."
)

response = agent.run("What are the key points in the documents?")
```

### Multi-Agent Team

```python
from agno import Agent, Team
from agno.models.openai import OpenAIChat
from agno.tools.python import PythonTools
from agno.tools.web import WebTools

# Create specialized agents
researcher = Agent(
    model=OpenAIChat(id="gpt-4"),
    name="Researcher",
    tools=[WebTools()],
    instructions="Research topics and gather information."
)

analyst = Agent(
    model=OpenAIChat(id="gpt-4"),
    name="Analyst",
    tools=[PythonTools()],
    instructions="Analyze data and create visualizations."
)

# Create team
team = Team(
    members=[researcher, analyst],
    mode="coordinate",
    name="ResearchTeam",
    instructions="Work together to research and analyze topics."
)

response = team.run("Research AI trends and create a summary with charts")
```

### Workflow Example

```python
from agno import Workflow, Agent
from agno.models.openai import OpenAIChat
from agno.tools.python import PythonTools

class DataAnalysisWorkflow(Workflow):
    def __init__(self):
        super().__init__(name="DataAnalysisWorkflow")
        
        self.data_collector = Agent(
            model=OpenAIChat(id="gpt-4"),
            name="DataCollector",
            tools=[PythonTools()]
        )
        
        self.analyzer = Agent(
            model=OpenAIChat(id="gpt-4"),
            name="Analyzer",
            tools=[PythonTools()]
        )
    
    def run(self, data_source: str):
        # Step 1: Collect data
        collection_result = self.data_collector.run(
            f"Collect data from {data_source}"
        )
        
        # Step 2: Analyze data
        analysis_result = self.analyzer.run(
            f"Analyze this data: {collection_result.content}"
        )
        
        return analysis_result

# Use workflow
workflow = DataAnalysisWorkflow()
result = workflow.run("sales_data.csv")
```

## Best Practices

1. **Model Selection**: Choose appropriate models based on task complexity and cost requirements
2. **Tool Integration**: Use specific tools for specific tasks (PythonTools for code, WebTools for research)
3. **Memory Management**: Enable session summaries for long conversations
4. **Knowledge Base**: Use semantic chunking for better retrieval quality
5. **Team Coordination**: Use "coordinate" mode for collaborative tasks, "route" for specialized routing
6. **Error Handling**: Implement proper error handling in workflows
7. **Resource Management**: Use appropriate storage backends for persistence needs

## Environment Variables

Common environment variables used by Agno:

```bash
# OpenAI
OPENAI_API_KEY=your_openai_key

# Anthropic
ANTHROPIC_API_KEY=your_anthropic_key

# Google
GOOGLE_API_KEY=your_google_key

# Database URLs
DATABASE_URL=postgresql://user:pass@localhost/db
REDIS_URL=redis://localhost:6379

# Vector Database
PINECONE_API_KEY=your_pinecone_key
QDRANT_URL=http://localhost:6333
```

This documentation covers the essential API components of the Agno library. For more detailed examples and advanced usage, refer to the cookbook examples in the repository.
