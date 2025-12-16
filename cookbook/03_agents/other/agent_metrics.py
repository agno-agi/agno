from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from agno.utils import pprint

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
    markdown=True,
    session_id="test-session-metrics",
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
)

# Get the run response directly from the non-streaming call
run_response = agent.run("What is the stock price of NVDA")
print("Tool execution completed successfully!")

# Print metrics per message
if run_response and run_response.messages:
    for message in run_response.messages:
        if message.role == "assistant":
            if message.content:
                print(
                    f"Message: {message.content[:100]}..."
                )  # Truncate for readability
            elif message.tool_calls:
                print(f"Tool calls: {len(message.tool_calls)} tool call(s)")
            print("---" * 5, "Message Metrics", "---" * 5)
            if message.metrics:
                pprint(message.metrics)
            else:
                print("No metrics available for this message")
            print("---" * 20)

# Print the run metrics
print("---" * 5, "Run Metrics", "---" * 5)
if run_response and run_response.metrics:
    pprint(run_response.metrics)
else:
    print("No run metrics available")

# Print the session metrics
print("---" * 5, "Session Metrics", "---" * 5)
try:
    session_metrics = agent.get_session_metrics()
    if session_metrics:
        pprint(session_metrics)
    else:
        print("No session metrics available")
except Exception as e:
    print(f"Error getting session metrics: {e}")
