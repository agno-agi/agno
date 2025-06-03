# [fix] Fix Anthropic prompt caching metrics propagation

## Summary

**Fixes a critical bug where Anthropic's prompt caching metrics were not propagating to Agent responses**, despite the raw Anthropic API working correctly. This minimal fix ensures cache performance metrics are properly captured and reported.

## Problem

Anthropic's prompt caching was working at the API level but metrics weren't flowing through agno's system:

```python
# Raw Anthropic API ✅
response.usage.cache_creation_input_tokens = 5501
response.usage.cache_read_input_tokens = 5501

# Agent response ❌
agent_response.metrics['cache_write_tokens'] = [0]
agent_response.metrics['cached_tokens'] = [0]
```

Users couldn't monitor cache performance or calculate cost savings.

## Solution

**Minimal fix in Claude model's response parser** - map Anthropic's field names to agno's standard names:

```python
# Added to parse_provider_response and parse_provider_response_delta
if hasattr(response.usage, "cache_creation_input_tokens"):
    usage_dict["cache_write_tokens"] = response.usage.cache_creation_input_tokens

if hasattr(response.usage, "cache_read_input_tokens"):
    usage_dict["cached_tokens"] = response.usage.cache_read_input_tokens
```

## Changes Made

### 🐛 **Bug Fix**

- **File**: `libs/agno/agno/models/anthropic/claude.py`
- **Change**: Map Anthropic cache fields to standard field names in response parser
- **Impact**: Cache metrics now flow correctly from API → Agent response

### ✅ **Tests Added**

- **File**: `libs/agno/tests/integration/models/anthropic/test_prompt_caching.py`
- **Added**: `test_usage_metrics_parsing` - validates field mapping
- **Updated**: `test_prompt_caching_with_agent_fixed` - handles both cache creation and hits
- **Improved**: Robust test coverage for real-world scenarios

### 📚 **Documentation**

- **File**: `docs/models/anthropic/prompt-caching.md`
- **Updated**: Professional, concise documentation matching agno's style
- **Added**: Quick start guide, monitoring examples, best practices
- **Improved**: Clear code examples and troubleshooting guide

## Verification

```bash
✅ test_usage_metrics_parsing PASSED
✅ test_prompt_caching_with_agent_fixed PASSED
```

**Before Fix:**

```python
agent_response.metrics['cache_write_tokens'] = [0]  # ❌ Wrong
```

**After Fix:**

```python
agent_response.metrics['cache_write_tokens'] = [5501]  # ✅ Correct
```

## Impact

- **🎯 Focused Solution**: Single responsibility - fix metrics propagation
- **📊 Monitoring Enabled**: Users can now track cache performance and savings
- **🔧 Zero Breaking Changes**: Maintains existing API compatibility
- **📈 Cost Tracking**: Enables proper monitoring of 90% cache cost savings

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [x] Documentation update
- [x] Test coverage improvement

---

This focused fix ensures Anthropic's excellent prompt caching functionality is properly reflected in agno's metrics system, enabling accurate monitoring and cost optimization.
