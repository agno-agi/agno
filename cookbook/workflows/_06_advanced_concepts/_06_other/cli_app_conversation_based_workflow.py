from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ==============================================================================
# 1. CUSTOMER SUPPORT WORKFLOW
# ==============================================================================

def create_customer_support_workflow():
    """Multi-step customer support with escalation and context retention"""
    
    intake_agent = Agent(
        name="Support Intake Specialist",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a friendly customer support intake specialist.",
            "Gather initial problem details, customer info, and urgency level.",
            "Ask clarifying questions to understand the issue completely.",
            "Classify issues as: technical, billing, account, or general inquiry.",
            "Be empathetic and professional."
        ],
    )

    technical_specialist = Agent(
        name="Technical Support Specialist", 
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a technical support expert with deep product knowledge.",
            "Review the full conversation history to understand the customer's issue.",
            "Reference what the intake specialist learned to avoid repeating questions.",
            "Provide step-by-step troubleshooting or technical solutions.",
            "If you can't solve it, escalate with detailed context."
        ],
    )

    resolution_manager = Agent(
        name="Resolution Manager",
        model=OpenAIChat(id="gpt-4o"), 
        instructions=[
            "You are a customer success manager who ensures resolution.",
            "Review the entire support conversation to understand what happened.",
            "Provide final resolution, follow-up steps, and ensure customer satisfaction.",
            "Reference specific details from earlier in the conversation.",
            "Be solution-oriented and customer-focused."
        ],
    )

    return Workflow(
        name="Customer Support Pipeline",
        description="Multi-agent customer support with conversation continuity",
        db=SqliteDb(db_file="tmp/support_workflow.db"),
        steps=[
            Step(name="Support Intake", agent=intake_agent),
            Step(name="Technical Resolution", agent=technical_specialist), 
            Step(name="Final Resolution", agent=resolution_manager),
        ],
        add_history_to_context_for_steps=True,
    )


# ==============================================================================
# 2. MEDICAL CONSULTATION WORKFLOW  
# ==============================================================================

def create_medical_consultation_workflow():
    """Medical consultation with symptom analysis and specialist referral"""
    
    triage_nurse = Agent(
        name="Triage Nurse",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a professional triage nurse conducting initial assessment.",
            "Gather symptoms, medical history, and current medications.",
            "Ask about pain levels, duration, and severity.",
            "Document everything clearly for the consulting physician.",
            "Be thorough but compassionate."
        ],
    )

    consulting_physician = Agent(
        name="Consulting Physician",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are an experienced physician reviewing the patient case.",
            "Review all information gathered by the triage nurse.",
            "Build on the conversation - don't repeat questions already asked.",
            "Provide differential diagnosis and recommend next steps.",
            "Explain medical reasoning in patient-friendly terms."
        ],
    )

    care_coordinator = Agent(
        name="Care Coordinator", 
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You coordinate follow-up care based on the full consultation.",
            "Reference specific details from the nurse assessment and physician recommendations.",
            "Provide clear next steps, appointment scheduling, and care instructions.",
            "Ensure continuity of care with detailed documentation."
        ],
    )

    return Workflow(
        name="Medical Consultation",
        description="Comprehensive medical consultation with care coordination",
        db=SqliteDb(db_file="tmp/medical_workflow.db"),
        steps=[
            Step(name="Triage Assessment", agent=triage_nurse),
            Step(name="Physician Consultation", agent=consulting_physician),
            Step(name="Care Coordination", agent=care_coordinator),
        ],
        add_history_to_context_for_steps=True,
    )


# ==============================================================================
# 3. FINANCIAL ADVISORY WORKFLOW
# ==============================================================================

