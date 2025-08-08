from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agno.agent.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.text import TextKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.run.response import Message, RunResponse
from agno.storage.postgres import PostgresStorage
from agno.vectordb.lancedb import LanceDb
from agno.workflow.v2.router import Router
from agno.workflow.v2.step import Step
from agno.workflow.v2.steps import Steps
from agno.workflow.v2.types import StepInput, StepOutput
from agno.workflow.v2.workflow import Workflow
from pydantic import BaseModel, Field

# =============================================================================
# Models
# =============================================================================


class InformationValidation(BaseModel):
    enough_information: bool = Field(
        description="Whether the user's message contains enough information to proceed"
    )


class KnowledgeValidation(BaseModel):
    knowledge_found: bool = Field(
        description="Whether the agents message contains relevant information to proceed"
    )


# =============================================================================
# Knowledge Base Setup
# =============================================================================


def create_knowledge_base():
    """Create and setup the HR knowledge base with sample documents."""
    knowledge_dir = Path("tmp/hr_knowledge")
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    # Travel Policy Document
    travel_policy = """
    COMPANY TRAVEL POLICY
    
    Flight Class Guidelines:
    - Domestic flights under 3 hours: Economy class only
    - Domestic flights 3+ hours: Business class allowed
    - International flights: Business class allowed
    - First class: Requires VP approval for flights over 6 hours
    
    Destinations and Approvals:
    - NYC to SF (5.5 hours): Business class approved, First class needs VP approval
    - NYC to Denver (4 hours): Business class approved, First class needs VP approval
    - NYC to Boston (1.5 hours): Economy class only
    - International travel: Requires manager approval
    """

    # Benefits Policy Document
    benefits_policy = """
    EMPLOYEE BENEFITS GUIDE
    
    Health Insurance:
    - Coverage starts first day of employment
    - Premium sharing: Company 80%, Employee 20%
    - Annual deductible: $1,500 individual, $3,000 family
    
    Retirement:
    - 401(k) with 6% company match
    - Vesting: 100% after 3 years
    - Enrollment available after 90 days
    """

    # Write files
    (knowledge_dir / "travel_policy.txt").write_text(travel_policy)
    (knowledge_dir / "benefits_policy.txt").write_text(benefits_policy)

    # Create and load knowledge base
    hr_knowledge = TextKnowledgeBase(
        path=knowledge_dir,
        vector_db=LanceDb(
            table_name="hr_policies",
            uri="tmp/lancedb",
            embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
        ),
        num_documents=3,
    )

    try:
        hr_knowledge.load(recreate=False)
    except:
        hr_knowledge.load(recreate=True)

    return hr_knowledge


# =============================================================================
# Agents
# =============================================================================

# Initialize knowledge base
hr_knowledge = create_knowledge_base()

# Define all agents
knowledge_search_agent = Agent(
    name="Knowledge Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""
    You are a knowledge search agent. Search the knowledge base for relevant information.
    """,
    knowledge=hr_knowledge,
    search_knowledge=True,
)

response_generator = Agent(
    name="Response Generator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""
    Generate a helpful response based on the knowledge search results.
    Be clear, professional, and specific.
    """,
)

not_found_responder = Agent(
    name="Not Found Responder",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""
    Generate a polite response when information cannot be found.
    Suggest alternative ways the user might get help or rephrase their question.
    """,
)

more_info_requester = Agent(
    name="More Info Requester",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""
    Ask the user for more specific information to help answer their question.
    Be helpful and suggest what kind of details would be useful.
    """,
)

information_validator = Agent(
    name="Information Check",
    agent_id="information_check",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""
    Based on the user's message, check if we have enough information needed to proceed.
    Gather context from the message history to make a decision.

    Rules:
    - If the user's message contains detailed information regarding travel. Return enough_information = True
    - Example of a good message: "Can I travel from NYC to SF in first class?"
    - Example of a good message: "What is the reimbursement policy for travel expenses?"
    - Example of a bad message: "I want to travel to SF"
    - Example of a bad message: "I want to know about the benefits"

    Based on whether the user message contains enough information, we will proceed to the next step. But its important that the user 
    message contains enough information to proceed.
    """,
    response_model=InformationValidation,
    storage=PostgresStorage(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="information_validation",
    ),
    add_history_to_messages=True,
)

knowledge_validator = Agent(
    name="Knowledge Validation Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""
    Based on the user's message, check if we have enough information needed to proceed.
    """,
    response_model=KnowledgeValidation,
)

