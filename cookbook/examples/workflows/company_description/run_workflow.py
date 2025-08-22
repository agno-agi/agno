import markdown
import resend
from agents import (
    SupplierProfile,
    competitor_agent,
    crawl_agent,
    search_agent,
    wikipedia_agent,
)
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.utils.log import log_error, log_info
from agno.workflow import Parallel, Step, Workflow
from agno.workflow.types import StepInput, StepOutput
from prompts import SUPPLIER_PROFILE_DICT, SUPPLIER_PROFILE_INSTRUCTIONS_GENERAL

crawler_step = Step(
    name="Crawler",
    agent=crawl_agent,
    description="Crawl the supplier homepage for the supplier profile url",
)

search_step = Step(
    name="Search",
    agent=search_agent,
    description="Search for the supplier profile for the supplier name",
)

wikipedia_step = Step(
    name="Wikipedia",
    agent=wikipedia_agent,
    description="Search Wikipedia for the supplier profile for the supplier name",
)

competitor_step = Step(
    name="Competitor",
    agent=competitor_agent,
    description="Find competitors of the supplier name",
)


def generate_supplier_profile(step_input: StepInput) -> StepOutput:
    supplier_profile: SupplierProfile = step_input.input

    supplier_name: str = supplier_profile.supplier_name
    supplier_homepage_url: str = supplier_profile.supplier_homepage_url

    crawler_data: str = step_input.get_step_content("Gathering Information")["Crawler"]
    search_data: str = step_input.get_step_content("Gathering Information")["Search"]
    wikipedia_data: str = step_input.get_step_content("Gathering Information")[
        "Wikipedia"
    ]
    competitor_data: str = step_input.get_step_content("Gathering Information")[
        "Competitor"
    ]

    log_info(f"Crawler data: {crawler_data}")
    log_info(f"Search data: {search_data}")
    log_info(f"Wikipedia data: {wikipedia_data}")
    log_info(f"Competitor data: {competitor_data}")

    supplier_profile_prompt: str = f"Generate the supplier profile for the supplier name {supplier_name} and the supplier homepage url is {supplier_homepage_url}. The supplier homepage is {crawler_data} and the search results are {search_data} and the wikipedia results are {wikipedia_data} and the competitor results are {competitor_data}"

    supplier_profile_response: str = ""
    html_content: str = ""
    for key, value in SUPPLIER_PROFILE_DICT.items():
        agent = Agent(
            model=OpenAIChat(id="o3-mini"),
            instructions="Instructions: "
            + SUPPLIER_PROFILE_INSTRUCTIONS_GENERAL
            + "Format to adhere to: "
            + value,
        )
        response: RunOutput = agent.run(
            "Write the response in markdown format for the title: "
            + key
            + " using the following information: "
            + supplier_profile_prompt
        )
        if response.content:
            html_content += markdown.markdown(response.content)
            supplier_profile_response += response.content

    log_info(f"Generated supplier profile for {html_content}")

    return StepOutput(
        content=html_content,
        success=True,
    )


generate_supplier_profile_step = Step(
    name="Generate Supplier Profile",
    executor=generate_supplier_profile,
    description="Generate the supplier profile for the supplier name",
)


def send_email(step_input: StepInput):
    supplier_profile: SupplierProfile = step_input.input
    supplier_name: str = supplier_profile.supplier_name
    user_email: str = supplier_profile.user_email

    html_content: str = step_input.get_step_content("Generate Supplier Profile")

    try:
        resend.Emails.send(
            {
                "from": "support@agno.com",
                "to": user_email,
                "subject": f"Supplier Profile for {supplier_name}",
                "html": html_content,
            }
        )
    except Exception as e:
        log_error(f"Error sending email: {e}")

    return StepOutput(
        content="Email sent successfully",
        success=True,
    )


send_email_step = Step(
    name="Send Email",
    executor=send_email,
    description="Send the email to the user",
)

company_description_workflow = Workflow(
    name="Company Description Workflow",
    description="A workflow to generate a company description for a supplier",
    steps=[
        Parallel(
            crawler_step,
            search_step,
            wikipedia_step,
            competitor_step,
            name="Gathering Information",
        ),
        generate_supplier_profile_step,
        send_email_step,
    ],
)

if __name__ == "__main__":
    supplier_profile_request = SupplierProfile(
        supplier_name="Agno",
        supplier_homepage_url="https://www.agno.com",
        user_email="yash@agno.com",
    )
    company_description_workflow.print_response(
        input=supplier_profile_request,
    )
