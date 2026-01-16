# Knowledge Protocol Implementation Guide

This guide explains how to create custom knowledge implementations that work seamlessly with Agno agents.

## What is the Knowledge Protocol?

The `KnowledgeProtocol` is a minimal interface that allows you to create custom knowledge sources for your agents. Instead of being forced into a single `search()` interface, each knowledge type defines:

- **Its own tools** - What operations agents can perform
- **Its own context** - Instructions on how to use those tools
- **Its own retrieval logic** - How to fetch information for context injection

## Why Implement the Protocol?

Implement the protocol when you want to:

- Connect agents to custom data sources (databases, APIs, filesystems, etc.)
- Expose specialized operations beyond simple search (e.g., `query_database`, `list_files`, `get_metadata`)
- Control how agents interact with your knowledge source
- Provide domain-specific tools and instructions

## Protocol Interface

### Required Methods

| Method | Purpose | Returns |
|--------|---------|---------|
| `build_context(**kwargs) -> str` | System prompt instructions | Instructions for the agent |
| `get_tools(**kwargs) -> List[Callable]` | Tools for the agent | List of callable functions |
| `aget_tools(**kwargs) -> List[Callable]` | Async version of get_tools | List of callable functions |

### Optional Methods

| Method | Purpose | When to implement |
|--------|---------|-------------------|
| `retrieve(query, **kwargs) -> List[Document]` | Fetch documents for context | If using `add_knowledge_to_context=True` |
| `aretrieve(query, **kwargs) -> List[Document]` | Async version of retrieve | Same as above (async agents) |

## Step-by-Step Implementation

### Step 1: Create Your Knowledge Class

Start with a basic class that holds your configuration:

```python
from dataclasses import dataclass
from typing import List, Any

@dataclass
class MyCustomKnowledge:
    """Custom knowledge implementation."""
    
    # Your configuration
    api_key: str
    endpoint: str
    max_results: int = 10
```

### Step 2: Implement Internal Logic

Add methods to interact with your data source. These are **not** exposed to the agent directly:

```python
@dataclass
class MyCustomKnowledge:
    api_key: str
    endpoint: str
    max_results: int = 10
    
    def _search_internal(self, query: str) -> List[dict]:
        """Internal method to search your data source."""
        # Your search implementation
        results = self._call_api(f"{self.endpoint}/search", {"q": query})
        return results
    
    def _get_document_internal(self, doc_id: str) -> dict:
        """Internal method to fetch a specific document."""
        result = self._call_api(f"{self.endpoint}/doc/{doc_id}")
        return result
    
    def _call_api(self, url: str, params: dict = None) -> dict:
        """Helper to call your API."""
        # Implementation here
        pass
```

### Step 3: Implement build_context()

Provide clear instructions for the agent:

```python
def build_context(self, **kwargs) -> str:
    """Build context string for the agent's system prompt."""
    return """
    You have access to a custom knowledge base.
    
    Available tools:
    - search_knowledge(query): Search for information using natural language
    - get_document(doc_id): Retrieve a specific document by ID
    
    Guidelines:
    - Always use search_knowledge first to find relevant information
    - If you see a document ID in results, use get_document to read the full content
    - Cite sources by mentioning document IDs
    """.strip()
```

### Step 4: Create Tool Functions

These are the functions the agent will call:

```python
def _create_search_tool(self) -> Any:
    """Create the search tool."""
    from agno.tools.function import Function
    
    def search_knowledge(query: str) -> str:
        """Search the knowledge base for information.
        
        Args:
            query: The search query in natural language.
            
        Returns:
            Search results with document IDs and snippets.
        """
        results = self._search_internal(query)
        
        if not results:
            return "No results found."
        
        # Format results for the agent
        output = []
        for result in results[:self.max_results]:
            output.append(
                f"Document ID: {result['id']}\n"
                f"Title: {result['title']}\n"
                f"Snippet: {result['snippet']}\n"
            )
        
        return "\n---\n".join(output)
    
    return Function.from_callable(search_knowledge)

def _create_get_document_tool(self) -> Any:
    """Create the get document tool."""
    from agno.tools.function import Function
    
    def get_document(doc_id: str) -> str:
        """Retrieve a specific document by its ID.
        
        Args:
            doc_id: The document ID (from search results).
            
        Returns:
            The full document content.
        """
        doc = self._get_document_internal(doc_id)
        
        if not doc:
            return f"Document not found: {doc_id}"
        
        return f"# {doc['title']}\n\n{doc['content']}"
    
    return Function.from_callable(get_document)
```

### Step 5: Implement get_tools()

Return all tools the agent should have access to:

```python
def get_tools(self, **kwargs) -> List[Any]:
    """Get tools to expose to the agent.
    
    Args:
        **kwargs: Context including run_response, run_context, async_mode, etc.
        
    Returns:
        List of callable tools.
    """
    return [
        self._create_search_tool(),
        self._create_get_document_tool(),
    ]

async def aget_tools(self, **kwargs) -> List[Any]:
    """Async version of get_tools."""
    # For simple cases, just return the same tools
    return self.get_tools(**kwargs)
    
    # For async tools, create async versions:
    # return [
    #     self._create_async_search_tool(),
    #     self._create_async_get_document_tool(),
    # ]
```

### Step 6: (Optional) Implement retrieve() for Context Injection

If you want to support `add_knowledge_to_context=True`:

