# Steering

Send a message to a run while it is still executing. `Agent.steer(run_id, input)`
(or `Team.steer`, and the async `asteer`) queues the input, and the run's model
loop appends it to the conversation as a user message before its next model
request. The user does not have to wait for the run to finish, cancel it, or
start a second run on the same session.

| Example | What it shows |
|---|---|
| [`01_steer_a_running_agent.py`](./01_steer_a_running_agent.py) | A follow-up sent while a tool is running reaches the next model request. |

```bash
.venvs/demo/bin/python cookbook/02_agents/23_steering/01_steer_a_running_agent.py
```

## When the input is used

| The input arrives | What happens | `steer()` returns |
|---|---|---|
| While tools are running | It joins after the tool results, before the next model request | `True` |
| While the model writes its final answer | The run does not finish: the model gets another request and answers it | `True` |
| After a `stop_after_tool_call` tool | The stop is overridden so the model can answer it | `True` |
| In a tool batch that pauses for a human | It is held and delivered when the run continues (`continue_run`) | `True` |
| While the run is paused for a human | Refused: answer the pause with `continue_run()` instead | `False` |
| Before the run reaches its model call, or after it finished | Refused: start a new run instead | `False` |

Accepted input is never dropped silently. The final check is atomic: either the
run takes the pending input and makes another request, or it closes its inbox,
so a message sent a moment too late gets `False` rather than being accepted and
never read.

A steered message stays in the run's transcript (`run_output.messages`) in the
position the model saw it. With `stream_events=True` each one also emits a
`RunSteered` (`TeamRunSteered`) event carrying the message id and content, so a
client can show the message as delivered.

## Across processes

Steering state is in memory by default, so the process that calls `steer()`
must be the one executing the run. To share it across processes, subclass
`BaseRunSteeringManager` and install it with
`agno.run.steering.set_steering_manager()`.
