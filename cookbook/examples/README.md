# Agno Examples

Five small, complete agents to read, run, and adapt. Each is an independent uv
project with its own agent, demo, dependencies, and validation notes.

| Example | Useful job | Choose it when |
| --- | --- | --- |
| [Personal Agent](personal_agent) | Keep projects, tasks, and decisions in durable notes | You want a simple agent that picks up where you left off |
| [Second Brain](second_brain) | Learn preferences and facts about people and projects | You want learning across conversations alongside explicit notes |
| [Team Brain](team_brain) | Share attributed decisions and reasoning | Teammates need a common project record |
| [Research Agent](research_agent) | Investigate a focused question and save a cited brief | You need source-backed findings with uncertainty |
| [Support Agent](support_agent) | Answer from maintained docs and prepare local handoffs | Product questions need traceable answers and conversational follow-ups |

Start with Personal Agent to understand durable notes and session history. Second
Brain builds on that idea with learning stores and an entity graph. Team Brain,
Research Agent, and Support Agent solve distinct jobs.

Each directory's README has exact setup commands. Export credentials explicitly;
`.env.example` does not load itself. `demo.py` exercises that directory's agent;
`test_contracts.py` contains deterministic assertions. Research and Support also
have offline scripted fixture modes, clearly separate from live model runs.

The examples use SQLite for local persistence. The two brain MCP servers require
JWT verification; the other AgentOS starters are local services. Follow each
README's identity boundaries before adapting an example for multiple users.

[Validation results](VALIDATION.md) distinguish published dependencies, exact local
source, fixture tests, live-model checks, and local HTTP/MCP checks.