def create_financial_advisory_workflow():
    """Financial planning with risk assessment and personalized recommendations"""
    
    financial_intake = Agent(
        name="Financial Intake Specialist",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a financial planning intake specialist.",
            "Gather information about income, expenses, assets, and financial goals.",
            "Ask about risk tolerance, time horizon, and investment experience.",
            "Be professional and build trust through active listening."
        ],
    )

    risk_analyst = Agent(
        name="Risk Assessment Analyst",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a risk assessment specialist.",
            "Review all financial information shared in the conversation.",
            "Analyze risk tolerance based on the full discussion.",
            "Don't re-ask questions - build on what was already shared.",
            "Provide risk profile assessment and suitable investment categories."
        ],
    )

    investment_advisor = Agent(
        name="Investment Advisor",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a certified investment advisor providing personalized recommendations.",
            "Consider the complete conversation including goals, risk tolerance, and financial situation.",
            "Reference specific details discussed earlier to show continuity.",
            "Provide concrete, actionable investment recommendations.",
            "Explain how recommendations align with their stated goals and risk profile."
        ],
    )

    return Workflow(
        name="Financial Advisory Session",
        description="Comprehensive financial planning with personalized advice",
        db=SqliteDb(db_file="tmp/financial_workflow.db"),
        steps=[
            Step(name="Financial Assessment", agent=financial_intake),
            Step(name="Risk Analysis", agent=risk_analyst),
            Step(name="Investment Recommendations", agent=investment_advisor),
        ],
        add_history_to_context_for_steps=True,
    )


# ==============================================================================
# 4. EDUCATIONAL TUTORING WORKFLOW
# ==============================================================================

def create_tutoring_workflow():
    """Personalized tutoring with adaptive learning"""
    
    learning_assessor = Agent(
        name="Learning Assessment Specialist",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are an educational assessment specialist.",
            "Evaluate the student's current knowledge level and learning style.",
            "Ask about specific topics they're struggling with.",
            "Identify knowledge gaps and learning preferences.",
            "Be encouraging and supportive."
        ],
    )

    subject_tutor = Agent(
        name="Subject Matter Tutor",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are an expert tutor in the student's subject area.",
            "Build on the assessment discussion - don't repeat questions.",
            "Teach using methods that match the student's identified learning style.",
            "Reference specific gaps and challenges mentioned earlier.",
            "Provide clear explanations and check for understanding."
        ],
    )

    progress_coach = Agent(
        name="Learning Progress Coach",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a learning coach focused on student success.",
            "Review the entire tutoring session for context.",
            "Provide study strategies based on what was discussed.",
            "Reference specific learning challenges and successes from the conversation.",
            "Create actionable next steps and encourage continued learning."
        ],
    )

    return Workflow(
        name="Personalized Tutoring Session",
        description="Adaptive educational support with learning continuity",
        db=SqliteDb(db_file="tmp/tutoring_workflow.db"),
        steps=[
            Step(name="Learning Assessment", agent=learning_assessor),
            Step(name="Subject Tutoring", agent=subject_tutor),
            Step(name="Progress Planning", agent=progress_coach),
        ],
        add_history_to_context_for_steps=True,
    )


# ==============================================================================
# 5. CREATIVE WRITING WORKSHOP
# ==============================================================================

def create_writing_workshop_workflow():
    """Creative writing development with feedback and revision"""
    
    idea_facilitator = Agent(
        name="Creative Idea Facilitator",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You help writers develop and refine creative ideas.",
            "Explore themes, characters, settings, and plot possibilities.",
            "Ask thought-provoking questions to deepen the concept.",
            "Be supportive and encouraging of creative expression."
        ],
    )

    writing_coach = Agent(
        name="Writing Development Coach",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are a writing coach who helps develop the ideas discussed earlier.",
            "Build on the creative concepts from the previous conversation.",
            "Help structure the writing and develop key elements.",
            "Reference specific ideas and themes mentioned by the writer.",
            "Provide concrete writing techniques and exercises."
        ],
    )

    editor_mentor = Agent(
        name="Editorial Mentor",
        model=OpenAIChat(id="gpt-4o"),
        instructions=[
            "You are an editorial mentor providing constructive feedback.",
            "Consider the full creative development process from the conversation.",
            "Provide feedback that builds on the established direction.",
            "Reference the writer's original vision and goals discussed earlier.",
            "Offer specific, actionable revision suggestions."
        ],
    )

    return Workflow(
        name="Creative Writing Workshop",
        description="Guided creative development with continuous feedback",
        db=SqliteDb(db_file="tmp/writing_workflow.db"),
        steps=[
            Step(name="Idea Development", agent=idea_facilitator),
            Step(name="Writing Coaching", agent=writing_coach),
            Step(name="Editorial Feedback", agent=editor_mentor),
        ],
        add_history_to_context_for_steps=True,
    )


