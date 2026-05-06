# Team Human-in-the-Loop

Examples of human-in-the-loop (HITL) patterns with Teams, where member agents
require user confirmation before executing sensitive actions.

## Examples

### member_confirmation.py

Demonstrates Team member HITL with database persistence. A DevOps team
delegates deployment tasks to a member agent that requires user confirmation.

Key concepts:
- Member agent with `@tool(requires_confirmation=True)`
- Team propagates member's pause to `TeamRunPausedEvent`
- DB persistence: run can be continued after reload
- `session.get_run()` recovers member runs from TeamSession

```bash
.venvs/demo/bin/python cookbook/03_teams/18_human_in_the_loop/member_confirmation.py
```

## How It Works

```
1. User asks Team to deploy
2. Team delegates to DeployAgent  
3. DeployAgent's deploy_code tool requires confirmation
4. Team pauses with the member's requirement
5. User approves/rejects
6. Team continues the member's run
```

## Recovery Paths

When continuing a paused Team member HITL run, the framework tries:

1. `_member_run_response` - In-memory pointer (CLI/terminal)
2. `run_response.member_responses` - Requires `store_member_responses=True`
3. `session.get_run(member_run_id)` - Uses existing TeamSession data
4. Fallback - `member.continue_run(run_id=...)` (broken without DB context)

Path 3 was added to fix API/Slack flows where the in-memory pointer is lost
during JSON serialization, without requiring `store_member_responses=True`.
