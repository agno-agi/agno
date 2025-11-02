# Fix Anthropic cumulative usage metrics inflation

## Summary

- Fix bug where Anthropic's cumulative token usage metrics were being accumulated instead of replaced during streaming with tool calls
- Add `_is_cumulative_usage` flag to Anthropic streaming responses to distinguish cumulative metrics from incremental metrics
- Update base model logic to replace (not accumulate) metrics when the cumulative flag is present
- Add comprehensive unit tests that verify the fix and ensure no regression for other providers (OpenAI, Gemini, etc.)

**Root Cause:** During tool calling, Anthropic returns cumulative usage totals across multiple streaming events (e.g., Event 1: 63k tokens, Event 2: 64k tokens including Event 1, Event 3: 65k tokens including Events 1+2). Agno was accumulating these values (63k + 64k + 65k = 192k) instead of using the final cumulative total (65k).

**Fix:** Mark Anthropic usage metrics as cumulative with `_is_cumulative_usage = True` flag, then check this flag in base model and use assignment (`=`) instead of accumulation (`+=`) for cumulative metrics.

## Type of change

- [x] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Improvement
- [ ] Model update
- [ ] Other:

---

## Checklist

- [x] Code complies with style guidelines
- [x] Self-review completed
- [x] Documentation updated (comments, docstrings)
- [ ] Examples and guides: Relevant cookbook examples have been included or updated (if applicable)
- [x] Tested in clean environment
- [x] Tests added/updated (if applicable)
- [x] Ran format/validation scripts (`./scripts/format.sh` and `./scripts/validate.sh`)

---

## Files Modified

1. **`libs/agno/agno/models/anthropic/claude.py` (lines 586-589)**
   - Added `_is_cumulative_usage = True` flag when parsing streaming usage metrics

2. **`libs/agno/agno/models/base.py` (lines 810-817)**
   - Modified `_populate_assistant_message` to check for cumulative usage flag
   - Use assignment (`=`) for cumulative metrics, accumulation (`+=`) for incremental metrics

3. **`libs/agno/tests/unit/models/test_anthropic_cumulative_usage.py` (new file)**
   - `test_anthropic_cumulative_usage_not_inflated`: Verifies Anthropic cumulative usage is replaced correctly
   - `test_non_cumulative_usage_still_accumulates`: Ensures OpenAI/Gemini behavior remains unchanged

---

## Test Results

```bash
$ python -m pytest libs/agno/tests/unit/models/ -v
======================== 19 passed, 1 warning in 2.89s =========================
```

All existing model tests pass, including:
- 7 AWS Bedrock streaming tests
- 4 OpenAI client persistence tests
- 4 OpenAI response ID handling tests
- 2 function call show result tests
- **2 new Anthropic cumulative usage tests** ✨

---

## Additional Notes

### Before Fix (Bug)
```
Event 1: 63,325 tokens → metrics = 63,325
Event 2: 64,197 tokens (cumulative) → metrics = 127,522 ❌ (accumulated)
Event 3: 64,911 tokens (cumulative) → metrics = 192,433 ❌ (inflated 3x!)
```

### After Fix (Correct)
```
Event 1: 63,325 tokens → metrics = 63,325
Event 2: 64,197 tokens (cumulative) → metrics = 64,197 ✅ (replaced)
Event 3: 64,911 tokens (cumulative) → metrics = 64,911 ✅ (correct)
```

### Impact
- **No breaking changes** - Only fixes bug for Anthropic
- **No impact on other providers** - OpenAI, Gemini, etc. continue to work as before
- **Fully backwards compatible** - Uses `getattr()` with default `False` for missing flag
- **Works for all Anthropic endpoints** - Native Anthropic, AWS Bedrock Claude, VertexAI Claude

### References
- Anthropic API Docs: https://docs.anthropic.com/en/api/messages
- Related to tool calling with streaming: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
