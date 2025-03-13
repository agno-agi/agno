import json
import os
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from todoist_api_python.api import TodoistAPI
except ImportError:
    raise ImportError("`todoist-api-python` not installed. Please install using `pip install todoist-api-python`")


class TodoistTools(Toolkit):
    """A toolkit for interacting with Todoist tasks and projects."""

    def __init__(
        self,
        api_token: Optional[str] = None,
        create_task: bool = True,
        get_task: bool = True,
        update_task: bool = True,
        close_task: bool = True,
        delete_task: bool = True,
        get_active_tasks: bool = True,
        get_projects: bool = True,
    ):
        """Initialize the Todoist toolkit.

        Args:
            api_token: Optional Todoist API token. If not provided, will look for TODOIST_API_TOKEN env var
            create_task: Whether to register the create_task function
            get_task: Whether to register the get_task function
            update_task: Whether to register the update_task function
            close_task: Whether to register the close_task function
            delete_task: Whether to register the delete_task function
            get_active_tasks: Whether to register the get_active_tasks function
            get_projects: Whether to register the get_projects function
        """
        super().__init__(name="todoist")

        self.api_token = api_token or os.getenv("TODOIST_API_TOKEN")
        if not self.api_token:
            raise ValueError("TODOIST_API_TOKEN not set. Please set the TODOIST_API_TOKEN environment variable.")

        self.api = TodoistAPI(self.api_token)

        # Register enabled functions
        if create_task:
            self.register(self.create_task)
        if get_task:
            self.register(self.get_task)
        if update_task:
            self.register(self.update_task)
        if close_task:
            self.register(self.close_task)
        if delete_task:
            self.register(self.delete_task)
        if get_active_tasks:
            self.register(self.get_active_tasks)
        if get_projects:
            self.register(self.get_projects)

    def _task_to_dict(self, task: Any) -> Dict[str, Any]:
        """Convert a Todoist task to a dictionary with proper typing."""
        task_dict: Dict[str, Any] = {
            "id": task.id,
            "content": task.content,
            "description": task.description,
            "project_id": task.project_id,
            "section_id": task.section_id,
            "parent_id": task.parent_id,
            "order": task.order,
            "priority": task.priority,
            "url": task.url,
            "comment_count": task.comment_count,
            "creator_id": task.creator_id,
            "created_at": task.created_at,
            "labels": task.labels,
        }
        if task.due:
            task_dict["due"] = {
                "date": task.due.date,
                "string": task.due.string,
                "datetime": task.due.datetime,
                "timezone": task.due.timezone,
            }
        return task_dict

    def create_task(
        self,
        content: str,
        project_id: Optional[str] = None,
        due_string: Optional[str] = None,
        priority: Optional[int] = None,
        labels: Optional[List[str]] = None,
    ) -> str:
        """
        Create a new task in Todoist.

        Args:
            content: The task content/description
            project_id: Optional ID of the project to add the task to
            due_string: Optional due date in natural language (e.g., "tomorrow at 12:00")
            priority: Optional priority level (1-4, where 4 is highest)
            labels: Optional list of label names to apply to the task

        Returns:
            str: JSON string containing the created task
        """
        try:
            task = self.api.add_task(
                content=content, project_id=project_id, due_string=due_string, priority=priority, labels=labels or []
            )
            # Convert task to a dictionary and handle the Due object
            task_dict = self._task_to_dict(task)
            return json.dumps(task_dict)
        except Exception as e:
            logger.error(f"Failed to create task: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_task(self, task_id: str) -> str:
        """Get a specific task by ID."""
        try:
            task = self.api.get_task(task_id)
            task_dict = self._task_to_dict(task)
            return json.dumps(task_dict)
        except Exception as e:
            logger.error(f"Failed to get task: {str(e)}")
            return json.dumps({"error": str(e)})

    def update_task(self, task_id: str, **kwargs) -> str:
        """
        Update an existing task.

        Args:
            task_id: The ID of the task to update
            **kwargs: Any task properties to update (content, due_string, priority, etc.)
                If a nested 'kwargs' dictionary is provided, its contents will be used instead.

        Returns:
            str: JSON string containing success status
        """
        try:
            # Check if there's a nested kwargs dictionary and use it if present
            if len(kwargs) == 1 and "kwargs" in kwargs and isinstance(kwargs["kwargs"], dict):
                kwargs = kwargs["kwargs"]

            success = self.api.update_task(task_id=task_id, **kwargs)
            return json.dumps({"success": success})
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to update task: {error_msg}")
            return json.dumps({"error": error_msg})

    def close_task(self, task_id: str) -> str:
        """Mark a task as completed."""
        try:
            success = self.api.close_task(task_id)
            return json.dumps({"success": success})
        except Exception as e:
            logger.error(f"Failed to close task: {str(e)}")
            return json.dumps({"error": str(e)})

    def delete_task(self, task_id: str) -> str:
        """Delete a task."""
        try:
            success = self.api.delete_task(task_id)
            return json.dumps({"success": success})
        except Exception as e:
            logger.error(f"Failed to delete task: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_active_tasks(self) -> str:
        """Get all active (not completed) tasks."""
        try:
            tasks = self.api.get_tasks()
            tasks_list = []
            for task in tasks:
                task_dict = self._task_to_dict(task)
                tasks_list.append(task_dict)
            return json.dumps(tasks_list)
        except Exception as e:
            logger.error(f"Failed to get active tasks: {str(e)}")
            return json.dumps({"error": str(e)})

    def get_projects(self) -> str:
        """Get all projects."""
        try:
            projects = self.api.get_projects()
            return json.dumps([project.__dict__ for project in projects])
        except Exception as e:
            logger.error(f"Failed to get projects: {str(e)}")
            return json.dumps({"error": str(e)})
