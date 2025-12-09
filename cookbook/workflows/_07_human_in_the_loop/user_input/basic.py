from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool
from agno.tools.function import UserInputField
from agno.utils import pprint
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


@tool(requires_user_input=True, user_input_fields=["to_address"])
def send_email(self, subject: str, body: str, to_address: str) -> str:
    """Send an email to the given address with the given subject and body.
    Args:
        subject (str): The subject of the email.
        body (str): The body of the email.
        to_address (str): The address to send the email to.
    """
    return f"Sent email to {to_address} with subject {subject} and body {body}"


# Step 1: Writer agent composes the email
writer_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="An agent that writes professional emails.",
    instructions="Write a clear and professional email based on the user's request.",
    db=SqliteDb(db_file="tmp/static_input_writer.db"),
)
write_email_step = Step(name="Writer Step", agent=writer_agent)

# Step 2: Email agent sends the email (requires user input for recipient)
email_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="An agent that sends emails.",
    instructions="Send the email using the provided content.",
    db=SqliteDb(db_file="tmp/static_input_sender.db"),
    tools=[send_email],
)
send_email_step = Step(name="Email Step", agent=email_agent)

# Define our Workflow
workflow = Workflow(
    name="Email Composition Workflow",
    description="A workflow that composes and sends emails",
    steps=[write_email_step, send_email_step],
)

run_output = workflow.run(
    input="Write and send a follow-up email thanking the interviewer for their time."
)

while run_output.is_paused:
    for requirement in run_output.active_requirements:
        if requirement.needs_user_input:
            input_schema: List[UserInputField] = requirement.user_input_schema  # type: ignore
            for field in input_schema:
                field_type = field.field_type
                field_description = field.description
                print(f"\nField: {field.name}")
                print(f"Description: {field_description}")
                print(f"Type: {field_type}")

                if field.value is None:
                    user_value = input(f"Please enter a value for {field.name}: ")
                else:
                    print(f"Value: {field.value}")
                    user_value = field.value

                field.value = user_value

    run_output = workflow.continue_run(
        run_id=run_output.run_id,
        requirements=run_output.requirements,
    )

pprint.pprint_run_response(run_output)
