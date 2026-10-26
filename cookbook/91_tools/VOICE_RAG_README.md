# ElevenLabs Voice RAG Tools

A comprehensive toolkit for building Voice RAG (Retrieval-Augmented Generation) agents using ElevenLabs Conversational AI within the Agno framework.

## Features

- 📄 **Document Upload**: Upload PDF, TXT, DOCX, CSV files to knowledge base
- 🔗 **URL Content**: Create knowledge from web pages and documentation
- 📝 **Text Content**: Add raw text to knowledge base
- 🤖 **Voice Agent Creation**: Create voice agents with RAG capabilities
- 🎤 **Real-time Voice Chat**: Speech-to-speech conversations
- 🌍 **Multi-language**: Support for Hindi, Spanish, French, and more
- ⚡ **Fast LLMs**: Qwen3-30B for ultra-low latency (~200ms)

## Installation

```bash
pip install agno httpx
```

## Environment Setup

```bash
export ELEVEN_LABS_API_KEY="your-api-key"
export OPENAI_API_KEY="your-openai-key"  # For orchestrating agent
```

## Quick Start

### Basic Usage

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.eleven_labs_voice_rag import ElevenLabsVoiceRAGTools

# Create agent with Voice RAG capabilities
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[ElevenLabsVoiceRAGTools(
        language="en",
        llm="qwen3-30b-a3b",  # Ultra low latency
    )],
    markdown=True,
)

# Create a voice agent from text content
agent.print_response("""
    Create a voice agent for a pizza restaurant with this menu:
    - Margherita: $12
    - Pepperoni: $14
    - Hawaiian: $15
    
    Name it "Pizza Bot" and give me the conversation URL.
""")
```

### Direct Tool Usage

```python
from agno.tools.eleven_labs_voice_rag import ElevenLabsVoiceRAGTools
import json

# Initialize toolkit
tools = ElevenLabsVoiceRAGTools(
    language="en",
    llm="qwen3-30b-a3b",
)

# Upload a document
result = json.loads(tools.upload_document("./docs/handbook.pdf"))
print(f"Document ID: {result['document_id']}")

# Create voice agent
agent_result = json.loads(tools.create_voice_agent(
    name="HR Assistant",
    system_prompt="You help employees with HR questions.",
    first_message="Hi! How can I help you today?",
))

print(f"Dashboard: {agent_result['dashboard_url']}")
print(f"Embed Code: {agent_result['embed_code']}")
# 1. Go to dashboard and enable "Public Access" in Security tab
# 2. Add embed_code to your HTML page to start voice conversation!
```

### Hindi Voice Agent

```python
tools = ElevenLabsVoiceRAGTools(
    language="hi",  # Hindi
    rag_embedding_model="multilingual_e5_large_instruct",
)

result = json.loads(tools.create_from_text(
    text="यह हमारी कंपनी की जानकारी है...",
    name="Company Info Hindi"
))

agent = json.loads(tools.create_voice_agent(
    name="हिंदी सहायक",
    system_prompt="आप एक सहायक हैं जो हिंदी में मदद करते हैं।",
    first_message="नमस्ते! मैं आपकी कैसे मदद कर सकता हूं?",
))
```

## CLI Demo

```bash
# From file
python voice_rag_demo.py --file doc.pdf --name "Doc Bot" --open-browser

# From URL
python voice_rag_demo.py --url https://docs.python.org --name "Python Helper"

# From text
python voice_rag_demo.py --text "Your content..." --name "Info Bot"

# Interactive mode
python voice_rag_demo.py --interactive
```

## Available Tools

| Tool | Description |
|------|-------------|
| `upload_document` | Upload PDF, TXT, DOCX files |
| `create_from_url` | Create content from web URL |
| `create_from_text` | Create content from raw text |
| `create_voice_agent` | Create RAG-enabled voice agent |
| `get_conversation_url` | Get WebSocket URL for voice chat |
| `list_voices` | List available voices |
| `list_documents` | List knowledge base documents |

## Configuration Options

```python
ElevenLabsVoiceRAGTools(
    api_key="...",                          # API key (or use env var)
    voice_id="cjVigY5qzO86Huf0OWal",       # Default voice
    language="en",                          # Language code
    llm="qwen3-30b-a3b",                   # LLM model
    rag_embedding_model="multilingual_e5_large_instruct",
    auto_compute_rag_index=True,           # Auto-index uploads
)
```

### Supported Languages

- `en` - English
- `hi` - Hindi  
- `es` - Spanish
- `fr` - French
- `de` - German
- `it` - Italian
- `pt` - Portuguese
- `ja` - Japanese
- `ko` - Korean
- `zh` - Chinese
- `ar` - Arabic
- `ru` - Russian

### Supported LLMs

- `qwen3-30b-a3b` - Ultra low latency (~200ms) ⚡
- `gpt-4o` - Best quality
- `gpt-4o-mini` - Good balance
- `claude-3-5-sonnet` - Anthropic
- `gemini-2.0-flash-exp` - Google

## How It Works

1. **Upload Content**: Documents, URLs, or text are uploaded to ElevenLabs Knowledge Base
2. **RAG Indexing**: Content is automatically indexed for semantic search
3. **Agent Creation**: Voice agent is created with the knowledge base attached
4. **Voice Conversation**: User speaks to the agent via browser widget
5. **RAG Retrieval**: Agent retrieves relevant content to answer questions
6. **Voice Response**: Agent responds in real-time with synthesized speech

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for contribution guidelines.

## License

MIT License - See [LICENSE](../../LICENSE) for details.
