import json
import re
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`.")


class ZendeskTools(Toolkit):
    """
    A toolkit class for interacting with the Zendesk API.

    Supports Help Center article search and ticket operations (list, get, comment, update).
    Requires authentication details and the company name to configure the API access.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        company_name: Optional[str] = None,
        enable_search_zendesk: bool = True,
        enable_get_tickets: bool = False,
        enable_get_ticket: bool = False,
        enable_get_ticket_comments: bool = False,
        enable_create_ticket_comment: bool = False,
        enable_update_ticket: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """
        Initializes the ZendeskTools class with necessary authentication details
        and registers the enabled methods.

        Parameters:
            username: The username for Zendesk API authentication (email/token format for API tokens).
            password: The password or API token for Zendesk API authentication.
            company_name: The company name to form the base URL for API requests.
            enable_search_zendesk: Whether to enable Help Center article search.
            enable_get_tickets: Whether to enable ticket listing.
            enable_get_ticket: Whether to enable single ticket retrieval.
            enable_get_ticket_comments: Whether to enable ticket comment retrieval.
            enable_create_ticket_comment: Whether to enable creating ticket comments.
            enable_update_ticket: Whether to enable ticket updates.
            all: Enable all functions.
        """
        self.username = username or getenv("ZENDESK_USERNAME")
        self.password = password or getenv("ZENDESK_PASSWORD")
        self.company_name = company_name or getenv("ZENDESK_COMPANY_NAME")

        if not self.username or not self.password or not self.company_name:
            logger.warning(
                "Zendesk credentials not provided. Set ZENDESK_USERNAME, ZENDESK_PASSWORD, "
                "and ZENDESK_COMPANY_NAME environment variables."
            )

        self._html_clean = re.compile("<.*?>")

        tools: List[Any] = []
        if all or enable_search_zendesk:
            tools.append(self.search_zendesk)
        if all or enable_get_tickets:
            tools.append(self.get_tickets)
        if all or enable_get_ticket:
            tools.append(self.get_ticket)
        if all or enable_get_ticket_comments:
            tools.append(self.get_ticket_comments)
        if all or enable_create_ticket_comment:
            tools.append(self.create_ticket_comment)
        if all or enable_update_ticket:
            tools.append(self.update_ticket)

        super().__init__(name="zendesk_tools", tools=tools, **kwargs)

    def _strip_html(self, text: str) -> str:
        """Strip HTML tags from text."""
        return re.sub(self._html_clean, "", text)

    def _check_credentials(self) -> Optional[str]:
        """Check if credentials are configured. Returns error message if not."""
        if not self.username or not self.password or not self.company_name:
            return "Username, password, or company name not provided."
        return None

    def _get_auth(self) -> tuple:
        """Get auth tuple for requests."""
        return (self.username, self.password)

    def _base_url(self) -> str:
        """Get the base API URL."""
        return f"https://{self.company_name}.zendesk.com/api/v2"

    def search_zendesk(self, search_string: str) -> str:
        """
        Searches for articles in Zendesk Help Center that match the given search string.

        Parameters:
            search_string: The search query to look for in Zendesk articles.

        Returns:
            A JSON-formatted string containing the list of articles without HTML tags.

        Raises:
            ConnectionError: If the API request fails due to connection-related issues.
        """
        error = self._check_credentials()
        if error:
            return error

        log_debug(f"Searching Zendesk for: {search_string}")

        url = f"https://{self.company_name}.zendesk.com/api/v2/help_center/articles/search.json?query={search_string}"
        try:
            response = requests.get(url, auth=self._get_auth())
            response.raise_for_status()
            articles = [self._strip_html(article["body"]) for article in response.json()["results"]]
            return json.dumps(articles)
        except requests.RequestException as e:
            logger.error(f"Zendesk API error: {e}")
            return json.dumps({"error": str(e)})

    def get_tickets(
        self,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 25,
    ) -> str:
        """
        List tickets from Zendesk.

        Parameters:
            status: Filter by ticket status (new, open, pending, hold, solved, closed).
            page: Page number for pagination (default 1).
            per_page: Number of results per page (default 25, max 100).

        Returns:
            JSON string with ticket list, count, pagination info.
        """
        error = self._check_credentials()
        if error:
            return error

        log_debug(f"Getting tickets (status={status}, page={page})")

        per_page = min(per_page, 100)
        url = f"{self._base_url()}/tickets.json"

        try:
            response = requests.get(
                url,
                auth=self._get_auth(),
                params={"page": page, "per_page": per_page},
            )
            response.raise_for_status()
            data = response.json()

            tickets = data.get("tickets", [])

            if status:
                tickets = [t for t in tickets if t.get("status") == status]

            result = {
                "tickets": [
                    {
                        "id": t["id"],
                        "subject": t.get("subject"),
                        "status": t.get("status"),
                        "priority": t.get("priority"),
                        "created_at": t.get("created_at"),
                        "updated_at": t.get("updated_at"),
                        "requester_id": t.get("requester_id"),
                        "assignee_id": t.get("assignee_id"),
                        "tags": t.get("tags", []),
                    }
                    for t in tickets
                ],
                "count": len(tickets),
                "page": page,
                "has_more": data.get("next_page") is not None,
            }
            return json.dumps(result)
        except requests.RequestException as e:
            logger.error(f"Zendesk API error: {e}")
            return json.dumps({"error": str(e)})

    def get_ticket(self, ticket_id: int) -> str:
        """
        Get detailed information about a single ticket.

        Parameters:
            ticket_id: The ID of the ticket to retrieve.

        Returns:
            JSON string with ticket details.
        """
        error = self._check_credentials()
        if error:
            return error

        log_debug(f"Getting ticket {ticket_id}")

        url = f"{self._base_url()}/tickets/{ticket_id}.json"

        try:
            response = requests.get(url, auth=self._get_auth())
            response.raise_for_status()
            ticket = response.json()["ticket"]

            result = {
                "id": ticket["id"],
                "subject": ticket.get("subject"),
                "description": ticket.get("description"),
                "status": ticket.get("status"),
                "priority": ticket.get("priority"),
                "type": ticket.get("type"),
                "created_at": ticket.get("created_at"),
                "updated_at": ticket.get("updated_at"),
                "requester_id": ticket.get("requester_id"),
                "assignee_id": ticket.get("assignee_id"),
                "tags": ticket.get("tags", []),
                "via": ticket.get("via", {}).get("channel"),
                "custom_fields": ticket.get("custom_fields", []),
            }
            return json.dumps(result)
        except requests.RequestException as e:
            logger.error(f"Zendesk API error: {e}")
            return json.dumps({"error": str(e)})

    def get_ticket_comments(self, ticket_id: int) -> str:
        """
        Get comments/conversation thread for a ticket.

        Parameters:
            ticket_id: The ID of the ticket to get comments for.

        Returns:
            JSON string with comment list.
        """
        error = self._check_credentials()
        if error:
            return error

        log_debug(f"Getting comments for ticket {ticket_id}")

        url = f"{self._base_url()}/tickets/{ticket_id}/comments.json"

        try:
            response = requests.get(url, auth=self._get_auth())
            response.raise_for_status()
            comments = response.json().get("comments", [])

            result = {
                "ticket_id": ticket_id,
                "comments": [
                    {
                        "id": c["id"],
                        "author_id": c.get("author_id"),
                        "body": c.get("body") or self._strip_html(c.get("html_body", "")),
                        "created_at": c.get("created_at"),
                        "public": c.get("public", True),
                        "type": c.get("type"),
                    }
                    for c in comments
                ],
                "count": len(comments),
            }
            return json.dumps(result)
        except requests.RequestException as e:
            logger.error(f"Zendesk API error: {e}")
            return json.dumps({"error": str(e)})

    def create_ticket_comment(
        self,
        ticket_id: int,
        body: str,
        public: bool = True,
    ) -> str:
        """
        Add a comment to a ticket.

        Parameters:
            ticket_id: The ID of the ticket to comment on.
            body: The comment text.
            public: Whether the comment is visible to the requester (default True).
                    Set to False for internal notes.

        Returns:
            JSON string with success status and updated ticket info.
        """
        error = self._check_credentials()
        if error:
            return error

        log_debug(f"Creating comment on ticket {ticket_id} (public={public})")

        url = f"{self._base_url()}/tickets/{ticket_id}.json"
        payload = {
            "ticket": {
                "comment": {
                    "body": body,
                    "public": public,
                }
            }
        }

        try:
            response = requests.put(url, auth=self._get_auth(), json=payload)
            response.raise_for_status()
            ticket = response.json()["ticket"]

            return json.dumps(
                {
                    "success": True,
                    "ticket_id": ticket["id"],
                    "message": "Comment added successfully",
                    "updated_at": ticket.get("updated_at"),
                }
            )
        except requests.RequestException as e:
            logger.error(f"Zendesk API error: {e}")
            return json.dumps({"error": str(e)})

    def update_ticket(
        self,
        ticket_id: int,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assignee_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """
        Update ticket properties.

        Parameters:
            ticket_id: The ID of the ticket to update.
            status: New status (new, open, pending, hold, solved, closed).
            priority: New priority (low, normal, high, urgent).
            assignee_id: ID of the agent to assign the ticket to.
            tags: List of tags to set on the ticket.

        Returns:
            JSON string with success status and updated ticket info.
        """
        error = self._check_credentials()
        if error:
            return error

        ticket_update: dict = {}
        if status is not None:
            ticket_update["status"] = status
        if priority is not None:
            ticket_update["priority"] = priority
        if assignee_id is not None:
            ticket_update["assignee_id"] = assignee_id
        if tags is not None:
            ticket_update["tags"] = tags

        if not ticket_update:
            return json.dumps(
                {
                    "success": False,
                    "message": "No fields to update. Provide at least one of: status, priority, assignee_id, tags.",
                }
            )

        log_debug(f"Updating ticket {ticket_id}: {ticket_update}")

        url = f"{self._base_url()}/tickets/{ticket_id}.json"
        payload = {"ticket": ticket_update}

        try:
            response = requests.put(url, auth=self._get_auth(), json=payload)
            response.raise_for_status()
            ticket = response.json()["ticket"]

            return json.dumps(
                {
                    "success": True,
                    "ticket_id": ticket["id"],
                    "status": ticket.get("status"),
                    "priority": ticket.get("priority"),
                    "assignee_id": ticket.get("assignee_id"),
                    "tags": ticket.get("tags", []),
                    "updated_at": ticket.get("updated_at"),
                }
            )
        except requests.RequestException as e:
            logger.error(f"Zendesk API error: {e}")
            return json.dumps({"error": str(e)})