# ==============================================================================
# DEMO FUNCTIONS USING CLI
# ==============================================================================

def demo_customer_support_cli():
    """Demo customer support workflow with CLI"""
    support_workflow = create_customer_support_workflow()
    
    print("🎧 Customer Support Demo - Type 'exit' to quit")
    print("Try: 'My account is locked and I can't access my billing information'")
    print("-" * 60)
    
    support_workflow.cli_app(
        session_id="support_demo",
        user="Customer",
        emoji="🆘",
        stream_intermediate_steps=True,
    )


def demo_medical_consultation_cli():
    """Demo medical consultation workflow with CLI"""
    medical_workflow = create_medical_consultation_workflow()
    
    print("🏥 Medical Consultation Demo - Type 'exit' to quit")  
    print("Try: 'I've been having chest pain and shortness of breath for 2 days'")
    print("-" * 60)
    
    medical_workflow.cli_app(
        session_id="medical_demo",
        user="Patient", 
        emoji="🩺",
        stream_intermediate_steps=True,
    )


def demo_financial_advisory_cli():
    """Demo financial advisory workflow with CLI"""
    financial_workflow = create_financial_advisory_workflow()
    
    print("💰 Financial Advisory Demo - Type 'exit' to quit")
    print("Try: 'I want to start investing for retirement, I'm 35 with $50k saved'")
    print("-" * 60)
    
    financial_workflow.cli_app(
        session_id="financial_demo",
        user="Client",
        emoji="💼", 
        stream_intermediate_steps=True,
    )


def demo_tutoring_cli():
    """Demo tutoring workflow with CLI"""
    tutoring_workflow = create_tutoring_workflow()
    
    print("📚 Tutoring Session Demo - Type 'exit' to quit")
    print("Try: 'I'm struggling with calculus derivatives and have a test next week'")
    print("-" * 60)
    
    tutoring_workflow.cli_app(
        session_id="tutoring_demo",
        user="Student",
        emoji="🎓",
        stream_intermediate_steps=True,
    )


def demo_writing_workshop_cli():
    """Demo writing workshop workflow with CLI"""
    writing_workflow = create_writing_workshop_workflow()
    
    print("✍️ Creative Writing Workshop Demo - Type 'exit' to quit")
    print("Try: 'I want to write a science fiction story about time travel'")
    print("-" * 60)
    
    writing_workflow.cli_app(
        session_id="writing_demo",
        user="Writer",
        emoji="📝",
        stream_intermediate_steps=True,
    )


if __name__ == "__main__":
    import sys
    
    demos = {
        "support": demo_customer_support_cli,
        "medical": demo_medical_consultation_cli,
        "financial": demo_financial_advisory_cli,
        "tutoring": demo_tutoring_cli,
        "writing": demo_writing_workshop_cli,
    }
    
    if len(sys.argv) > 1 and sys.argv[1] in demos:
        demos[sys.argv[1]]()
    else:
        print("🚀 Conversational Workflow Demos")
        print("Choose a demo to run:")
        print("")
        for key, func in demos.items():
            print(f"{key:<10} - {func.__doc__}")
        print("")
        print("Or run all demos interactively:")
        choice = input("Enter demo name (or 'all'): ").strip().lower()
        
        if choice == "all":
            for demo_func in demos.values():
                demo_func()
        elif choice in demos:
            demos[choice]()
        else:
            print("Invalid choice!")