"""
Agents for Multi-Agent B2B Pipeline Builder
Three sequential agents: Data Enricher, ICP Scorer, LinkedIn Message Generator
"""

import os

from dotenv import load_dotenv
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager
from agno.models.google import Gemini

from tools import enrich_organization, enrich_person, search_people

# Load environment variables from .env file
load_dotenv()

# Setup SQLite database for sessions and memory
sqlite_db_path = os.getenv("SQLITE_DB_PATH", "tmp/agno_sessions.db")
sqlite_dir = os.path.dirname(sqlite_db_path)
if sqlite_dir:
    os.makedirs(sqlite_dir, exist_ok=True)
db = SqliteDb(db_file=sqlite_db_path)

# Setup Memory Manager, to adjust how memories are created
memory_manager = MemoryManager(
    db=db,
    # Select the model used for memory creation and updates. If unset, the default model of the Agent is used.
    model=Gemini(id="gemini-2.0-flash", api_key=os.getenv("GOOGLE_API_KEY")),
)

# Data Enricher Agent
data_enricher = Agent(
    name="Data Enricher",
    model=Gemini(id="gemini-2.0-flash", api_key=os.getenv("GOOGLE_API_KEY")),
    tools=[search_people, enrich_person, enrich_organization],
    instructions=[
        "You are a data enrichment specialist.",
        "Your job is to fetch and enrich lead profiles using Apollo API tools.",
        "When given a search query like '5 sales directors in London':",
        "  1. Use search_people to find matching profiles",
        "  2. For each profile, use enrich_person to get complete contact details",
        "  3. Use enrich_organization to get firmographics (company size, location, revenue, tech stack)",
        "  4. Structure the enriched data clearly for the next agent",
        "Extract and organize: name, title, email, phone, company name, company size, location, revenue, tech stack.",
    ],
    db=db,
    memory_manager=memory_manager,
    enable_user_memories=True,
    add_history_to_context=True,
    markdown=True,
)

# ICP Fit Scorer Agent
icp_scorer = Agent(
    name="ICP Fit Scorer",
    model=Gemini(id="gemini-2.0-flash", api_key=os.getenv("GOOGLE_API_KEY")),
    instructions=[
        "You are an ICP (Ideal Customer Profile) scoring specialist.",
        "Your job is to score leads against ICP criteria and provide detailed rationale.",
        "",
        "ICP Criteria with Weights:",
        "  - Role Level (Weight: 35%): Director, VP, C-level are ideal",
        "  - Company Size (Weight: 30%): 50-500 employees is ideal",
        "  - Tech Stack Match (Weight: 25%): Match with our product integrations",
        "  - Location (Weight: 10%): Target markets preferred",
        "",
        "For each enriched lead:",
        "  1. Score 0-100 for each dimension: role fit, company size, tech match, location",
        "  2. Calculate weighted overall score: (role×0.35) + (size×0.30) + (tech×0.25) + (location×0.10)",
        "  3. Flag as 'Fit' (70+ overall) or 'Misfit' (<70 overall) with clear reasoning",
        "  4. Provide specific rationale for each dimension and weighted calculation",
        "Format your output with individual scores, weighted overall score, and clear rationale for each lead.",
    ],
    db=db,
    memory_manager=memory_manager,
    enable_user_memories=True,
    add_history_to_context=True,
    markdown=True,
)

# LinkedIn Message Generator Agent
linkedin_message_generator = Agent(
    name="LinkedIn Message Generator",
    model=Gemini(id="gemini-2.0-flash", api_key=os.getenv("GOOGLE_API_KEY")),
    instructions=[
        "You are a personalized LinkedIn message writer for B2B outreach.",
        "Your job is to create personalized LinkedIn messages for ALL leads (both Fit and Misfit).",
        "The Fit/Misfit flag is for prioritization, but all leads should receive messages.",
        "",
        "For each scored lead (whether Fit or Misfit):",
        "  1. Review the lead's profile: name, role, company, size, context, ICP score and fit status",
        "  2. Identify relevant pain points based on their role and company",
        "  3. Match pain points to our value proposition",
        "  4. Write a concise, personalized LinkedIn message (2-3 sentences)",
        "  5. Make it conversational, value-focused, and non-salesy",
        "",
        "Output Format: Create a markdown table with columns (in this order):",
        "  - Fit/Misfit: First column showing 'Fit' or 'Misfit' status",
        "  - Profile Name: Full name of the person",
        "  - Role: Job title",
        "  - Org: Company name",
        "  - Size: Company size",
        "  - LinkedIn URL: Clickable markdown link format [Profile Name](linkedin_url)",
        "  - Message: Ready-to-use LinkedIn message",
        "",
        "Example table format:",
        "| Fit/Misfit | Profile Name | Role | Org | Size | LinkedIn URL | Message |",
        "|------------|--------------|------|-----|------|--------------|---------|",
        "| Fit | John Doe | Sales Director | Acme Corp | 200 | [John Doe](https://linkedin.com/in/johndoe) | Hi John, I noticed... |",
        "",
        "Include ALL leads in the table, regardless of Fit/Misfit status.",
    ],
    db=db,
    memory_manager=memory_manager,
    enable_user_memories=True,
    add_history_to_context=True,
    markdown=True,
)

