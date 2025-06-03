# Claude Prompt Caching

Prompt caching reduces costs and improves response times by caching portions of your prompts. Cached content costs only 10% of regular input tokens.

## Quick Start

```python
from agno.agent import Agent
from agno.models.anthropic import Claude

# Basic caching
agent = Agent(
    model=Claude(
        id="claude-3-5-sonnet-20241022",
        cache_system_prompt=True
    ),
    description="You are a helpful assistant with extensive knowledge..."
)

response = agent.run("What are microservices?")
print(f"Cached tokens: {response.metrics.get('cached_tokens', [0])[0]}")
```

## Configuration

### System Prompt Caching

```python
model = Claude(
    cache_system_prompt=True,  # Cache system messages
    extended_cache_time=True   # Use 1-hour cache (optional)
)
```

### Cache Duration

- **5-minute cache** (default): 1.25x cost to write, 0.1x to read
- **1-hour cache**: 2x cost to write, 0.1x to read

```python
# 5-minute cache (default)
model = Claude(cache_system_prompt=True)

# 1-hour cache
model = Claude(
    cache_system_prompt=True,
    extended_cache_time=True
)
```

## Usage Examples

### Large System Prompts

```python
large_prompt = """
You are an expert software architect specializing in:
- Microservices design patterns
- Cloud-native applications
- Performance optimization
- Security best practices
[... extensive instructions ...]
"""

agent = Agent(
    model=Claude(
        cache_system_prompt=True,
        extended_cache_time=True  # Long sessions
    ),
    description=large_prompt
)
```

### Document Analysis

```python
document_content = "..." # Large document text

agent = Agent(
    model=Claude(cache_system_prompt=True),
    description=f"Analyze this document:\n\n{document_content}"
)

# Multiple queries benefit from cached content
agent.run("Summarize key points")
agent.run("Extract action items")
agent.run("Identify risks")
```

### Conversational Agents

```python
agent = Agent(
    model=Claude(
        cache_system_prompt=True,
        extended_cache_time=True
    ),
    description="Long conversation context that gets reused..."
)

# Ongoing conversation benefits from caching
agent.run("Tell me about AI")
agent.run("How does machine learning work?")
agent.run("Explain neural networks")
```

## Monitoring Cache Performance

```python
response = agent.run("Your question here")

# Check cache metrics
metrics = response.metrics
cache_write = metrics.get('cache_write_tokens', [0])[0]
cached_tokens = metrics.get('cached_tokens', [0])[0]

print(f"Cache created: {cache_write} tokens")
print(f"Cache used: {cached_tokens} tokens")

# Calculate savings
if cached_tokens > 0:
    savings = cached_tokens * 0.9  # 90% savings on cached tokens
    print(f"Estimated savings: {savings} tokens")
```

## Cache Requirements

- **Claude 3.5 Sonnet/Opus**: Minimum 1,024 tokens
- **Claude 3.5 Haiku**: Minimum 2,048 tokens
- Content must be identical for cache hits

## Best Practices

### Structure for Caching

Place stable content at the beginning:

```python
# Good: Cache-friendly structure
system_prompt = f"""
{stable_instructions}    # Cached
{reference_material}     # Cached
{dynamic_context}        # Not cached
"""
```

### Choose Appropriate Duration

```python
# Frequent interactions
model = Claude(cache_system_prompt=True)  # 5-minute cache

# Long sessions or document analysis
model = Claude(
    cache_system_prompt=True,
    extended_cache_time=True  # 1-hour cache
)
```

### Monitor Effectiveness

```python
def track_cache_performance(response):
    metrics = response.metrics
    cached = metrics.get('cached_tokens', [0])[0]
    total_input = metrics.get('input_tokens', [0])[0] + cached

    if total_input > 0:
        hit_rate = cached / total_input
        print(f"Cache hit rate: {hit_rate:.1%}")

track_cache_performance(response)
```

## Common Use Cases

| Use Case              | Cache Duration | Benefits               |
| --------------------- | -------------- | ---------------------- |
| Document analysis     | 1-hour         | Reuse large documents  |
| Conversational agents | 5-minute       | Context preservation   |
| Code review           | 1-hour         | Reuse codebase context |
| Research tasks        | 5-minute       | Quick follow-ups       |

## Troubleshooting

**Cache not working?**

- Verify content meets minimum token requirements
- Ensure system prompt is identical between calls
- Check that calls are within cache TTL

**Low cache hit rate?**

- Move stable content to system prompt
- Use longer cache duration for infrequent calls
- Monitor with usage metrics

## Advanced Usage

### Custom Headers (if needed)

```python
model = Claude(
    cache_system_prompt=True,
    default_headers={
        "anthropic-beta": "prompt-caching-2024-07-31"
    }
)
```

### Streaming with Caching

```python
agent = Agent(
    model=Claude(cache_system_prompt=True),
    description="Large cached system prompt..."
)

# Streaming responses also benefit from caching
agent.print_response("Your question", stream=True)
```

For more examples, see `cookbook/models/anthropic/prompt_caching_extended.py`.
