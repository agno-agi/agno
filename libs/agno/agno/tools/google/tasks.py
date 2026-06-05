"""GoogleTasksTools — Google Tasks API v1 toolkit for task list and task management.

Setup:
1. Install the Google client libraries:
   `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`

2. Enable the Google Tasks API in your Google Cloud project:
   https://console.cloud.google.com/apis/enableflow?apiid=tasks.googleapis.com

3. Create OAuth 2.0 credentials (Desktop app) from API & Services -> Credentials
   and download the JSON file. Pass its path as ``credentials_path``.

   Alternatively, set a service account file via the ``GOOGLE_SERVICE_ACCOUNT_FILE``
   environment variable (requires domain-wide delegation for user impersonation).

Required OAuth scopes (one of):
- ``https://www.googleapis.com/auth/tasks.readonly`` (read-only access)
- ``https://www.googleapis.com/auth/tasks`` (full read/write access)

Add these scopes in the OAuth consent screen under "Scopes for Google APIs".
"""

import json
import textwrap
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from agno.tools import Toolkit
from agno.tools.google.auth import google_authenticate
from agno.utils.log import log_debug, log_error, log_info

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "Google client libraries not found. Install using "
        "`pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


TASKS_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Google Tasks tools for managing task lists and tasks.

    ## Terminology
    - A "task list" is a named collection of tasks (e.g. "Work", "Groceries").
    - A "task" belongs to exactly one task list and may have a parent task (subtask).

    ## Date/Time Formats
    - Due dates use RFC 3339 timestamps (e.g. ``2026-12-31T00:00:00Z``).
    - A date-only value like ``2026-12-31`` is accepted; the API treats it as UTC midnight.
    - The API stores due dates with second-level precision only; time-of-day is ignored.

    ## Tips
    - Always call ``list_task_lists`` first to discover available task list IDs.
    - ``create_task`` uses the task list's ID, not its title — fetch the ID with ``list_task_lists``.
    - To add a subtask, pass the parent task's ID as the ``parent`` argument to ``create_task``.
    - Use ``complete_task`` to mark a task done — this sets ``status=completed`` and a completion timestamp.
    - ``clear_completed_tasks`` hides completed tasks from the default view; it does not delete them.""")


authenticate = google_authenticate("tasks")


class GoogleTasksTools(Toolkit):
    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/tasks.readonly",
        "https://www.googleapis.com/auth/tasks",
    ]

    def __init__(
        self,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = "token.json",
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        oauth_port: int = 8080,
        login_hint: Optional[str] = None,
        list_task_lists: bool = True,
        get_task_list: bool = True,
        list_tasks: bool = True,
        get_task: bool = True,
        create_task_list: bool = True,
        update_task_list: bool = True,
        create_task: bool = True,
        update_task: bool = True,
        complete_task: bool = True,
        move_task: bool = True,
        delete_task_list: bool = False,
        delete_task: bool = False,
        clear_completed_tasks: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs: Any,
    ):
        """Initialize GoogleTasksTools with authentication and tool selection.

        Args:
            creds: Pre-fetched credentials to skip a new auth flow.
            credentials_path: Path to OAuth credentials JSON file.
            token_path: Path to cached token file. Created on first auth.
            service_account_path: Path to service account JSON key. When set, OAuth is skipped.
            delegated_user: Email to impersonate via domain-wide delegation. Optional for Tasks.
            scopes: Custom OAuth scopes. If None, uses DEFAULT_SCOPES.
            oauth_port: Port for OAuth local redirect server (default: 8080).
            login_hint: Email to pre-select in the OAuth consent screen.
            list_task_lists: Register the list_task_lists tool (read).
            get_task_list: Register the get_task_list tool (read).
            list_tasks: Register the list_tasks tool (read).
            get_task: Register the get_task tool (read).
            create_task_list: Register the create_task_list tool (write).
            update_task_list: Register the update_task_list tool (write).
            create_task: Register the create_task tool (write).
            update_task: Register the update_task tool (write).
            complete_task: Register the complete_task tool (write).
            move_task: Register the move_task tool (write).
            delete_task_list: Register the delete_task_list tool (destructive, disabled by default).
            delete_task: Register the delete_task tool (destructive, disabled by default).
            clear_completed_tasks: Register the clear_completed_tasks tool (destructive, disabled by default).
            instructions: Custom instructions for the toolkit. If None, uses default.
            add_instructions: Whether to inject instructions into the agent system prompt.
        """
        if instructions is None:
            self.instructions = TASKS_INSTRUCTIONS
        else:
            self.instructions = instructions

        self.creds = creds
        self.service: Optional[Resource] = None
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service_account_path = service_account_path
        self.delegated_user = delegated_user
        self.scopes = scopes or self.DEFAULT_SCOPES
        self.oauth_port = oauth_port
        self.login_hint = login_hint

        tools: List[Any] = []
        if list_task_lists:
            tools.append(self.list_task_lists)
        if get_task_list:
            tools.append(self.get_task_list)
        if list_tasks:
            tools.append(self.list_tasks)
        if get_task:
            tools.append(self.get_task)
        if create_task_list:
            tools.append(self.create_task_list)
        if update_task_list:
            tools.append(self.update_task_list)
        if create_task:
            tools.append(self.create_task)
        if update_task:
            tools.append(self.update_task)
        if complete_task:
            tools.append(self.complete_task)
        if move_task:
            tools.append(self.move_task)
        if delete_task_list:
            tools.append(self.delete_task_list)
        if delete_task:
            tools.append(self.delete_task)
        if clear_completed_tasks:
            tools.append(self.clear_completed_tasks)

        super().__init__(
            name="google_tasks_tools",
            tools=tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

        # Scope validation: write operations require the full tasks scope
        write_tool_names = {
            "create_task_list",
            "update_task_list",
            "delete_task_list",
            "create_task",
            "update_task",
            "complete_task",
            "move_task",
            "delete_task",
            "clear_completed_tasks",
        }
        if any(name in self.functions for name in write_tool_names):
            if "https://www.googleapis.com/auth/tasks" not in self.scopes:
                raise ValueError("The scope https://www.googleapis.com/auth/tasks is required for write operations")

        read_tool_names = {"list_task_lists", "get_task_list", "list_tasks", "get_task"}
        if any(name in self.functions for name in read_tool_names):
            # Full write scope is a superset of read — either satisfies read operations
            read_scope = "https://www.googleapis.com/auth/tasks.readonly"
            write_scope = "https://www.googleapis.com/auth/tasks"
            if read_scope not in self.scopes and write_scope not in self.scopes:
                raise ValueError(f"The scope {read_scope} is required for read operations")

    def _build_service(self):
        return build("tasks", "v1", credentials=self.creds)

    def _auth(self) -> None:
        """Authenticate with Google Tasks API using service account (priority) or OAuth flow."""
        if self.creds and self.creds.valid:
            return

        # Service account authentication takes priority over OAuth
        service_account_path = self.service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if service_account_path:
            delegated_user = self.delegated_user or getenv("GOOGLE_DELEGATED_USER")
            sa_creds = ServiceAccountCredentials.from_service_account_file(
                service_account_path,
                scopes=self.scopes,
            )
            # Tasks service accounts can optionally impersonate a user
            if delegated_user:
                sa_creds = sa_creds.with_subject(delegated_user)
            # Eagerly fetch token so creds.valid=True and @authenticate won't re-enter _auth
            sa_creds.refresh(Request())
            self.creds = sa_creds
            return

        # OAuth flow
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            try:
                self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
            except ValueError:
                # Token file missing refresh_token — fall through to re-auth
                self.creds = None

        if self.creds and self.creds.expired and self.creds.refresh_token:  # type: ignore[union-attr]
            try:
                self.creds.refresh(Request())
            except Exception:
                # Refresh token revoked or expired — fall through to re-auth
                self.creds = None

        if not self.creds or not self.creds.valid:
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
            # prompt=consent forces Google to return a refresh_token every time
            oauth_kwargs: Dict[str, Any] = {"prompt": "consent"}
            if self.login_hint:
                oauth_kwargs["login_hint"] = self.login_hint
            oauth_kwargs["port"] = self.oauth_port
            self.creds = flow.run_local_server(**oauth_kwargs)

        if self.creds and self.creds.valid:
            token_file.write_text(self.creds.to_json())  # type: ignore[union-attr]
            log_debug("Successfully authenticated with Google Tasks API.")
            log_info(f"Token file path: {token_file}")

    @authenticate
    def list_task_lists(self, max_results: int = 100) -> str:
        """
        List all task lists for the authenticated user.

        Args:
            max_results (int): Maximum number of task lists to return (default: 100, max: 100).

        Returns:
            str: JSON string containing the list of task lists or an error message.
        """
        try:
            service = cast(Resource, self.service)
            response = service.tasklists().list(maxResults=min(max_results, 100)).execute()
            task_lists = response.get("items", [])
            if not task_lists:
                return json.dumps({"message": "No task lists found."})
            return json.dumps(task_lists)
        except HttpError as error:
            log_error(f"Failed to list task lists: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def get_task_list(self, task_list_id: str) -> str:
        """
        Retrieve a single task list by its ID.

        Args:
            task_list_id (str): The ID of the task list to fetch.

        Returns:
            str: JSON string containing the task list or an error message.
        """
        try:
            service = cast(Resource, self.service)
            task_list = service.tasklists().get(tasklist=task_list_id).execute()
            return json.dumps(task_list)
        except HttpError as error:
            log_error(f"Failed to get task list {task_list_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def list_tasks(
        self,
        task_list_id: str,
        max_results: int = 100,
        show_completed: bool = True,
        show_hidden: bool = False,
        show_deleted: bool = False,
        due_min: Optional[str] = None,
        due_max: Optional[str] = None,
        completed_min: Optional[str] = None,
        completed_max: Optional[str] = None,
        updated_min: Optional[str] = None,
    ) -> str:
        """
        List all tasks within a specific task list, with optional filters.

        Args:
            task_list_id (str): The ID of the task list to fetch tasks from.
            max_results (int): Maximum number of tasks to return (default: 100, max: 100).
            show_completed (bool): Include completed tasks (default: True).
            show_hidden (bool): Include tasks hidden by a previous clear (default: False).
            show_deleted (bool): Include soft-deleted tasks (default: False).
            due_min (Optional[str]): Lower bound for task due date (RFC 3339 timestamp).
            due_max (Optional[str]): Upper bound for task due date (RFC 3339 timestamp).
            completed_min (Optional[str]): Lower bound for completion date (RFC 3339 timestamp).
            completed_max (Optional[str]): Upper bound for completion date (RFC 3339 timestamp).
            updated_min (Optional[str]): Only return tasks updated after this timestamp (RFC 3339).

        Returns:
            str: JSON string containing the list of tasks or an error message.
        """
        try:
            service = cast(Resource, self.service)
            params: Dict[str, Any] = {
                "tasklist": task_list_id,
                "maxResults": min(max_results, 100),
                "showCompleted": show_completed,
                "showHidden": show_hidden,
                "showDeleted": show_deleted,
            }
            if due_min is not None:
                params["dueMin"] = due_min
            if due_max is not None:
                params["dueMax"] = due_max
            if completed_min is not None:
                params["completedMin"] = completed_min
            if completed_max is not None:
                params["completedMax"] = completed_max
            if updated_min is not None:
                params["updatedMin"] = updated_min

            response = service.tasks().list(**params).execute()
            tasks = response.get("items", [])
            if not tasks:
                return json.dumps({"message": "No tasks found."})
            return json.dumps(tasks)
        except HttpError as error:
            log_error(f"Failed to list tasks in {task_list_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def get_task(self, task_list_id: str, task_id: str) -> str:
        """
        Retrieve a single task by its ID.

        Args:
            task_list_id (str): The ID of the task list containing the task.
            task_id (str): The ID of the task to fetch.

        Returns:
            str: JSON string containing the task or an error message.
        """
        try:
            service = cast(Resource, self.service)
            task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
            return json.dumps(task)
        except HttpError as error:
            log_error(f"Failed to get task {task_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def create_task_list(self, title: str) -> str:
        """
        Create a new task list.

        Args:
            title (str): The name of the new task list (max 1024 characters).

        Returns:
            str: JSON string containing the created task list or an error message.
        """
        try:
            service = cast(Resource, self.service)
            task_list = service.tasklists().insert(body={"title": title}).execute()
            log_debug(f"Task list created: {task_list.get('id')}")
            return json.dumps(task_list)
        except HttpError as error:
            log_error(f"Failed to create task list: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def update_task_list(self, task_list_id: str, title: str) -> str:
        """
        Rename an existing task list.

        Args:
            task_list_id (str): The ID of the task list to rename.
            title (str): The new name of the task list (max 1024 characters).

        Returns:
            str: JSON string containing the updated task list or an error message.
        """
        try:
            service = cast(Resource, self.service)
            updated = service.tasklists().patch(tasklist=task_list_id, body={"title": title}).execute()
            log_debug(f"Task list {task_list_id} renamed to '{title}'")
            return json.dumps(updated)
        except HttpError as error:
            log_error(f"Failed to update task list {task_list_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def delete_task_list(self, task_list_id: str) -> str:
        """
        Delete an entire task list and all its tasks. Irreversible.

        Args:
            task_list_id (str): The ID of the task list to delete.

        Returns:
            str: JSON string confirming deletion or an error message.
        """
        try:
            service = cast(Resource, self.service)
            service.tasklists().delete(tasklist=task_list_id).execute()
            log_debug(f"Task list {task_list_id} deleted")
            return json.dumps({"success": True, "message": f"Task list {task_list_id} deleted."})
        except HttpError as error:
            log_error(f"Failed to delete task list {task_list_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def create_task(
        self,
        task_list_id: str,
        title: str,
        notes: Optional[str] = None,
        due: Optional[str] = None,
        parent: Optional[str] = None,
        previous: Optional[str] = None,
    ) -> str:
        """
        Create a new task in a task list.

        Args:
            task_list_id (str): The ID of the task list to add the task to.
            title (str): The title of the task (max 1024 characters).
            notes (Optional[str]): Free-text description of the task (max 8192 characters).
            due (Optional[str]): Due date as an RFC 3339 timestamp (e.g. "2026-12-31T00:00:00Z").
            parent (Optional[str]): Parent task ID to create this task as a subtask.
            previous (Optional[str]): Sibling task ID to insert after. If omitted, the task is placed first.

        Returns:
            str: JSON string containing the created task or an error message.
        """
        try:
            body: Dict[str, Any] = {"title": title}
            if notes is not None:
                body["notes"] = notes
            if due is not None:
                body["due"] = due

            params: Dict[str, Any] = {"tasklist": task_list_id, "body": body}
            if parent is not None:
                params["parent"] = parent
            if previous is not None:
                params["previous"] = previous

            service = cast(Resource, self.service)
            task = service.tasks().insert(**params).execute()
            log_debug(f"Task created: {task.get('id')} in {task_list_id}")
            return json.dumps(task)
        except HttpError as error:
            log_error(f"Failed to create task: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def update_task(
        self,
        task_list_id: str,
        task_id: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        due: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str:
        """
        Update fields on an existing task. Only provided fields are changed.

        Args:
            task_list_id (str): The ID of the task list containing the task.
            task_id (str): The ID of the task to update.
            title (Optional[str]): New task title (max 1024 characters).
            notes (Optional[str]): New task notes (max 8192 characters).
            due (Optional[str]): New due date as an RFC 3339 timestamp.
            status (Optional[str]): New status: "needsAction" or "completed".

        Returns:
            str: JSON string containing the updated task or an error message.
        """
        if status is not None and status not in ("needsAction", "completed"):
            return json.dumps({"error": "status must be 'needsAction' or 'completed'"})

        body: Dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if notes is not None:
            body["notes"] = notes
        if due is not None:
            body["due"] = due
        if status is not None:
            body["status"] = status

        if not body:
            return json.dumps({"error": "At least one field must be provided to update."})

        try:
            service = cast(Resource, self.service)
            updated = service.tasks().patch(tasklist=task_list_id, task=task_id, body=body).execute()
            log_debug(f"Task {task_id} updated")
            return json.dumps(updated)
        except HttpError as error:
            log_error(f"Failed to update task {task_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def complete_task(self, task_list_id: str, task_id: str) -> str:
        """
        Mark a task as completed. Convenience wrapper around update_task.

        Args:
            task_list_id (str): The ID of the task list containing the task.
            task_id (str): The ID of the task to mark complete.

        Returns:
            str: JSON string containing the updated task or an error message.
        """
        try:
            service = cast(Resource, self.service)
            updated = service.tasks().patch(tasklist=task_list_id, task=task_id, body={"status": "completed"}).execute()
            log_debug(f"Task {task_id} marked complete")
            return json.dumps(updated)
        except HttpError as error:
            log_error(f"Failed to complete task {task_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def move_task(
        self,
        task_list_id: str,
        task_id: str,
        parent: Optional[str] = None,
        previous: Optional[str] = None,
        destination_task_list_id: Optional[str] = None,
    ) -> str:
        """
        Move a task to a new position, parent, or task list.

        Args:
            task_list_id (str): The current task list ID.
            task_id (str): The ID of the task to move.
            parent (Optional[str]): New parent task ID. Use None to make the task a top-level task.
            previous (Optional[str]): New sibling to insert after. Use None to move to the top.
            destination_task_list_id (Optional[str]): Target task list ID if moving between lists.

        Returns:
            str: JSON string containing the moved task or an error message.
        """
        try:
            params: Dict[str, Any] = {"tasklist": task_list_id, "task": task_id}
            if parent is not None:
                params["parent"] = parent
            if previous is not None:
                params["previous"] = previous
            if destination_task_list_id is not None:
                params["destinationTasklist"] = destination_task_list_id

            service = cast(Resource, self.service)
            moved = service.tasks().move(**params).execute()
            log_debug(f"Task {task_id} moved")
            return json.dumps(moved)
        except HttpError as error:
            log_error(f"Failed to move task {task_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def delete_task(self, task_list_id: str, task_id: str) -> str:
        """
        Delete a task from a task list. Irreversible.

        Args:
            task_list_id (str): The ID of the task list containing the task.
            task_id (str): The ID of the task to delete.

        Returns:
            str: JSON string confirming deletion or an error message.
        """
        try:
            service = cast(Resource, self.service)
            service.tasks().delete(tasklist=task_list_id, task=task_id).execute()
            log_debug(f"Task {task_id} deleted")
            return json.dumps({"success": True, "message": f"Task {task_id} deleted."})
        except HttpError as error:
            log_error(f"Failed to delete task {task_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})

    @authenticate
    def clear_completed_tasks(self, task_list_id: str) -> str:
        """
        Hide all completed tasks from the default view of a task list.
        The tasks are not deleted — they are marked as hidden and can still be fetched
        via list_tasks with show_hidden=True.

        Args:
            task_list_id (str): The ID of the task list to clear.

        Returns:
            str: JSON string confirming the clear or an error message.
        """
        try:
            service = cast(Resource, self.service)
            service.tasks().clear(tasklist=task_list_id).execute()
            log_debug(f"Task list {task_list_id} cleared of completed tasks")
            return json.dumps({"success": True, "message": f"Completed tasks cleared from {task_list_id}."})
        except HttpError as error:
            log_error(f"Failed to clear task list {task_list_id}: {error}")
            return json.dumps({"error": f"An error occurred: {error}"})
