from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import Workflow
from agno.workflow.types import StepInput, StepOutput

# Create agents with more specific validation criteria
data_validator = Agent(
    name="Data Validator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a data validator. Analyze the provided data and determine if it's valid.",
        "For data to be VALID, it must meet these criteria:",
        "- user_count: Must be a positive number (> 0)",
        "- revenue: Must be a positive number (> 0)",
        "- date: Must be in a reasonable date format (YYYY-MM-DD)",
        "",
        "Return exactly 'VALID' if all criteria are met.",
        "Return exactly 'INVALID' if any criteria fail.",
        "Also briefly explain your reasoning.",
    ],
)

data_processor = Agent(
    name="Data Processor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Process and transform the validated data.",
)

report_generator = Agent(
    name="Report Generator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Generate a final report from processed data.",
)


def early_exit_validator(step_input: StepInput) -> StepOutput:
    """
    Custom function that checks data quality and stops workflow early if invalid
    """
    # Get the validation result from previous step
    validation_result = step_input.previous_step_content or ""

    if "INVALID" in validation_result.upper():
        return StepOutput(
            content="❌ Data validation failed. Workflow stopped early to prevent processing invalid data.",
            stop=True,  # Stop the entire workflow here
        )
    else:
        return StepOutput(
            content="✅ Data validation passed. Continuing with processing...",
            stop=False,  # Continue normally
        )


# Create workflow with conditional early termination
workflow = Workflow(
    name="Data Processing with Early Exit",
    description="Process data but stop early if validation fails",
    steps=[
        data_validator,  # Step 1: Validate data
        early_exit_validator,  # Step 2: Check validation and possibly stop early
        data_processor,  # Step 3: Process data (only if validation passed)
        report_generator,  # Step 4: Generate report (only if processing completed)
    ],
)

if __name__ == "__main__":
    print("\n=== Testing with INVALID data ===")
    workflow.print_response(
        input="Process this data: {'user_count': -50, 'revenue': 'invalid_amount', 'date': 'bad_date'}"
    )

    print("=== Testing with VALID data ===")
    workflow.print_response(
        input="Process this data: {'user_count': 1000, 'revenue': 50000, 'date': '2024-01-15'}"
    )