# =============================================================================
# Step Executors
# =============================================================================


def knowledge_found_executor(step_input: StepInput) -> StepOutput:
    """Executor for the knowledge found branch."""
    message = str(step_input.message or "").lower()

    # Get conversation history, potentially combine these functions into one
    # Make sure the knowledge agent has sufficient context to answer the users question.
    runs = chat_workflow.get_runs_from_session_state("information_check", num_runs=2)
    messages = chat_workflow.get_messages_from_runs(runs)

    # Run knowledge search.
    if messages:
        messages.append(Message(role="user", content=message))
        response = knowledge_search_agent.run(messages=messages)
    else:
        response = knowledge_search_agent.run(message=message)

    return StepOutput(content=response.content, success=True)


def information_validation_executor(step_input: StepInput) -> StepOutput:
    """Executor for the information validation step."""
    message = str(step_input.message or "").lower()

    response = information_validator.run(message=message)

    if isinstance(response.content, InformationValidation):
        return StepOutput(content=response.content, success=True)
    else:
        raise ValueError("Information validation failed")


# =============================================================================
# Steps
# =============================================================================

# Define workflow steps
information_validation_step = Step(
    name="information_validation", executor=information_validation_executor
)
need_more_info_step = Step(name="request_more_info", agent=more_info_requester)
success_response_step = Step(name="generate_success_response", agent=response_generator)
not_found_response_step = Step(
    name="generate_not_found_response", agent=not_found_responder
)


# =============================================================================
# Selectors
# =============================================================================


def validate_user_message(step_input: StepInput) -> List[Union[Step, Steps]]:
    """
    Main Router: Check if we have enough information to proceed.
    Returns appropriate branch based on information completeness.
    """
    message = str(step_input.message or "").lower()

    # Get conversation history, potentially combine these functions into one
    runs = chat_workflow.get_runs_from_session_state("information_check", num_runs=2)
    messages = chat_workflow.get_messages_from_runs(runs)

    # Run validation
    if messages:
        messages.append(Message(role="user", content=message))
        response = information_validator.run(messages=messages)
    else:
        response = information_validator.run(message=message)

    chat_workflow.add_run_to_session_state(response)

    # Route based on validation
    if not isinstance(response.content, InformationValidation):
        return [need_more_info_step]

    if response.content.enough_information:
        print("🔍 Route 1: Proceeding to knowledge search branch")
        return [knowledge_search_branch]
    else:
        print("❓ Route 2: Need more information")
        return [need_more_info_step]


def validate_knowledge_result(step_input: StepInput) -> List[Step]:
    """
    Knowledge Router: Check if knowledge search found relevant information.
    Returns appropriate response step.
    """
    # TODO: Get the original user input and add it to the input message to the knowledge validator
    message = str(step_input.message or "").lower()

    runs = chat_workflow.get_runs_from_session_state("knowledge_validation", num_runs=2)
    messages = chat_workflow.get_messages_from_runs(runs)

    response: RunResponse = knowledge_validator.run(message=message)

    if response.content.knowledge_found:
        print("🔍 Route 1: Knowledge found")
        return [success_response_step]
    else:
        print("❓ Route 2: No knowledge found")
        return [not_found_response_step]


# Define knowledge search branch with nested routing
knowledge_search_branch = Steps(
    name="knowledge_search_steps",
    steps=[
        Step(name="gather_knowledge", executor=knowledge_found_executor),
        Router(
            name="knowledge_result_router",
            selector=validate_knowledge_result,
            choices=[success_response_step, not_found_response_step],
        ),
    ],
)


# =============================================================================
# Workflow Definition
# =============================================================================

chat_workflow = Workflow(
    name="💬 HR Chat Assistant",
    description="Interactive HR assistant with intelligent routing and knowledge search",
    steps=[
        information_validation_step,
        Router(
            name="main_information_router",
            selector=lambda step_input: [need_more_info_step]
            if not step_input.previous_step_content.enough_information
            else [knowledge_search_branch],
            choices=[
                need_more_info_step,
                knowledge_search_branch,
            ],
            description="Main router that checks if we have enough information to proceed",
        ),
    ],
    storage=PostgresStorage(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="chat_workflow",
        mode="workflow_v2",
    ),
)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    chat_workflow.cli_app(user="You", emoji="💬", stream=False, markdown=True)
