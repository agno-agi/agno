from pathlib import Path
from typing import Any, Dict, List, Union

from agno.agent.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.text import TextKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.lancedb import LanceDb
from agno.workflow.v2.router import Router
from agno.workflow.v2.step import Step
from agno.workflow.v2.steps import Steps
from agno.workflow.v2.types import StepInput
from agno.workflow.v2.workflow import Workflow


# Create dummy knowledge base content
def create_dummy_knowledge():
    """Create dummy knowledge base files for HR policies"""
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

    return knowledge_dir


# Create knowledge base
knowledge_dir = create_dummy_knowledge()
hr_knowledge = TextKnowledgeBase(
    path=knowledge_dir,
    vector_db=LanceDb(
        table_name="hr_policies",
        uri="tmp/lancedb",
        embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
    ),
    num_documents=3,
)

# Load knowledge base
try:
    hr_knowledge.load(recreate=False)
except:
    hr_knowledge.load(recreate=True)

# Define agents
knowledge_search_agent = Agent(
    name="Knowledge Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""
You are a knowledge search agent. Search the knowledge base for relevant information.

If you find relevant information, provide it clearly and end with "KNOWLEDGE_FOUND".
If you can't find specific information, end with "KNOWLEDGE_NOT_FOUND".
""",
    knowledge=hr_knowledge,
    search_knowledge=True,
    tools=[DuckDuckGoTools()],
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

# Define the nested router choices (need to be defined before use)
knowledge_found_branch = Step(
    name="generate_success_response", agent=response_generator
)
knowledge_not_found_branch = Step(
    name="generate_not_found_response", agent=not_found_responder
)

# Define the predefined step sequences (choices)
# Branch 1: Need more info (single step)
need_more_info_branch = Step(name="request_more_info", agent=more_info_requester)

# Branch 2: Knowledge search with nested router (multiple steps)
knowledge_search_branch = Steps(
    name="knowledge_search_steps",
    steps=[
        Step(name="gather_knowledge", agent=knowledge_search_agent),
        Router(
            name="knowledge_result_router",
            selector=lambda step_input: (
                [knowledge_found_branch]
                if "KNOWLEDGE_FOUND" in (step_input.previous_step_content or "")
                else [knowledge_not_found_branch]
            ),
            choices=[knowledge_found_branch, knowledge_not_found_branch],
        ),
    ],
)


# Step functions for routers - Following the pattern from router_with_loop_steps.py
def check_information_completeness(step_input: StepInput) -> List[Union[Step, Steps]]:
    """
    Main Router (Step 1): Check if we have enough information to proceed
    Returns a LIST containing ONE of the predefined choices (following the Loop example pattern)
    """
    message = str(step_input.message or "").lower()

    # Define what constitutes "relevant information" with hardcoded keywords
    travel_complete_patterns = [
        ("first class", ["nyc", "sf"]),
        ("first class", ["nyc", "denver"]),
        ("first class", ["nyc", "boston"]),
        ("business class", ["nyc", "sf"]),
        ("business class", ["nyc", "denver"]),
        ("economy class", ["nyc", "boston"]),
    ]

    benefits_complete_patterns = [
        ("health insurance", ["coverage", "premium", "deductible"]),
        ("401k", ["match", "vesting", "retirement"]),
    ]

    # Check if message contains complete information
    has_complete_info = False

    # Check travel patterns
    for class_type, locations in travel_complete_patterns:
        if class_type in message and any(loc in message for loc in locations):
            has_complete_info = True
            print(f"✅ Complete travel info detected: {class_type} with specific route")
            break

    # Check benefits patterns
    if not has_complete_info:
        for benefit_type, details in benefits_complete_patterns:
            if benefit_type in message and any(detail in message for detail in details):
                has_complete_info = True
                print(f"✅ Complete benefits info detected: {benefit_type}")
                break

    # Check for general completeness indicators
    travel_keywords = ["travel", "flight", "first class", "business class", "economy"]
    benefits_keywords = ["benefits", "health", "insurance", "401k", "retirement"]
    location_keywords = ["nyc", "sf", "denver", "boston", "new york", "san francisco"]

    has_topic = any(kw in message for kw in travel_keywords + benefits_keywords)
    has_specifics = any(kw in message for kw in location_keywords) or any(
        kw in message for kw in ["coverage", "premium", "match", "vesting"]
    )

    if has_topic and has_specifics:
        has_complete_info = True
        print("✅ Complete information detected based on topic + specifics")

    if has_complete_info:
        print("🔍 Route 1: Proceeding to knowledge search branch")
        return [knowledge_search_branch]
    else:
        print("❓ Route 2: Need more information")
        return [need_more_info_branch]


def check_knowledge_results(step_input: StepInput) -> List[Step]:
    """
    Knowledge Router: Check if knowledge search found relevant information
    Returns a LIST containing ONE of the predefined choices
    """
    # Get the previous step content (from knowledge search)
    previous_content = step_input.previous_step_content or ""

    if "KNOWLEDGE_FOUND" in previous_content:
        print("✅ Knowledge found, generating successful response")
        return [knowledge_found_branch]
    else:
        print("❌ Knowledge not found, generating not found response")
        return [knowledge_not_found_branch]


# Create the multi-level router workflow
chat_workflow = Workflow(
    name="💬 HR Chat Assistant",
    description="Interactive HR assistant with intelligent routing and knowledge search",
    steps=[
        # Main Router (Step 1): Check information completeness
        Router(
            name="main_information_router",
            selector=check_information_completeness,
            choices=[
                need_more_info_branch,  # Branch 1: Need more info
                knowledge_search_branch,  # Branch 2: Knowledge search with nested router
            ],
            description="Main router that checks if we have enough information to proceed",
        )
    ],
    storage=SqliteStorage(
        db_file="tmp/chat_workflow.db", table_name="chat_workflow", mode="workflow_v2"
    ),
)

if __name__ == "__main__":
    chat_workflow.cli_app(user="You", emoji="💬", stream=False, markdown=True)
