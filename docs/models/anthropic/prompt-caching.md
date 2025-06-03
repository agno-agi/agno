# Claude Prompt Caching in Agno

This guide explains how to use the enhanced prompt caching features with Claude models in Agno. Prompt caching can significantly reduce costs and improve response times for applications with repetitive content or large contexts.

## Overview

Prompt caching allows you to cache portions of your prompts to avoid reprocessing the same content repeatedly. This is especially beneficial for:

- **Large system prompts** with extensive instructions
- **Tool definitions** that remain constant across calls
- **Long conversation contexts** in multi-turn interactions
- **Document analysis** with large amounts of reference material

## Cost Benefits

Cached content costs only **10% of regular input tokens**, providing up to **90% cost savings** for cached portions:

| Cache Type     | Cost Multiplier            | Use Case              |
| -------------- | -------------------------- | --------------------- |
| 5-minute cache | 1.25x (write), 0.1x (read) | Regular conversations |
| 1-hour cache   | 2x (write), 0.1x (read)    | Long-running sessions |

## Configuration Options

### Basic System Message Caching

```python
from agno.models.anthropic import Claude

# Enable basic system prompt caching
model = Claude(
    id="claude-3-5-sonnet-20241022",
    cache_system_prompt=True,  # Cache the system message
    cache_ttl="5m"            # Cache for 5 minutes (default)
)
```

### Enhanced Caching Features

```python
# Comprehensive caching configuration
model = Claude(
    id="claude-3-5-sonnet-20241022",

    # General caching settings
    enable_prompt_caching=True,     # Enable overall caching
    cache_ttl="1h",                 # 1-hour cache duration

    # Specific caching options
    cache_system_prompt=True,       # Cache system messages
    cache_tool_definitions=True,    # Cache tool definitions

    # Message-level caching
    cache_messages={
        "cache_last": True,         # Cache the last message
        "indices": [0, 2],          # Cache specific message indices
        "ttl": "1h"                 # TTL for message caching
    }
)
```

## Cache Duration Options

### 5-Minute Cache (Default)

- **Cost**: 1.25x input price to write, 0.1x to read
- **Best for**: Regular conversations, frequent interactions
- **Automatic refresh**: Cache refreshes for free when used

```python
model = Claude(
    cache_system_prompt=True,
    cache_ttl="5m"  # Default duration
)
```

### 1-Hour Cache (Beta)

- **Cost**: 2x input price to write, 0.1x to read
- **Best for**: Long sessions, infrequent but repeated use
- **Use cases**: Document analysis, long conversations

```python
model = Claude(
    cache_system_prompt=True,
    cache_ttl="1h"  # Extended duration
)
```

## Caching Strategies

### 1. System Message Caching

Cache large system prompts that don't change between requests:

```python
from agno.agent import Agent

large_system_prompt = """
You are an expert financial analyst with deep knowledge of:
- Market analysis and forecasting
- Risk assessment methodologies
- Investment portfolio optimization
- Regulatory compliance frameworks
- Financial modeling techniques
[... extensive instructions ...]
"""

agent = Agent(
    model=Claude(
        cache_system_prompt=True,
        cache_ttl="1h"
    ),
    description=large_system_prompt
)
```

### 2. Tool Definition Caching

Cache tool definitions when using the same tools across multiple requests:

```python
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Claude(
        cache_tool_definitions=True,
        enable_prompt_caching=True
    ),
    tools=[DuckDuckGoTools()],
    description="Research assistant with web search capabilities"
)
```

### 3. Message Content Caching

Cache specific messages in conversations:

```python
# Cache the last message in ongoing conversations
model = Claude(
    cache_messages={
        "cache_last": True,
        "ttl": "5m"
    }
)

# Cache specific message indices
model = Claude(
    cache_messages={
        "indices": [0, 1, 5],  # Cache messages at these positions
        "ttl": "1h"
    }
)
```

### 4. Comprehensive Caching

Combine all caching strategies for maximum benefit:

```python
agent = Agent(
    model=Claude(
        # Enable all caching features
        enable_prompt_caching=True,
        cache_system_prompt=True,
        cache_tool_definitions=True,
        cache_messages={"cache_last": True},
        cache_ttl="1h"
    ),
    tools=[DuckDuckGoTools()],
    description=large_knowledge_base
)
```

