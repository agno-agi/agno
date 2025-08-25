from pathlib import Path
from typing import Any, Dict, List, Union

from agno.agent.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.text import TextKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.vectordb.lancedb import LanceDb
from agno.workflow.v2.router import Router
from agno.workflow.v2.step import Step
from agno.workflow.v2.steps import Steps
from agno.workflow.v2.types import StepInput
from agno.workflow.v2.workflow import Workflow


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


# Helper tools for managing conversation state
def add_to_conversation_history(agent: Agent, role: str, message: str) -> str:
    """Add a message to conversation history in workflow session state"""
    print(f"🔧 [TOOL] add_to_conversation_history called with role='{role}'")
    print(
        f"🔧 [TOOL] Agent workflow_session_state before: {agent.workflow_session_state}"
    )

    if agent.workflow_session_state is None:
        agent.workflow_session_state = {}

    if "conversation_history" not in agent.workflow_session_state:
        agent.workflow_session_state["conversation_history"] = []

    agent.workflow_session_state["conversation_history"].append(
        {"role": role, "message": message}
    )

    print(
        f"🔧 [TOOL] Agent workflow_session_state after: {agent.workflow_session_state}"
    )
    return f"Added {role} message to conversation history"


def get_conversation_context(agent: Agent) -> str:
    """Get conversation context from workflow session state"""
    print(f"🔧 [TOOL] get_conversation_context called")
    print(f"🔧 [TOOL] Agent workflow_session_state: {agent.workflow_session_state}")

    if (
        agent.workflow_session_state is None
        or "conversation_history" not in agent.workflow_session_state
    ):
        return "No conversation history available"

    history = agent.workflow_session_state["conversation_history"]
    if not history:
        return "No conversation history available"

    # Return last 5 messages for context
    recent_history = history[-5:]
    context = "Recent conversation:\n"
    for msg in recent_history:
        context += f"{msg['role']}: {msg['message']}\n"

    print(f"🔧 [TOOL] Returning context: {context[:100]}...")
    return context


def set_classification_result(
    agent: Agent, topic: str, status: str, confidence: str = "high"
) -> str:
    """Set classification result in workflow session state"""
    print(
        f"🔧 [TOOL] set_classification_result called with topic='{topic}', status='{status}', confidence='{confidence}'"
    )
    print(
        f"🔧 [TOOL] Agent workflow_session_state before: {agent.workflow_session_state}"
    )

    if agent.workflow_session_state is None:
        agent.workflow_session_state = {}

    agent.workflow_session_state["classification"] = {
        "topic": topic,
        "info_status": status,
        "confidence": confidence,
    }

    print(
        f"🔧 [TOOL] Agent workflow_session_state after: {agent.workflow_session_state}"
    )
    return f"Set classification - Topic: {topic}, Status: {status}, Confidence: {confidence}"


def get_classification_result(agent: Agent) -> str:
    """Get classification result from workflow session state"""
    print(f"🔧 [TOOL] get_classification_result called")
    print(f"🔧 [TOOL] Agent workflow_session_state: {agent.workflow_session_state}")

    if (
        agent.workflow_session_state is None
        or "classification" not in agent.workflow_session_state
    ):
        return "No classification available"

    classification = agent.workflow_session_state["classification"]
    result = f"Topic: {classification.get('topic', 'unknown')}, Status: {classification.get('info_status', 'unknown')}, Confidence: {classification.get('confidence', 'unknown')}"
    print(f"🔧 [TOOL] Returning: {result}")
    return result


# Create agents
intake_analysis_agent = Agent(
    name="Intake Analysis Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        add_to_conversation_history,
        get_conversation_context,
        set_classification_result,
    ],
    instructions="""
    You are an intake analysis specialist for HR queries. Your job is to:
    
    1. Add the user's message to conversation history as "user"
    2. Get conversation context to understand the full discussion
    3. Analyze the query to determine topic and completeness
    4. Set the classification result in session state
    5. Provide a structured response for routing
    
    Topics: travel_policy, benefits, paystubs, other
    Status: 
    - "COMPLETE" if you have enough information to search knowledge base
    - "INCOMPLETE" if you need more details from the user
    
    For travel policy: Need departure, destination, and context
    For benefits: Need specific benefit type and question
    For paystubs: Need specific payroll question
    
    Always follow this sequence:
    1. add_to_conversation_history (role="user", message=user_input)
    2. get_conversation_context
    3. set_classification_result (topic, status, confidence)
    4. Respond with EXACTLY this format: "CLASSIFICATION: [TOPIC] | STATUS: [COMPLETE/INCOMPLETE] | ANALYSIS: [your analysis]"
    
    Example: "CLASSIFICATION: travel_policy | STATUS: COMPLETE | ANALYSIS: User wants to know about first class travel from NYC to SF. I have enough information to search our policies."
    """,
)

information_gatherer_agent = Agent(
    name="Information Gatherer",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        get_conversation_context,
        get_classification_result,
        add_to_conversation_history,
    ],
    instructions="""
    You are an information gathering specialist. Your job is to:
    1. Get the current conversation context and classification
    2. Ask ONE specific follow-up question to get missing information
    3. Add your response to conversation history
    
    Always:
    1. get_conversation_context first
    2. get_classification_result to understand what's missing
    3. Ask ONE clear, specific question
    4. add_to_conversation_history (role="assistant", message=your_response)
    """,
)

