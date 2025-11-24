from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.guardrails import OpenAIModerationGuardrail, PromptInjectionGuardrail, PIIDetectionGuardrail
from agno.os import AgentOS
from agno.db.sqlite import SqliteDb

db = SqliteDb(
    session_table="guardrails_session",
    db_file="tmp/guardrails.db",
)

guardrail_agent = Agent(
    name="Chat Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    pre_hooks=[OpenAIModerationGuardrail() , PromptInjectionGuardrail() , PIIDetectionGuardrail()],
    instructions=[
        "You are a helpful assistant that can answer questions and help with tasks.",
        "Always answer in a friendly and helpful tone.",
        "Never be rude or offensive.",
    ],
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,

)

agent_os = AgentOS(
    id="guardrails_demo",
    agents=[guardrail_agent],
)   
app = agent_os.get_app()
if __name__ == "__main__":
    agent_os.serve(app="guardrails:app", port=7777, reload=True)
