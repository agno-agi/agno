from agno.playground import Playground, serve_playground_app
from reasoning_finance_team import finance_agent, reasoning_finance_team, web_agent

app = Playground(
    app_id="multi-agent-reasoning-app",
    name="Multi Agent Reasoning App",
    agents=[web_agent, finance_agent],
    teams=[reasoning_finance_team],
).get_app()

if __name__ == "__main__":
    serve_playground_app("playground:app", port=7777)
