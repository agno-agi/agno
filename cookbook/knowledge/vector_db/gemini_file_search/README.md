# Gemini File Search

Gemini File Search provides a managed vector database integrated with Google's Gemini AI models. It allows you to upload documents and perform semantic search using Google's infrastructure.

## Features

- **Managed Service**: No infrastructure management required
- **Native Integration**: Seamlessly works with Gemini models
- **File Upload**: Directly upload documents to Google's File Search Store
- **Metadata Filtering**: Filter search results by custom metadata
- **Grounding Support**: Get responses with citation metadata

## Installation

```bash
pip install google-genai
```

## Configuration

Set your Google API key as an environment variable:

```bash
export GOOGLE_API_KEY="your-api-key-here"
```

Or get one from: https://ai.google.dev/

## Basic Usage

```python
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.gemini.gemini_file_search import GeminiFileSearch

# Create Gemini File Search vector database
vector_db = GeminiFileSearch(
    file_search_store_name="my-knowledge-store",
    model_name="gemini-2.5-flash-lite",
    api_key="your-api-key",
)

# Create knowledge base
knowledge = Knowledge(
    name="My Knowledge Base",
    vector_db=vector_db,
)

# Add documents
knowledge.add_content(
    name="MyDocument",
    url="https://example.com/document.pdf",
    metadata={"doc_type": "manual"},
)

# Create agent and query
agent = Agent(knowledge=knowledge, search_knowledge=True)
agent.print_response("What is covered in the document?")
```

## Examples

- **[gemini_file_search.py](./gemini_file_search.py)** - Basic usage with Thai recipe knowledge base
- **[async_gemini_file_search.py](./async_gemini_file_search.py)** - Async operations with Agno documentation
- **[gemini_file_search_with_filters.py](./gemini_file_search_with_filters.py)** - Using metadata filters for refined search

## Supported Operations

| Operation | Supported | Notes |
|-----------|-----------|-------|
| `create()` | ✅ | Creates or gets existing File Search Store |
| `insert()` | ✅ | Uploads documents to the store |
| `search()` | ✅ | Semantic search with optional metadata filters |
| `upsert()` | ✅ | Updates existing documents or inserts new ones |
| `delete_by_name()` | ✅ | Delete documents by display name |
| `delete_by_id()` | ✅ | Delete documents by ID |
| `delete_by_content_id()` | ✅ | Delete documents by content ID |
| `delete_by_metadata()` | ❌ | Not supported by Gemini File Search |
| `update_metadata()` | ❌ | Not supported by Gemini File Search |

## Important Notes

1. **File Search Store**: Documents are organized in "File Search Stores" - named containers for your documents
2. **Document Names**: Each document has both a system-generated `name` (ID) and a user-defined `display_name`
3. **Operation Polling**: Document uploads are asynchronous; the library polls until completion
4. **Metadata Limitations**: 
   - Supports string, numeric, and float metadata values
   - Metadata can be used for filtering during search
   - Cannot update metadata after upload (must delete and re-upload)
5. **Cost**: Check Google AI pricing for File Search Store usage

## Model Options

Gemini File Search supports various Gemini models:

- `gemini-2.5-flash-lite` (default) - Fast and cost-effective
- `gemini-2.5-flash` - Balanced performance
- `gemini-2.0-flash` - High performance
- `gemini-2.0-flash-exp` - Experimental features

## API Reference

See the [GeminiFileSearch documentation](../../../../libs/agno/agno/vectordb/gemini/gemini_file_search.py) for detailed API information.

## Resources

- [Google AI Gemini Docs](https://ai.google.dev/gemini-api/docs)
- [File Search API](https://ai.google.dev/gemini-api/docs/file-search)
- [Agno Documentation](https://docs.agno.com)
