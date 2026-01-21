"""🤝 Human-in-the-Loop: Allowing users to provide input externally

This example shows how to use the UserControlFlowTools to allow the agent to get user input dynamically.
If the agent doesn't have enough information to complete a task, it will use the toolkit to get the information it needs from the user.
"""

from typing import Any, Dict, List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import Toolkit
from agno.tools.function import UserInputField
from agno.tools.user_control_flow import UserControlFlowTools
from agno.utils import pprint


class EmailTools(Toolkit):
    def __init__(self, *args, **kwargs):
        super().__init__(
            name="EmailTools", tools=[self.send_email, self.get_emails], *args, **kwargs
        )

    def send_email(self, subject: str, body: str, to_address: str) -> str:
        """Send an email to the given address with the given subject and body.

        Args:
            subject (str): The subject of the email.
            body (str): The body of the email.
            to_address (str): The address to send the email to.
        """
        return f"Sent email to {to_address} with subject {subject} and body {body}"

    def get_emails(self, date_from: str, date_to: str) -> list[dict[str, str]]:
        """Get all emails between the given dates.

        Args:
            date_from (str): The start date (in YYYY-MM-DD format).
            date_to (str): The end date (in YYYY-MM-DD format).
        """
        return [
            {
                "subject": "Hello",
                "body": "Hello, world!",
                "to_address": "test@test.com",
                "date": date_from,
            },
            {
                "subject": "Random other email",
                "body": "This is a random other email",
                "to_address": "john@doe.com",
                "date": date_to,
            },
        ]


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[EmailTools(), UserControlFlowTools()],
    markdown=True,
    db=SqliteDb(db_file="tmp/agentic_user_input.db"),
)

run_response = agent.run("Send an email with the body 'What is the weather in Tokyo?'")

# We use a while loop to continue the running until the agent is satisfied with the user input
while run_response.is_paused:
    for requirement in run_response.active_requirements:
        if requirement.needs_user_input:
            input_schema: List[UserInputField] = requirement.user_input_schema  # type: ignore

            for field in input_schema:
                # Get user input for each field in the schema
                field_type = field.field_type  # type: ignore
                field_description = field.description  # type: ignore

                # Display field information to the user
                print(f"\nField: {field.name}")  # type: ignore
                print(f"Description: {field_description}")
                print(f"Type: {field_type}")

                # Get user input
                if field.value is None:  # type: ignore
                    user_value = input(f"Please enter a value for {field.name}: ")  # type: ignore
                else:
                    print(f"Value: {field.value}")  # type: ignore
                    user_value = field.value  # type: ignore

                # Update the field value
                field.value = user_value  # type: ignore

    run_response = agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    if not run_response.is_paused:
        pprint.pprint_run_response(run_response)
        break


run_response = agent.run("Get me all my emails")

while run_response.is_paused:
    for requirement in run_response.active_requirements:
        if requirement.needs_user_input:
            input_schema: Dict[str, Any] = requirement.user_input_schema  # type: ignore

            for field in input_schema:
                # Get user input for each field in the schema
                field_type = field.field_type  # type: ignore
                field_description = field.description  # type: ignore

                # Display field information to the user
                print(f"\nField: {field.name}")  # type: ignore
                print(f"Description: {field_description}")
                print(f"Type: {field_type}")

                # Get user input
                if field.value is None:  # type: ignore
                    user_value = input(f"Please enter a value for {field.name}: ")  # type: ignore
                else:
                    print(f"Value: {field.value}")  # type: ignore
                    user_value = field.value  # type: ignore

                # Update the field value
                field.value = user_value  # type: ignore

    run_response = agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )

    if not run_response.is_paused:
        pprint.pprint_run_response(run_response)
        break
