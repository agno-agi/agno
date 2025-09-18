import base64
import re
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit

from agno.utils.log import logger

try:
    from email.mime.text import MIMEText

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "Google client library for Python not found , install it using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


def authenticate(func):
    """Decorator to ensure authentication before executing a function."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self.creds or not self.creds.valid:
            self._auth()
        if not self.service:
            self.service = build("gmail", "v1", credentials=self.creds)
        return func(self, *args, **kwargs)

    return wrapper


def validate_email(email: str) -> bool:
    """Validate email format."""
    email = email.strip()
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


class GmailTools(Toolkit):
    # Default scopes for Gmail API access
    DEFAULT_SCOPES = [
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ]

    def __init__(
        self,
        creds: Optional[Credentials] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ):
        """Initialize GmailTools and authenticate with Gmail API

        Args:
            creds (Optional[Credentials]): Pre-existing credentials. Defaults to None.
            credentials_path (Optional[str]): Path to credentials file. Defaults to None.
            token_path (Optional[str]): Path to token file. Defaults to None.
            scopes (Optional[List[str]]): Custom OAuth scopes. If None, uses DEFAULT_SCOPES.
        """
        super().__init__(name="gmail_tools")
        self.creds = creds
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes or self.DEFAULT_SCOPES
        self.service = None

    @authenticate
    def get_emails_from_user(self, user: str, count: int) -> List[dict]:
        """
        Get X number of emails from a specific user (name or email).

        Args:
            user (str): Name or email address of the sender
            count (int): Maximum number of emails to retrieve

        Returns:
            List[dict]: List of email details
        """
        try:
            logger.debug(f"Getting {count} emails from {user}")
            query = f"from:{user}" if "@" in user else f"from:{user}*"
            results = self.service.users().messages().list(userId="me", q=query, maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            logger.error(f"Error retrieving emails from {user}: {error}")
            return [{"error": f"Error retrieving emails from {user}: {error}"}]
        except Exception as error:
            logger.error(f"Unexpected error retrieving emails from {user}: {type(error).__name__}: {error}")
            return [{"error": f"Unexpected error retrieving emails from {user}: {type(error).__name__}: {error}"}]

    def _auth(self) -> None:
        """Authenticate with Gmail API"""
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": getenv("GOOGLE_CLIENT_ID"),
                        "client_secret": getenv("GOOGLE_CLIENT_SECRET"),
                        "project_id": getenv("GOOGLE_PROJECT_ID"),
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [getenv("GOOGLE_REDIRECT_URI", "http://localhost")],
                    }
                }
                if creds_file.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
                else:
                    flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
                self.creds = flow.run_local_server(port=0)

            # Save the credentials for future use
            if self.creds and self.creds.valid:
                token_file.write_text(self.creds.to_json())

    def _format_emails(self, emails: List[dict]) -> List[dict]:
        """Format list of email dictionaries into a readable string"""
        if not emails:
            return []

        formatted_emails = []
        for email in emails:
            formatted_email = {
                "from": email["from"],
                "subject": email["subject"],
                "date": email["date"],
                "body": email["body"],
                "id": email["id"],
                "message_id": email["message_id"],
                "in-reply-to": email["in-reply-to"],
                "references": email["references"],
                "thread_id": email["thread_id"],
            }
            formatted_emails.append(formatted_email)
        return formatted_emails

    @authenticate
    def get_latest_emails(self, count: int) -> str:
        """
        Get the latest X emails from the user's inbox.

        Args:
            count (int): Number of latest emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            results = self.service.users().messages().list(userId="me", maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving latest emails: {error}"
        except Exception as error:
            return f"Unexpected error retrieving latest emails: {type(error).__name__}: {error}"

    @authenticate
    def get_unread_emails(self, count: int) -> str:
        """
        Get the X number of latest unread emails from the user's inbox.

        Args:
            count (int): Maximum number of unread emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            results = self.service.users().messages().list(userId="me", q="is:unread", maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving unread emails: {error}"
        except Exception as error:
            return f"Unexpected error retrieving unread emails: {type(error).__name__}: {error}"

    @authenticate
    def get_emails_by_thread(self, thread_id: str) -> List[dict]:
        """
        Retrieve all emails from a specific thread.

        Args:
            thread_id (str): The ID of the email thread.

        Returns:
            str: Formatted string containing email thread details.
        """
        try:
            thread = self.service.users().threads().get(userId="me", id=thread_id).execute()  # type: ignore
            messages = thread.get("messages", [])
            emails = self._get_message_details(messages)
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving emails from thread {thread_id}: {error}"
        except Exception as error:
            return f"Unexpected error retrieving emails from thread {thread_id}: {type(error).__name__}: {error}"

    @authenticate
    def send_email(self, to: str, subject: str, body: str, cc: Optional[str] = None) -> str:
        """
        Send an email immediately. to and cc are comma separated string of email ids
        Args:
            to (str): Comma separated string of recipient email addresses
            subject (str): Email subject
            body (str): Email body content
            cc (Optional[str]): Comma separated string of CC email addresses (optional)

        Returns:
            str: Stringified dictionary containing sent email details including id
        """
        self._validate_email_params(to, subject, body)
        body = body.replace("\n", "<br>")
        message = self._create_message(to.split(","), subject, body, cc.split(",") if cc else None)
        message = self.service.users().messages().send(userId="me", body=message).execute()  # type: ignore
        return str(message)

    @authenticate
    def send_email_reply(
        self, thread_id: str, message_id: str, to: str, subject: str, body: str, cc: Optional[str] = None
    ) -> str:
        """
        Respond to an existing email thread.

        Args:
            thread_id (str): The ID of the email thread to reply to.
            message_id (str): The ID of the email being replied to.
            to (str): Comma-separated recipient email addresses.
            subject (str): Email subject (prefixed with "Re:" if not already).
            body (str): Email body content.
            cc (Optional[str]): Comma-separated CC email addresses (optional).

        Returns:
            str: Stringified dictionary containing sent email details including id.
        """
        self._validate_email_params(to, subject, body)

        # Ensure subject starts with "Re:" for consistency
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        body = body.replace("\n", "<br>")
        message = self._create_message(
            to.split(","), subject, body, cc.split(",") if cc else None, thread_id, message_id
        )
        message = self.service.users().messages().send(userId="me", body=message).execute()  # type: ignore
        return str(message)

    @authenticate
    def search_emails(self, query: str, count: int) -> str:
        """
        Get X number of emails based on a given natural text query.
        Searches in to, from, cc, subject and email body contents.

        Args:
            query (str): Natural language query to search for
            count (int): Number of emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            results = self.service.users().messages().list(userId="me", q=query, maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving emails with query '{query}': {error}"
        except Exception as error:
            return f"Unexpected error retrieving emails with query '{query}': {type(error).__name__}: {error}"

    def _create_message(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> dict:
        body = body.replace("\\n", "\n")
        message = MIMEText(body, "html")
        message["to"] = ", ".join(to)
        message["from"] = "me"
        message["subject"] = subject

        if cc:
            message["Cc"] = ", ".join(cc)

        # Add reply headers if this is a response
        if thread_id and message_id:
            message["In-Reply-To"] = message_id
            message["References"] = message_id

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        email_data = {"raw": raw_message}

        if thread_id:
            email_data["threadId"] = thread_id

        return email_data

    def _get_message_details(self, messages: List[dict]) -> List[dict]:
        """Get details for list of messages"""
        details = []
        for msg in messages:
            msg_data = self.service.users().messages().get(userId="me", id=msg["id"], format="full").execute()  # type: ignore
            # pprint(msg_data)
            details.append(
                {
                    "id": msg_data["id"],
                    "thread_id": msg_data.get("threadId"),
                    "message_id": next(
                        (
                            header["value"]
                            for header in msg_data["payload"]["headers"]
                            if header["name"].lower() == "message-id"
                        ),
                        None,
                    ),
                    "subject": next(
                        (
                            header["value"]
                            for header in msg_data["payload"]["headers"]
                            if header["name"].lower() == "subject"
                        ),
                        None,
                    ),
                    "from": next(
                        (
                            header["value"]
                            for header in msg_data["payload"]["headers"]
                            if header["name"].lower() == "from"
                        ),
                        None,
                    ),
                    "date": next(
                        (
                            header["value"]
                            for header in msg_data["payload"]["headers"]
                            if header["name"].lower() == "date"
                        ),
                        None,
                    ),
                    "in-reply-to": next(
                        (
                            header["value"]
                            for header in msg_data["payload"]["headers"]
                            if header["name"].lower() == "in-reply-to"
                        ),
                        None,
                    ),
                    "references": next(
                        (
                            header["value"]
                            for header in msg_data["payload"]["headers"]
                            if header["name"].lower() == "references"
                        ),
                        None,
                    ),
                    "body": self._get_message_body(msg_data),
                }
            )
        # filter subject to only include the vendor name
        details = [
            detail
            for detail in details
            if "subject" in detail and detail["subject"] and "siemens" in detail["subject"].lower()
        ]
        return details

    def _get_message_body(self, msg_data: dict) -> str:
        """Extract message body from message data"""
        body = ""
        attachments = []
        try:
            if "parts" in msg_data["payload"]:
                for part in msg_data["payload"]["parts"]:
                    if part["mimeType"] == "text/plain":
                        if "data" in part["body"]:
                            body = base64.urlsafe_b64decode(part["body"]["data"]).decode()
                    elif "filename" in part:
                        attachments.append(part["filename"])
            elif "body" in msg_data["payload"] and "data" in msg_data["payload"]["body"]:
                body = base64.urlsafe_b64decode(msg_data["payload"]["body"]["data"]).decode()
        except Exception:
            return "Unable to decode message body"

        if attachments:
            return f"{body}\n\nAttachments: {', '.join(attachments)}"
        return body

    def _validate_email_params(self, to: str, subject: str, body: str) -> None:
        """Validate email parameters."""
        if not to:
            raise ValueError("Recipient email cannot be empty")

        # Validate each email in the comma-separated list
        for email in to.split(","):
            if not validate_email(email.strip()):
                raise ValueError(f"Invalid recipient email format: {email}")

        if not subject or not subject.strip():
            raise ValueError("Subject cannot be empty")

        if body is None:
            raise ValueError("Email body cannot be None")

    @authenticate
    def setup_push_notifications(self, topic_name: str, label_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Setup Gmail push notifications to a Cloud Pub/Sub topic.

        Args:
            topic_name (str): Full Cloud Pub/Sub topic name (projects/{project_id}/topics/{topic_name})
            label_ids (Optional[List[str]]): List of label IDs to watch. Defaults to ["INBOX"]

        Returns:
            Dict[str, Any]: Watch response containing historyId and expiration
        """
        try:
            request_body = {
                "topicName": topic_name,
                "labelIds": label_ids or ["INBOX"],
                "labelFilterBehavior": "INCLUDE",
            }

            response = (
                self.service.users()
                .watch(  # type: ignore
                    userId="me", body=request_body
                )
                .execute()
            )

            logger.info(f"Successfully setup push notifications to topic: {topic_name}")
            return response

        except HttpError as error:
            logger.error(f"Error setting up push notifications: {error}")
            raise

    @authenticate
    def stop_push_notifications(self) -> None:
        """Stop receiving Gmail push notifications."""
        try:
            self.service.users().stop(userId="me").execute()  # type: ignore
            logger.info("Successfully stopped push notifications")
        except HttpError as error:
            logger.error(f"Error stopping push notifications: {error}")
            raise
