# Tool Post-Hooks Do Not Execute When Tool Execution Fails

## Description

Tool post-hooks are not executed when a tool call fails with an exception. The post-hook is only called after successful execution, which prevents it from being used for cleanup, error logging, or error handling scenarios.

## Steps to Reproduce

1. Create a tool that raises an exception:
```python
from agno.tools import tool

post_hook_executed = []

def my_post_hook(fc):
    post_hook_executed.append(True)
    print(f"Post-hook called! Error: {fc.error}")

@tool(post_hook=my_post_hook)
def failing_tool(value: int) -> str:
    """A tool that always fails."""
    raise ValueError(f"Tool failed with value: {value}")
```

2. Execute the tool via an agent:
```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[failing_tool],
    show_tool_calls=True
)

agent.print_response("Call the failing_tool with value 42")
```

3. **Expected:** Post-hook executes and `post_hook_executed` contains one entry
4. **Actual:** Post-hook never executes and `post_hook_executed` remains empty

The tool execution fails with an exception, and the post-hook at [function.py:836](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/function.py#L836) is never reached because of the early return at [line 833](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/function.py#L833).

## Current Behavior

In the `FunctionCall` class ([function.py:776-840](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/function.py#L776-L840)), both `execute()` and `aexecute()` methods have the following execution flow:

```python
def execute(self) -> FunctionExecutionResult:
    # Pre-hook executes before try block
    self._handle_pre_hook()

    entrypoint_args = self._build_entrypoint_args()

    # Tool execution inside try/except
    try:
        # ... execute the tool ...
        self.result = result

    except AgentRunException as e:
        self.error = str(e)
        raise  # Re-raises, post-hook won't execute

    except Exception as e:
        self.error = str(e)
        return FunctionExecutionResult(status="failure", error=str(e))  # Early return - post-hook won't execute

    # Post-hook only executes if no exception occurred
    self._handle_post_hook()

    return FunctionExecutionResult(status="success", result=self.result)
```

**Problem:** When an exception occurs in the tool execution:
- `AgentRunException` is re-raised immediately (line 828/1023), bypassing post-hook
- Other exceptions return early (line 833/1028), bypassing post-hook
- Post-hook at line 836/1034 never executes

## Expected Behavior

Post-hooks should execute **regardless of success or failure**, similar to a `finally` block. This is already documented in the code:

```python
# From function.py:95-97
# Hook that runs after the function is executed, regardless of success/failure.
# If defined, can accept the FunctionCall instance as a parameter.
post_hook: Optional[Callable] = None
```

The comment explicitly states "**regardless of success/failure**", but the implementation doesn't match this specification.

## Use Cases That Are Broken

1. **Cleanup operations** - Post-hooks can't clean up resources when a tool fails
2. **Error logging** - Can't log tool failures in post-hooks
3. **Metrics/monitoring** - Can't track tool failure rates
4. **Retry logic** - The cookbook example at [`retry_tool_call_from_post_hook.py`](https://github.com/agno-agi/agno/blob/main/cookbook/tools/other/retry_tool_call_from_post_hook.py) demonstrates using post-hooks for retry logic, but this won't work if the tool itself throws an exception

## Related Code

- **Sync execution:** [function.py:776-840](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/function.py#L776-L840)
- **Async execution:** [function.py:964-1038](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/function.py#L964-L1038)
- **Documentation:** [function.py:95-97](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/function.py#L95-L97)

## Proposed Solution

Move the post-hook execution into a `finally` block to ensure it always runs:

```python
def execute(self) -> FunctionExecutionResult:
    self._handle_pre_hook()
    entrypoint_args = self._build_entrypoint_args()

    execution_result = None
    exception_to_raise = None

    try:
        # ... execute the tool ...
        self.result = result
        execution_result = FunctionExecutionResult(
            status="success",
            result=self.result,
            updated_session_state=updated_session_state
        )

    except AgentRunException as e:
        self.error = str(e)
        exception_to_raise = e  # Store to re-raise after post-hook

    except Exception as e:
        self.error = str(e)
        execution_result = FunctionExecutionResult(status="failure", error=str(e))

    finally:
        # Always execute post-hook, regardless of success/failure
        self._handle_post_hook()

    # Re-raise AgentRunException after post-hook has executed
    if exception_to_raise is not None:
        raise exception_to_raise

    return execution_result
```

The same pattern should be applied to `aexecute()` for async execution.

## Testing

Consider adding tests to verify post-hooks execute on tool failure:

```python
def test_post_hook_executes_on_tool_failure():
    """Test that post-hook executes even when tool execution fails."""
    post_hook_called = []

    def failing_tool() -> str:
        raise ValueError("Tool failed")

    def post_hook(fc: FunctionCall):
        post_hook_called.append(True)
        assert fc.error is not None  # Should have error set

    function = Function.from_callable(failing_tool)
    function.post_hook = post_hook
    function.process_entrypoint()

    fc = FunctionCall(function=function)
    result = fc.execute()

    assert result.status == "failure"
    assert len(post_hook_called) == 1  # Post-hook should have been called
```

## Questions

1. **Is the current behavior intentional?** Should post-hooks only run on success?
2. If post-hooks should run on failure, should they receive information about the error (via `FunctionCall.error` field)?
3. Should the same fix apply to both `execute()` and `aexecute()` methods?

## Impact

- **Breaking change:** Low - Most users probably expect post-hooks to run on failure (as documented)
- **Affected cookbook examples:** `retry_tool_call_from_post_hook.py` assumes post-hooks run on failure
- **Workaround:** Currently none - post-hooks simply cannot handle tool failures
