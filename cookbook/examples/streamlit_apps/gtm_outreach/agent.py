import json
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.memory.v2 import Memory
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools


def create_company_finder_agent() -> Agent:
    exa_tools = ExaTools(category="company")
    memory = Memory()
    return Agent(
        model=OpenAIChat(id="gpt-5"),
        tools=[exa_tools],
        memory=memory,
        add_history_to_messages=True,
        num_history_responses=6,
        session_id="gtm_outreach_company_finder",
        show_tool_calls=True,
        instructions=[
            "You are CompanyFinderAgent. Use ExaTools to search the web for companies that match the targeting criteria.",
            "Return ONLY valid JSON with key 'companies' as a list; respect the requested limit provided in the user prompt.",
            "Each item must have: name, website, why_fit (1-2 lines).",
        ],
    )


def create_contact_finder_agent() -> Agent:
    exa_tools = ExaTools()
    memory = Memory()
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[exa_tools],
        memory=memory,
        add_history_to_messages=True,
        num_history_responses=6,
        session_id="gtm_outreach_contact_finder",
        show_tool_calls=True,
        instructions=[
            "You are ContactFinderAgent. Use ExaTools to collect as many relevant decision makers as possible per company...",
            "Return ONLY valid JSON with key 'companies' as a list; each has: name, contacts: [{full_name, title, email, inferred}]",
        ],
    )


def create_phone_finder_agent() -> Agent:
    exa_tools = ExaTools()
    memory = Memory()
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[exa_tools],
        memory=memory,
        add_history_to_messages=True,
        num_history_responses=6,
        session_id="gtm_outreach_phone_finder",
        show_tool_calls=True,
        instructions=[
            "You are PhoneFinderAgent. Use ExaTools to find phone numbers...",
            "Return ONLY valid JSON with key 'companies' as a list; each has: name, contacts: [{full_name, phone_number, phone_type, verified}]",
        ],
    )


def create_research_agent() -> Agent:
    exa_tools = ExaTools()
    memory = Memory()
    return Agent(
        model=OpenAIChat(id="gpt-5"),
        tools=[exa_tools],
        memory=memory,
        add_history_to_messages=True,
        num_history_responses=6,
        session_id="gtm_outreach_researcher",
        show_tool_calls=True,
        instructions=[
            "You are ResearchAgent. Collect insights from websites + Reddit...",
            "Return ONLY valid JSON with key 'companies' as a list; each has: name, insights: [strings].",
        ],
    )


def get_email_style_instruction(style_key: str) -> str:
    styles = {
        "Professional": "Style: Professional. Clear, respectful, and businesslike.",
        "Casual": "Style: Casual. Friendly, approachable, first-name basis.",
        "Cold": "Style: Cold email. Strong hook, tight value proposition.",
        "Consultative": "Style: Consultative. Insight-led, soft CTA.",
    }
    return styles.get(style_key, styles["Professional"])


def create_email_writer_agent(style_key: str = "Professional") -> Agent:
    memory = Memory()
    style_instruction = get_email_style_instruction(style_key)
    return Agent(
        model=OpenAIChat(id="gpt-5"),
        tools=[],
        memory=memory,
        add_history_to_messages=True,
        num_history_responses=6,
        session_id="gtm_outreach_email_writer",
        show_tool_calls=False,
        instructions=[
            "You are EmailWriterAgent. Write concise, personalized B2B outreach emails.",
            style_instruction,
            "Return ONLY valid JSON with key 'emails' as a list of items: {company, contact, subject, body}.",
        ],
    )


# -------- Utility Functions -------- #


def extract_json_or_raise(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def run_company_finder(
    agent: Agent, target_desc: str, offering_desc: str, max_companies: int
) -> List[Dict[str, str]]:
    prompt = f"Find exactly {max_companies} companies...\nTargeting: {target_desc}\nOffering: {offering_desc}"
    resp = agent.run(prompt)
    data = extract_json_or_raise(str(resp.content))
    return data.get("companies", [])[: max(1, min(max_companies, 10))]


def run_contact_finder(
    agent: Agent, companies: List[Dict[str, str]], target_desc: str, offering_desc: str
) -> List[Dict[str, Any]]:
    prompt = f"For each company below, find contacts...\nCompanies JSON: {json.dumps(companies)}"
    resp = agent.run(prompt)
    data = extract_json_or_raise(str(resp.content))
    return data.get("companies", [])


def run_phone_finder(
    agent: Agent, contacts_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    prompt = f"For each contact below, find phone numbers...\nContacts JSON: {json.dumps(contacts_data)}"
    resp = agent.run(prompt)
    data = extract_json_or_raise(str(resp.content))
    return data.get("companies", [])


def run_research(agent: Agent, companies: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    prompt = (
        f"For each company, gather insights...\nCompanies JSON: {json.dumps(companies)}"
    )
    resp = agent.run(prompt)
    data = extract_json_or_raise(str(resp.content))
    return data.get("companies", [])


def run_email_writer(
    agent: Agent,
    contacts_data: List[Dict[str, Any]],
    research_data: List[Dict[str, Any]],
    offering_desc: str,
    sender_name: str,
    sender_company: str,
    calendar_link: Optional[str],
) -> List[Dict[str, str]]:
    prompt = f"Write outreach emails...\nContacts JSON: {json.dumps(contacts_data)}\nResearch JSON: {json.dumps(research_data)}"
    resp = agent.run(prompt)
    data = extract_json_or_raise(str(resp.content))
    return data.get("emails", [])
