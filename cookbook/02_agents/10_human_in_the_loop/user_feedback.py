"""
User Feedback (Structured Questions)
=====================================

Human-in-the-Loop: Presenting structured questions with predefined options.
Uses UserFeedbackTools to pause the agent and collect user selections.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.user_feedback import UserFeedbackTools
from agno.utils import pprint

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[UserFeedbackTools()],
    instructions=[
        "You are a helpful travel assistant.",
        "When the user asks you to plan a trip, use the ask_user tool to clarify their preferences.",
    ],
    markdown=True,
    db=SqliteDb(db_file="tmp/user_feedback.db"),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_response = agent.run("Help me plan a vacation")

    while run_response.is_paused:
        for requirement in run_response.active_requirements:
            if requirement.needs_user_feedback:
                feedback_schema = requirement.user_feedback_schema
                if not feedback_schema:
                    continue

                selections = {}
                for question in feedback_schema:
                    print(f"\n{question.header or 'Question'}: {question.question}")
                    if question.options:
                        for i, opt in enumerate(question.options, 1):
                            desc = f" - {opt.description}" if opt.description else ""
                            print(f"  {i}. {opt.label}{desc}")

                    if question.multi_select:
                        raw = input("Select options (comma-separated numbers): ")
                        indices = [
                            int(x.strip()) - 1
                            for x in raw.split(",")
                            if x.strip().isdigit()
                        ]
                        selected = [
                            question.options[i].label
                            for i in indices
                            if question.options and 0 <= i < len(question.options)
                        ]
                    else:
                        raw = input("Select an option (number): ")
                        idx = int(raw.strip()) - 1 if raw.strip().isdigit() else -1
                        selected = (
                            [question.options[idx].label]
                            if question.options and 0 <= idx < len(question.options)
                            else []
                        )

                    selections[question.question] = selected
                    print(f"  -> Selected: {selected}")

                requirement.provide_user_feedback(selections)

        run_response = agent.continue_run(
            run_id=run_response.run_id,
            requirements=run_response.requirements,
        )

        if not run_response.is_paused:
            pprint.pprint_run_response(run_response)
