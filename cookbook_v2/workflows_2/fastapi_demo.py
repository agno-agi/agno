from agno.agent import Agent
from agno.app.fastapi import FastAPIApp
from agno.models.openai.chat import OpenAIChat
from agno.utils.log import log_info
from agno.workflow.v2 import Workflow

agent_storage_file: str = "tmp/agents.db"

# Define agents
support_agent = Agent(
    name="Solution Developer",
    model=OpenAIChat(id="gpt-4o"),
    instructions="""
        You are a solution developer for customer support. Your job is to create clear,
        step-by-step solutions for customer issues.

        Based on research and knowledge base information, create:
        1. Clear problem diagnosis
        2. Step-by-step solution instructions
        3. Alternative approaches if the main solution fails
        4. Prevention tips for the future

        Make solutions customer-friendly with numbered steps and clear language.
        Include any relevant screenshots, links, or additional resources.
        """,
    markdown=True,
)
triage_agent = Agent(
    name="Ticket Classifier",
    model=OpenAIChat(id="gpt-4o"),
    instructions="""
            You are a customer support ticket classifier. Your job is to analyze customer queries and extract key information.

            For each customer query, provide:
            1. Category (billing, technical, account_access, product_info, bug_report, feature_request)
            2. Priority (low, medium, high, urgent)
            3. Key tags/keywords (extract 3-5 relevant terms)
            4. Brief summary of the issue

            Format your response as:
            Category: [category]
            Priority: [priority]
            Tags: [tag1, tag2, tag3]
            Summary: [brief summary]
            """,
    markdown=True,
)


def cache_solution(workflow: Workflow, query: str, solution: str):
    if "solutions" not in workflow.workflow_session_state:
        workflow.workflow_session_state["solutions"] = {}
    workflow.workflow_session_state["solutions"][query] = solution


def customer_support_execution(workflow: Workflow, query: str) -> str:
    cached_solution = workflow.workflow_session_state.get("solutions", {}).get(query)
    if cached_solution:
        log_info(f"Cache hit! Returning cached solution for query: {query}")
        return cached_solution

    log_info(f"No cached solution found for query: {query}")

    classification_response = triage_agent.run(query)
    classification = classification_response.content

    solution_context = f"""
    Customer Query: {query}

    Classification: {classification}

    Please provide a clear, step-by-step solution for this customer issue.
    Make sure to format it in a customer-friendly way with clear instructions.
    """

    solution_response = support_agent.run(solution_context)
    solution = solution_response.content

    cache_solution(workflow, query, solution)

    return solution


# Create the customer support workflow
customer_support_workflow = Workflow(
    workflow_id="customer-support-resolution-pipeline",
    name="Customer Support Resolution Pipeline",
    description="AI-powered customer support with intelligent caching",
    steps=customer_support_execution,
    workflow_session_state={},  # Initialize empty session state
)

fastapi_app = FastAPIApp(
    workflows=[customer_support_workflow],
    app_id="workflows-fastapi-app",
    name="Workflows FastAPI App",
)
app = fastapi_app.get_app(use_async=False)

if __name__ == "__main__":
    # Start the fastapi server
    fastapi_app.serve(app="fastapi_demo:app", reload=True)