```python
from agno.knowledge.document import Document

def retrieve(
    self,
    query: str,
    max_results: Optional[int] = None,
    **kwargs,
) -> List[Document]:
    """Retrieve documents for context injection.
    
    Used by the add_knowledge_to_context feature to pre-fetch
    relevant documents into the user message.
    
    Args:
        query: The query string.
        max_results: Maximum number of results.
        **kwargs: Additional parameters.
        
    Returns:
        List of Document objects.
    """
    results = self._search_internal(query)
    limit = max_results or self.max_results
    
    documents = []
    for result in results[:limit]:
        # Fetch full document
        doc = self._get_document_internal(result['id'])
        
        documents.append(
            Document(
                name=doc['title'],
                content=doc['content'],
                meta_data={
                    'id': doc['id'],
                    'source': 'custom_api',
                },
            )
        )
    
    return documents

async def aretrieve(
    self,
    query: str,
    max_results: Optional[int] = None,
    **kwargs,
) -> List[Document]:
    """Async version of retrieve."""
    # For async implementations:
    # results = await self._async_search_internal(query)
    # ...
    
    # For sync fallback:
    return self.retrieve(query, max_results=max_results, **kwargs)
```

### Step 7: Use with an Agent

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Create your knowledge instance
knowledge = MyCustomKnowledge(
    api_key="your-api-key",
    endpoint="https://api.example.com",
    max_results=5,
)

# Create agent with your knowledge
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,  # Enables the tools
    add_knowledge_to_context=True,  # Optional: pre-fetch context
)

# Agent now has access to your custom tools
agent.print_response("Find information about machine learning")
```

## Complete Example

See `filesystem.py` for a complete implementation that provides:
- `grep_file(query)` - Search file contents
- `list_files(pattern)` - List available files
- `get_file(path)` - Read specific files

```python
from agno.agent import Agent
from agno.knowledge.filesystem import FileSystemKnowledge
from agno.models.openai import OpenAIChat

# Filesystem knowledge implementation
fs_knowledge = FileSystemKnowledge(
    base_dir="/path/to/code",
    exclude_patterns=[".git", "node_modules"],
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=fs_knowledge,
    search_knowledge=True,
)

agent.print_response("Find where the main function is defined")
```

## Advanced: Async Tools

For async operations, create async versions of your tool functions:

```python
def _create_async_search_tool(self) -> Any:
    """Create async search tool."""
    from agno.tools.function import Function
    
    async def search_knowledge(query: str) -> str:
        """Async search the knowledge base."""
        results = await self._async_search_internal(query)
        # Format results...
        return formatted_results
    
    return Function.from_callable(search_knowledge)

def get_tools(self, async_mode: bool = False, **kwargs) -> List[Any]:
    """Get tools with async support."""
    if async_mode:
        return [
            self._create_async_search_tool(),
            self._create_async_get_document_tool(),
        ]
    else:
        return [
            self._create_search_tool(),
            self._create_get_document_tool(),
        ]
```

## Advanced: Tool Parameters from Context

The `get_tools()` method receives context from the agent:

```python
def get_tools(
    self,
    run_response=None,      # Add references here
    run_context=None,       # Access run context
    agent=None,             # The agent instance
    async_mode=False,       # Whether to return async tools
    enable_agentic_filters=False,  # For Knowledge class
    knowledge_filters=None, # Pre-set filters
    **kwargs
) -> List[Any]:
    """Get tools with full context."""
    
    # Example: Add search references to run_response
    def search_with_references(query: str) -> str:
        results = self._search_internal(query)
        
        # Track references
        if run_response is not None:
            from agno.models.message import MessageReferences
            run_response.references = run_response.references or []
            run_response.references.append(
                MessageReferences(
                    query=query,
                    references=[r.to_dict() for r in results],
                )
            )
        
        return self._format_results(results)
    
    return [Function.from_callable(search_with_references)]
```

## Best Practices

### DO:
- ✅ Provide clear, specific instructions in `build_context()`
- ✅ Use descriptive tool names and docstrings
- ✅ Return formatted, readable strings from tools
- ✅ Include error handling in tool functions
- ✅ Log debug info for troubleshooting
- ✅ Add metadata to Document objects

### DON'T:
- ❌ Expose internal methods directly as tools
- ❌ Return raw API responses - format them first
- ❌ Use generic tool names like "search" - be specific
- ❌ Forget to handle empty results gracefully
- ❌ Raise exceptions from tool functions - return error messages
- ❌ Include sensitive data in tool responses

## Testing Your Implementation

```python
# Test build_context
knowledge = MyCustomKnowledge(...)
context = knowledge.build_context()
print(context)  # Should be clear instructions

# Test get_tools
tools = knowledge.get_tools()
assert len(tools) > 0
assert callable(tools[0])

# Test tool execution
search_tool = tools[0]
result = search_tool.entrypoint("test query")
print(result)  # Should be formatted string

# Test with agent
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,
)
response = agent.run("Test question")
print(response.content)
```

## Troubleshooting

**Tools not appearing:**
- Check that `search_knowledge=True` on your Agent
- Verify `get_tools()` returns a non-empty list
- Ensure tools are `Function` objects or callables

**Context not applied:**
- Check that `build_context()` returns a non-empty string
- The agent automatically adds this to the system prompt

**retrieve() not called:**
- Requires `add_knowledge_to_context=True` on Agent
- Must return `List[Document]`, not strings

## Examples in the Codebase

- `knowledge.py` - Vector database search implementation
- `filesystem.py` - Filesystem grep/list/read implementation
- `protocol.py` - Protocol definition and documentation

## Need Help?

- Read the protocol definition: `agno.knowledge.protocol.KnowledgeProtocol`
- Study the filesystem example: `agno.knowledge.filesystem.FileSystemKnowledge`
- Check the changelog: `CHANGELOG_PROTOCOL.md`