knowledge_search_agent = Agent(
    name="Knowledge Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=hr_knowledge,
    search_knowledge=True,
    tools=[get_conversation_context, get_classification_result],
    instructions="""
    You are a knowledge search specialist. Your job is to:
    1. Get the conversation context and classification
    2. Search the HR knowledge base for relevant information
    3. Return whether knowledge was found or not
    
    If you find relevant information, respond with: "KNOWLEDGE_FOUND: [brief summary]"
    If you cannot find relevant information, respond with: "KNOWLEDGE_NOT_FOUND"
    """,
)

response_generator_agent = Agent(
    name="Response Generator",
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=hr_knowledge,
    tools=[get_conversation_context, add_to_conversation_history],
    instructions="""
    You are an HR assistant that provides final responses to employee questions.
    
    Your job is to:
    1. Get the full conversation context
    2. Use the available knowledge to provide a helpful, accurate answer
    3. Add your response to conversation history
    
    Always:
    1. get_conversation_context first
    2. Provide a professional, friendly response
    3. Cite relevant policies when applicable
    4. add_to_conversation_history (role="assistant", message=your_response)
    """,
)


def route_based_on_classification(step_input: StepInput) -> List[Step]:
    """
    Router function that routes based on the classification result from the intake step.
    """
    print(f"\n🔀 [ROUTER] route_based_on_classification called")
    print(
        f"🔀 [ROUTER] step_input.previous_step_content: {step_input.previous_step_content}"
    )

    # Access workflow session state directly
    workflow_session_state = hr_chat_workflow.workflow_session_state
    print(f"🔀 [ROUTER] workflow_session_state: {workflow_session_state}")

    classification = workflow_session_state.get("classification", {})
    info_status = classification.get("info_status", "unknown")
    topic = classification.get("topic", "unknown")

    print(
        f"🔀 [ROUTER] Classification from session state - Topic: {topic}, Status: {info_status}"
    )

    # Route based on classification status
    if info_status == "COMPLETE":
        print(f"✅ Complete information for {topic} - proceeding to knowledge search")
        return [knowledge_search_branch]
    elif info_status == "INCOMPLETE":
        print(f"❓ Incomplete information for {topic} - gathering more details")
        return [information_gathering_step]
    else:
        print("❓ Classification unclear - gathering more information")
        return [information_gathering_step]


def check_knowledge_results(step_input: StepInput) -> List[Step]:
    """
    Router function that determines next step based on knowledge search results.
    """
    print(f"\n🔀 [ROUTER] check_knowledge_results called")
    print(
        f"🔀 [ROUTER] step_input.previous_step_content: {step_input.previous_step_content}"
    )

    search_result = step_input.previous_step_content or step_input.message or ""

    if "KNOWLEDGE_FOUND" in str(search_result):
        print("📚 Knowledge found - generating response")
        return [response_generation_step]
    else:
        print("❌ Knowledge not found - generating sorry response")
        return [no_knowledge_response_step]


# Define workflow steps
intake_analysis_step = Step(
    name="intake_analysis",
    description="Analyze user query and classify topic and completeness",
    agent=intake_analysis_agent,
)

information_gathering_step = Step(
    name="gather_information",
    description="Gather additional information from user",
    agent=information_gatherer_agent,
)

knowledge_search_step = Step(
    name="search_knowledge",
    description="Search knowledge base for relevant information",
    agent=knowledge_search_agent,
)

knowledge_results_router = Router(
    name="knowledge_results_router",
    description="Route based on knowledge search results",
    selector=check_knowledge_results,
    choices=[
        response_generation_step := Step(
            name="generate_response",
            description="Generate response with found knowledge",
            agent=response_generator_agent,
        ),
        no_knowledge_response_step := Step(
            name="no_knowledge_response",
            description="Generate response when no knowledge found",
            agent=response_generator_agent,
        ),
    ],
)

# Knowledge search branch
knowledge_search_branch = Steps(
    name="knowledge_search_branch",
    description="Search knowledge and route based on results",
    steps=[
        knowledge_search_step,
        knowledge_results_router,
    ],
)

# Main routing logic
main_router = Router(
    name="main_classification_router",
    description="Route based on intake analysis classification",
    selector=route_based_on_classification,
    choices=[
        information_gathering_step,
        knowledge_search_branch,
    ],
)

# Create workflow
hr_chat_workflow = Workflow(
    name="HR Chat Workflow",
    description="Conversational HR assistant with proper intake analysis",
    steps=[
        intake_analysis_step,  # Step 1: Classify and analyze
        main_router,  # Step 2: Route based on classification
    ],
    storage=SqliteStorage(
        db_file="tmp/chat_workflow.db", table_name="chat_workflow", mode="workflow_v2"
    ),
    workflow_session_state={},  # Initialize empty workflow session state
)

if __name__ == "__main__":
    hr_chat_workflow.cli_app(user="You", emoji="💬", stream=False, markdown=True)
