"""
Google People API toolkit for contact and directory lookups.

Required Environment Variables:
-----------------------------
- GOOGLE_CLIENT_ID: Google OAuth client ID
- GOOGLE_CLIENT_SECRET: Google OAuth client secret
- GOOGLE_PROJECT_ID: Google Cloud project ID

Setup:
-----
1. Enable the People API at Google Cloud Console:
   https://console.cloud.google.com/apis/library/people.googleapis.com

2. For directory lookups (list_directory_people), you need:
   - Google Workspace account (not personal Gmail)
   - Admin-enabled directory access

Scopes:
------
- contacts.readonly: Read user's contacts
- directory.readonly: Read organization directory (Workspace only)
- userinfo.profile: Read basic profile info
"""

import textwrap
from typing import Any, Dict, List, Optional, Union

from agno.agent.agent import Agent
from agno.run.base import RunContext

try:
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from googleapiclient.discovery import Resource
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "`google-api-python-client` `google-auth-httplib2` `google-auth-oauthlib` not installed. "
        "Please install using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )

from agno.tools.google.auth import google_authenticate
from agno.tools.google.base import GoogleToolkit
from agno.utils.log import log_error

PEOPLE_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Google People tools for looking up contacts and directory information.

    ## Key Capabilities
    - search_contacts: Find contacts by name, email, or phone
    - get_contact: Get detailed info for a specific contact
    - list_directory_people: Search organization directory (Workspace only)
    - get_person: Get profile info by resource name

    ## Tips
    - Use search_contacts for the user's personal contacts
    - Use list_directory_people for coworkers in the organization
    - Directory access requires Google Workspace (not personal Gmail)
    - Resource names look like "people/c12345" for contacts or "people/account_id" for directory