## Usage Metrics

Monitor caching effectiveness through detailed usage metrics:

```python
response = agent.run("Analyze this data...")

usage = response.usage
print(f"Input tokens: {usage['input_tokens']}")
print(f"Output tokens: {usage['output_tokens']}")
print(f"Cached tokens: {usage['cached_tokens']}")
print(f"Cache writes: {usage.get('cache_write_tokens', 0)}")

# Enhanced metrics for 1-hour cache
if 'cache_5m_write_tokens' in usage:
    print(f"5m cache writes: {usage['cache_5m_write_tokens']}")
if 'cache_1h_write_tokens' in usage:
    print(f"1h cache writes: {usage['cache_1h_write_tokens']}")
```

## Best Practices

### 1. Cache Stable Content First

Place the most stable, reusable content at the beginning of your prompts:

- System instructions
- Tool definitions
- Large reference documents
- Examples and templates

### 2. Use Appropriate Cache Duration

- **5-minute cache**: Regular conversations, frequent API calls
- **1-hour cache**: Long sessions, document analysis, infrequent calls

### 3. Monitor Cache Hit Rates

Track your cache effectiveness:

```python
def calculate_cache_savings(usage):
    cached_tokens = usage.get('cached_tokens', 0)
    total_input = usage.get('input_tokens', 0) + cached_tokens

    if total_input > 0:
        hit_rate = cached_tokens / total_input
        print(f"Cache hit rate: {hit_rate:.1%}")
        return hit_rate
    return 0
```

### 4. Structure for Caching

Organize your prompts to maximize cache effectiveness:

```python
# Good: Cacheable content first
system_prompt = f"""
{stable_instructions}  # Cache this
{tool_definitions}     # Cache this
{reference_docs}       # Cache this
{dynamic_context}      # Don't cache this
"""
```

## Common Use Cases

### Document Analysis

```python
# Cache large documents for multiple analysis tasks
model = Claude(
    enable_prompt_caching=True,
    cache_ttl="1h"
)

agent = Agent(
    model=model,
    description=f"Analyze this document:\n\n{large_document_text}"
)

# Multiple queries benefit from cached document
questions = [
    "Summarize the key themes",
    "Identify main arguments",
    "Extract action items"
]
```

### Conversational Agents

```python
# Cache conversation context for ongoing sessions
model = Claude(
    cache_messages={"cache_last": True, "ttl": "5m"},
    cache_system_prompt=True
)
```

### Code Analysis

```python
# Cache codebase context for multiple operations
model = Claude(
    enable_prompt_caching=True,
    cache_tool_definitions=True,
    cache_ttl="1h"
)
```

## Troubleshooting

### Cache Misses

If you're not seeing cache hits:

1. **Check minimum token requirements**:

   - Claude 3.5 Sonnet/Opus: 1024 tokens minimum
   - Claude 3.5 Haiku: 2048 tokens minimum

2. **Verify content consistency**: Cache requires exact matches

3. **Check timing**: Ensure calls are within cache TTL

### Performance Issues

- Use 1-hour cache for infrequent but repeated content
- Monitor cache hit rates and adjust strategy
- Consider breaking large prompts into cacheable sections

## Migration from Basic Caching

If you're using the existing basic caching:

```python
# Old way
model = Claude(
    cache_system_prompt=True,
    extended_cache_time=True
)

# New way (backward compatible)
model = Claude(
    enable_prompt_caching=True,  # Enhanced features
    cache_system_prompt=True,    # Still works
    cache_ttl="1h"              # Cleaner TTL setting
)
```

## Examples

See the comprehensive examples in:

- `cookbook/models/anthropic/prompt_caching_extended.py`
- Test cases in `tests/unit/tools/test_claude_prompt_caching.py`

## Support

For questions or issues with prompt caching:

1. Check the [Anthropic Prompt Caching Documentation](https://docs.anthropic.com/en/api/prompt-caching)
2. Review the test cases for implementation examples
3. Monitor usage metrics to optimize your caching strategy
