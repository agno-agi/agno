"""
Custom tools for Apollo API integration
Provides People Search, People Enrichment, and Organization Enrichment
"""

import os
from typing import Optional, Dict, Any

import requests
from agno.tools import tool

APOLLO_TIMEOUT = float(os.getenv("APOLLO_API_TIMEOUT", "10"))


@tool()
def search_people(
    person_titles: Optional[str] = None,
    person_locations: Optional[str] = None,
    q_keywords: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
) -> Dict[str, Any]:
    """
    Search for people using Apollo API.
    
    Args:
        person_titles: Job titles to search for (e.g., "Sales Director", "Marketing Manager")
        person_locations: Locations to search in (e.g., "London", "New York")
        q_keywords: Additional keywords for search
        page: Page number for pagination (default: 1)
        per_page: Number of results per page (default: 10, max: 100)
    
    Returns:
        Dictionary containing search results with people data
    """
    api_key = os.getenv("APOLLO_API_KEY")
    if not api_key:
        return {"error": "APOLLO_API_KEY not found in environment variables"}
    
    url = "https://api.apollo.io/v1/mixed_people/search"
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }
    
    payload = {
        "page": page,
        "per_page": min(per_page, 100),
    }
    
    if person_titles:
        payload["person_titles"] = [person_titles]
    if person_locations:
        payload["person_locations"] = [person_locations]
    if q_keywords:
        payload["q_keywords"] = q_keywords
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=APOLLO_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Apollo API error: {str(e)}"}


@tool()
def enrich_person(
    linkedin_url: Optional[str] = None,
    apollo_person_id: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Enrich person data from LinkedIn URL, Apollo ID, or email.
    
    Args:
        linkedin_url: LinkedIn profile URL
        apollo_person_id: Apollo person ID
        email: Email address of the person
    
    Returns:
        Dictionary containing enriched person data
    """
    api_key = os.getenv("APOLLO_API_KEY")
    if not api_key:
        return {"error": "APOLLO_API_KEY not found in environment variables"}
    
    url = "https://api.apollo.io/v1/people/match"
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }
    
    payload = {}
    if linkedin_url:
        payload["linkedin_url"] = linkedin_url
    if apollo_person_id:
        payload["id"] = apollo_person_id
    if email:
        payload["email"] = email
    
    if not payload:
        return {"error": "At least one of linkedin_url, apollo_person_id, or email must be provided"}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=APOLLO_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Apollo API error: {str(e)}"}


@tool()
def enrich_organization(
    organization_id: Optional[str] = None,
    domain: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Enrich organization data to get firmographics (size, location, revenue, tech stack).
    
    Args:
        organization_id: Apollo organization ID
        domain: Company domain (e.g., "example.com")
        name: Company name
    
    Returns:
        Dictionary containing enriched organization data including firmographics
    """
    api_key = os.getenv("APOLLO_API_KEY")
    if not api_key:
        return {"error": "APOLLO_API_KEY not found in environment variables"}
    
    url = "https://api.apollo.io/v1/organizations/match"
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }
    
    payload = {}
    if organization_id:
        payload["id"] = organization_id
    if domain:
        payload["domain"] = domain
    if name:
        payload["name"] = name
    
    if not payload:
        return {"error": "At least one of organization_id, domain, or name must be provided"}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=APOLLO_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Apollo API error: {str(e)}"}