""")


authenticate = google_authenticate("people")


class GooglePeopleTools(GoogleToolkit):
    """Google People API toolkit for contact and directory lookups.

    Enables looking up contacts, searching the organization directory,
    and resolving names to email addresses.
    """

    api_name = "people"
    api_version = "v1"
    google_service_name = "people"
    default_scopes = [
        "https://www.googleapis.com/auth/contacts.readonly",
        "https://www.googleapis.com/auth/directory.readonly",
    ]

    def __init__(
        self,
        # Feature flags
        search_contacts: bool = True,
        get_contact: bool = True,
        list_directory_people: bool = True,
        get_person: bool = True,
        # Auth params
        scopes: Optional[List[str]] = None,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        **kwargs: Any,
    ):
        super().__init__(scopes=scopes, creds=creds, **kwargs)

        self._search_contacts = search_contacts
        self._get_contact = get_contact
        self._list_directory_people = list_directory_people
        self._get_person = get_person

        self._register_tools()

    def _register_tools(self) -> None:
        if self._search_contacts:
            self.register(self.search_contacts)
        if self._get_contact:
            self.register(self.get_contact)
        if self._list_directory_people:
            self.register(self.list_directory_people)
        if self._get_person:
            self.register(self.get_person)

    @classmethod
    def get_default_instructions(cls) -> str:
        return PEOPLE_INSTRUCTIONS

    def _format_person(self, person: Dict[str, Any]) -> Dict[str, Any]:
        """Extract useful fields from a person resource."""
        result: Dict[str, Any] = {}

        resource_name = person.get("resourceName", "")
        result["resource_name"] = resource_name

        # Names
        names = person.get("names", [])
        if names:
            result["name"] = names[0].get("displayName", "")

        # Email addresses
        emails = person.get("emailAddresses", [])
        if emails:
            result["emails"] = [e.get("value") for e in emails if e.get("value")]
            result["primary_email"] = emails[0].get("value", "")

        # Phone numbers
        phones = person.get("phoneNumbers", [])
        if phones:
            result["phones"] = [p.get("value") for p in phones if p.get("value")]

        # Organization/job
        orgs = person.get("organizations", [])
        if orgs:
            org = orgs[0]
            result["organization"] = org.get("name", "")
            result["title"] = org.get("title", "")
            result["department"] = org.get("department", "")

        # Photos
        photos = person.get("photos", [])
        if photos:
            result["photo_url"] = photos[0].get("url", "")

        return result

    @authenticate
    def search_contacts(self, agent: Agent, run_context: RunContext, query: str, page_size: int = 10) -> str:
        """Search the user's contacts by name, email, or phone.

        Args:
            query: Search term (name, email, or phone number)
            page_size: Max results to return (default 10, max 30)

        Returns:
            JSON with matching contacts
        """
        try:
            page_size = min(page_size, 30)
            service: Resource = self.service

            results = (
                service.people()
                .searchContacts(
                    query=query,
                    pageSize=page_size,
                    readMask="names,emailAddresses,phoneNumbers,organizations,photos",
                )
                .execute()
            )

            contacts = results.get("results", [])
            formatted = []
            for result in contacts:
                person = result.get("person", {})
                formatted.append(self._format_person(person))

            return str({"contacts": formatted, "total": len(formatted)})

        except HttpError as e:
            log_error(f"People API error: {e}")
            return str({"error": str(e), "status_code": e.resp.status})
        except Exception as e:
            log_error(f"Error searching contacts: {e}")
            return str({"error": str(e)})

    @authenticate
    def get_contact(self, agent: Agent, run_context: RunContext, resource_name: str) -> str:
        """Get detailed information for a specific contact.

        Args:
            resource_name: Contact resource name (e.g., "people/c12345")

        Returns:
            JSON with contact details
        """
        try:
            service: Resource = self.service

            person = (
                service.people()
                .get(
                    resourceName=resource_name,
                    personFields="names,emailAddresses,phoneNumbers,organizations,photos,biographies,addresses",
                )
                .execute()
            )

            return str(self._format_person(person))

        except HttpError as e:
            log_error(f"People API error: {e}")
            return str({"error": str(e), "status_code": e.resp.status})
        except Exception as e:
            log_error(f"Error getting contact: {e}")
            return str({"error": str(e)})

    @authenticate
    def list_directory_people(
        self,
        agent: Agent,
        run_context: RunContext,
        query: str = "",
        page_size: int = 20,
        page_token: Optional[str] = None,
    ) -> str:
        """List people in the organization directory (Google Workspace only).

        Args:
            query: Optional search query (name or email)
            page_size: Max results per page (default 20, max 100)
            page_token: Token for pagination

        Returns:
            JSON with directory people and pagination info
        """
        try:
            page_size = min(page_size, 100)
            service: Resource = self.service

            request_params: Dict[str, Any] = {
                "pageSize": page_size,
                "readMask": "names,emailAddresses,phoneNumbers,organizations,photos",
                "sources": ["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"],
            }

            if query:
                request_params["query"] = query
            if page_token:
                request_params["pageToken"] = page_token

            results = service.people().listDirectoryPeople(**request_params).execute()

            people = results.get("people", [])
            formatted = [self._format_person(p) for p in people]

            response: Dict[str, Any] = {
                "people": formatted,
                "total": len(formatted),
            }

            if "nextPageToken" in results:
                response["next_page_token"] = results["nextPageToken"]

            return str(response)

        except HttpError as e:
            if e.resp.status == 403:
                return str(
                    {
                        "error": "Directory access requires Google Workspace account with admin-enabled directory access",
                        "status_code": 403,
                    }
                )
            log_error(f"People API error: {e}")
            return str({"error": str(e), "status_code": e.resp.status})
        except Exception as e:
            log_error(f"Error listing directory: {e}")
            return str({"error": str(e)})

    @authenticate
    def get_person(self, agent: Agent, run_context: RunContext, resource_name: str) -> str:
        """Get profile information for a person by resource name.

        Works for both contacts (people/c123) and directory entries (people/account_id).

        Args:
            resource_name: Person resource name

        Returns:
            JSON with person details
        """
        try:
            service: Resource = self.service

            person = (
                service.people()
                .get(
                    resourceName=resource_name,
                    personFields="names,emailAddresses,phoneNumbers,organizations,photos,biographies",
                )
                .execute()
            )

            return str(self._format_person(person))

        except HttpError as e:
            log_error(f"People API error: {e}")
            return str({"error": str(e), "status_code": e.resp.status})
        except Exception as e:
            log_error(f"Error getting person: {e}")
            return str({"error": str(e)})
