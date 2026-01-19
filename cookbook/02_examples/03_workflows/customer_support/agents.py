from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel


class SupportTicketClassification(BaseModel):
    category: str
    priority: str
    tags: List[str]
    summary: str


triage_agent = Agent(
    name="Ticket Classifier",
    model=OpenAIChat(id="gpt-5-mini"),
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
    output_schema=SupportTicketClassification,
)

support_agent = Agent(
    name="Solution Developer",
    model=OpenAIChat(id="gpt-5-mini"),
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
