import pandas as pd
from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat
from agno.playground import Playground
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools

simple_agent = Agent(
    name="Simple Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions=["Always provide a short and concise answer."],
    storage=SqliteStorage(
        table_name="simple_agent_sessions", db_file="tmp/simple_agent.db"
    ),
    monitoring=True,
)

playground_app = Playground(
    agents=[simple_agent],
    name="Simple Playground",
    app_id="simple_playground_test",
    monitoring=True,
)

app = playground_app.get_app()

data = {
    "user_input": ["What is the capital of France?", "Who is the CEO of Google?"],
    "reference_contexts": [
        "Paris is the capital of France.",
        "Sundar Pichai is the CEO of Google.",
    ],
}
test_df = pd.DataFrame(data)


def run_evaluation():
    for _, row in test_df.iterrows():
        input_text = row["user_input"]
        expected_output = row["reference_contexts"]

        evaluation = AccuracyEval(
            model=OpenAIChat(id="gpt-4o"),
            agent=simple_agent,
            input=str(input_text),
            expected_output=str(expected_output),
            monitoring=True,
        )

        evaluation.run(print_results=True)
        print(f"Evaluación para '{input_text}' completada y guardada.")


if __name__ == "__main__":
    run_evaluation()
    playground_app.serve("p:app", reload=True)
