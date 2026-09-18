"""
Claim Review + Draft Response Agent
Multi-agent system with Claim Ingestor, Rule Checker, and Draft Response agents.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini

# ============================================================================
# Storage (db) - For sessions, memories, and evals
# Memory is stored in the same database - see: https://docs.agno.com/concepts/memory/overview
# ============================================================================
memory_db = SqliteDb(
    id="claim-memory-db",
    db_file="storage/claim_memory.db",
    # Memories are stored in 'agno_memories' table by default
    # Sessions are stored in 'agno_sessions' table by default
)

# Create storage directories if they don't exist
Path("storage").mkdir(exist_ok=True)

# ============================================================================
# Claim Ingestor Agent
# Memory: Automatic memory management enabled
# Memories are automatically created and retrieved for each user
# ============================================================================
claim_ingestor_agent = Agent(
    id="claim-ingestor",
    name="Claim Ingestor",
    role="Extract relevant fields (claim amount, incident details, documents) from PDFs and structured forms",
    model=Gemini(id="gemini-2.0-flash"),
    db=memory_db,
    enable_user_memories=True,  # Automatic memory: extracts and stores user info
    add_memories_to_context=True,  # Automatically adds relevant memories to context
    instructions=[
        "Extract complete content and structured data from claim documents.",
        "REQUIRED OUTPUT (JSON only, no additional text):",
        "- full_content: Complete text from all claim documents (extract everything, no summarization)",
        "- claim_amount: Total claimed amount",
        "- policy_number: Policy identifier",
        "- claim_number: Claim reference (may be 'Claim Number', 'Invoice Number', 'Claim ID')",
        "- claimant_name: Name of claimant (may be 'Policyholder', 'Patient Name', 'Driver', 'Claimant')",
        "- vehicle_registration: Vehicle registration (for auto claims only, null for health claims)",
        "- incident_date: Date of incident (may be 'Date of Accident', 'Date of Admission', 'Incident Date')",
        "- documents_submitted: List of document types mentioned",
        "RULES:",
        "- Extract ALL text from documents into full_content - include everything, do not summarize.",
        "- Only extract information explicitly visible in documents - use null for missing fields.",
        "- Look for field name variations (e.g., 'Invoice Number' = claim_number).",
        "- Process all document types: PDFs, invoices, forms, text.",
    ],
    markdown=False,
)

# ============================================================================
# Rule Checker Agent
# Memory: Automatic memory management enabled
# Can remember policy patterns, common exclusions, and user preferences
# ============================================================================
rule_checker_agent = Agent(
    id="rule-checker",
    name="Rule Checker",
    role="Match extracted data against policy rules, exclusions, and thresholds (e.g. deductible not met, duplicate coverage)",
    model=Gemini(id="gemini-2.0-flash"),
    db=memory_db,
    enable_user_memories=True,  # Automatic memory: learns from past claim reviews
    add_memories_to_context=True,  # Automatically adds relevant memories to context
    instructions=[
        "Extract complete content and policy data from the provided policy document.",
        "REQUIRED OUTPUT (JSON only, no additional text):",
        "- full_content: Complete text from policy document (extract everything, no summarization)",
        "- policy_number: Policy identifier (e.g., 'AU-2024-98452', 'HI-2024-78523')",
        "- policy_document_file: Name/identifier of the policy document",
        "- deductible: Deductible amount per claim",
        "- coverage_limit: Maximum coverage (may be 'Sum Insured', 'Coverage Limit', 'IDV')",
        "- exclusions: List of exclusions from policy",
        "- policy_summary: Brief summary of policy terms and coverage",
        "- claim_eligible: true/false based on verification",
        "- final_payout: Calculated amount (Claim Amount - Deductible, if both confirmed)",
        "- decision_rationale: Explanation of decision",
        "RULES:",
        "- Extract ALL text from policy document into full_content - include everything, do not summarize.",
        "- Verify policy number from claim data matches policy number in document.",
        "- Only use information explicitly stated in document - use null for missing values.",
        "- Calculate final_payout only if both claim_amount and deductible are confirmed.",
        "- If no policy document provided, return error JSON with claim_eligible: false.",
    ],
    markdown=False,
)

# ============================================================================
# Draft Response Agent
# Memory: Automatic memory management enabled
# Can remember response formats, adjuster preferences, and common patterns
# ============================================================================
draft_response_agent = Agent(
    id="draft-response",
    name="Draft Response Agent",
    role="Write payout approval or denial response with a clear, regulation-aligned explanation",
    model=Gemini(id="gemini-2.0-flash"),
    db=memory_db,
    enable_user_memories=True,  # Automatic memory: learns response preferences
    add_memories_to_context=True,  # Automatically adds relevant memories to context
    instructions=[
        "Create a draft response using Claim data (from Claim Ingestor) and Policy data (from Rule Checker).",
        "REQUIRED RESPONSE STRUCTURE (markdown):",
        "1. ## Claim Decision: [Approval/Denial]",
        "2. **Policy Number: [from policy data]**",
        "3. ### Policy Summary",
        "4. ### Claim Details Table",
        "   | Field | Claim Value |",
        "   Include: Policy Number, Claim Number, Claimant Name, Claim Amount, Incident Date, Vehicle Registration (if applicable), Documents Submitted",
        "5. ### Policy Details Table",
        "   | Field | Policy Value |",
        "   Include: Policy Number, Deductible, Coverage Limit, Exclusions, Policy Summary",
        "6. ### Decision Rationale",
        "7. ### Payout Details (if approved)",
        "   Show: Final Payout Amount, Calculation (Claim Amount - Deductible)",
        "8. ### Assessment Details",
        "   Include: Claimant name, incident date, vehicle registration (if applicable), nature of damage/incident from claim documents, key policy terms relevant to the claim, exclusions checked, coverage verification details, policy number match verification",
        "RULES:",
        "- Only use values from provided data - show 'N/A' for null values.",
        "- Do not invent or modify any values.",
        "- Extract assessment details from the full_content fields in both Claim and Policy data.",
        "- Ensure markdown formatting renders properly.",
    ],
    markdown=True,
    )
