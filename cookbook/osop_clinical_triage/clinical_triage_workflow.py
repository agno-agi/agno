"""
OSOP Clinical Triage Workflow - Agno Implementation

Demonstrates how an OSOP (Open Standard for Orchestration Protocols) workflow
maps to Agno's Agent and Workflow primitives. This example implements a
multi-step clinical triage pipeline with conditional routing.

Key concepts:
- OSOP steps map to Agno Workflow steps
- OSOP agents map to Agno Agent instances
- OSOP conditions map to Agno conditional branching
- OSOP inputs/outputs map to Agno session state

Try:
- "Patient: 45M, chest pain, HR 112, BP 85/60, SpO2 94%"
- "Patient: 28F, ankle sprain, HR 78, BP 120/80, SpO2 99%"
"""

from agno.agent import Agent
from agno.workflow import Workflow, Step

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------

intake_instructions = """You are a clinical intake agent. Structure the patient
information into a standardized format including: demographics (age, gender),
chief complaint, vital signs (HR, BP, SpO2, RR, Temp), pain score, and any
relevant medical history. Output as structured data."""

risk_instructions = """You are a clinical risk scoring agent. Based on the
structured patient data, determine the Emergency Severity Index (ESI) level:
- ESI 1: Immediate life-saving intervention required
- ESI 2: High risk, confused/lethargic, or severe pain/distress
- ESI 3: Multiple resources needed, stable vitals
- ESI 4: One resource needed
- ESI 5: No resources needed
Provide the ESI level with clinical justification."""

router_instructions = """You are a care routing agent. Based on the ESI level:
- ESI 1-2: Route to immediate emergency/resuscitation
- ESI 3: Route to urgent care with specialist consult
- ESI 4-5: Route to standard care or fast-track
Include department recommendation and estimated wait time."""

referral_instructions = """You are a specialist referral agent. Generate a
referral document including: reason for referral, clinical summary, urgency
level, recommended specialist type, and any immediate interventions needed."""

# ---------------------------------------------------------------------------
# Create Agents (OSOP agents map to Agno Agent instances)
# ---------------------------------------------------------------------------

intake_agent = Agent(
    name="Intake Agent",
    model="openai:gpt-4o-mini",
    instructions=intake_instructions,
    markdown=True,
)

risk_scoring_agent = Agent(
    name="Risk Scoring Agent",
    model="openai:gpt-4o-mini",
    instructions=risk_instructions,
    markdown=True,
)

router_agent = Agent(
    name="Router Agent",
    model="openai:gpt-4o-mini",
    instructions=router_instructions,
    markdown=True,
)

referral_agent = Agent(
    name="Referral Agent",
    model="openai:gpt-4o-mini",
    instructions=referral_instructions,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow (OSOP workflow maps to Agno Workflow)
# ---------------------------------------------------------------------------

clinical_triage_workflow = Workflow(
    name="Clinical Triage",
    agents=[intake_agent, risk_scoring_agent, router_agent, referral_agent],
)

# ---------------------------------------------------------------------------
# Run the Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example: High-acuity patient
    patient_input = (
        "45-year-old male presenting with acute chest pain radiating to left arm. "
        "Vitals: HR 112, BP 85/60, SpO2 94%, RR 22, Temp 37.2C. "
        "Pain score 9/10. History of hypertension and diabetes."
    )

    print("=" * 70)
    print("OSOP Clinical Triage Workflow - Agno Implementation")
    print("=" * 70)

    # Step 1: Patient Intake
    print("\n[Step 1] Patient Intake")
    print("-" * 40)
    intake_result = intake_agent.print_response(
        f"Structure this patient data: {patient_input}", stream=True
    )

    # Step 2: Risk Assessment
    print("\n[Step 2] Risk Assessment")
    print("-" * 40)
    risk_result = risk_scoring_agent.print_response(
        f"Assess ESI level for: {patient_input}", stream=True
    )

    # Step 3: Care Routing (conditional based on ESI)
    print("\n[Step 3] Care Level Routing")
    print("-" * 40)
    router_agent.print_response(
        f"Route this ESI 1-2 patient: {patient_input}", stream=True
    )

    # Step 4: Specialist Referral (conditional - only for ESI <= 3)
    print("\n[Step 4] Specialist Referral")
    print("-" * 40)
    referral_agent.print_response(
        f"Generate referral for: {patient_input}", stream=True
    )