from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.models.response import UserInputField
from agno.tools import Toolkit
from agno.tools.user_control_flow import UserControlFlowTools
from agno.utils import pprint
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


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


# Define our Agents
email_agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    description="An agent that can send emails, obtaining the necessary information from the user.",
    db=SqliteDb(db_file="tmp/agentic_user_input.db"),
    tools=[EmailTools(), UserControlFlowTools()],
)
cover_letter_agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    description="An agent that can write cover letters.",
    instructions="Write the perfect cover letter for the given job description and user profile.",
    db=SqliteDb(db_file="tmp/email_writer.db"),
)

# Define the steps of our Workflow
cover_letter_step = Step(name="Cover Letter Step", agent=cover_letter_agent)
email_step = Step(name="Email Step", agent=email_agent)

# Define our Workflow
cover_letter_workflow = Workflow(
    name="Cover Letter Workflow",
    description="A workflow that can write cover letters and send them via email.",
    steps=[cover_letter_step, email_step],
)

run_output = cover_letter_workflow.run(
    "I'm an expert in Python, and want to apply for the software engineer position at Agno.",
)

# We use a while loop to continue the running until the agent is satisfied with the user input
while run_output.is_paused:
    for requirement in run_output.active_requirements:
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

    run_response = cover_letter_workflow.continue_run(
        run_id=run_output.run_id,
        requirements=run_output.requirements,
    )

    if not run_response.is_paused:
        pprint.pprint_run_response(run_response)
        break
