import json
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from redminelib import Redmine
except ImportError:
    raise ImportError("`python-redmine` not installed. Please install using `pip install python-redmine`")


class RedmineTools(Toolkit):
    def __init__(
        self,
        server_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        enable_get_issue: bool = True,
        enable_create_issue: bool = True,
        enable_update_issue: bool = True,
        enable_search_issues: bool = True,
        enable_add_comment: bool = True,
        enable_log_time: bool = True,
        enable_list_projects: bool = True,
        enable_list_users: bool = True,
        enable_list_project_members: bool = True,
        enable_list_versions: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.server_url = server_url or getenv("REDMINE_SERVER_URL")
        self.username = username or getenv("REDMINE_USERNAME")
        self.password = password or getenv("REDMINE_PASSWORD")
        self.token = token or getenv("REDMINE_TOKEN")

        if not self.server_url:
            raise ValueError("Redmine server URL not provided.")

        # Initialize Redmine client. raise_attr_exception=False so that missing optional fields
        # (e.g. an unassigned issue's assigned_to) return None instead of raising.
        if self.token:
            self.redmine = Redmine(url=self.server_url, key=self.token, raise_attr_exception=False)
        elif self.username and self.password:
            self.redmine = Redmine(
                url=self.server_url, username=self.username, password=self.password, raise_attr_exception=False
            )
        else:
            self.redmine = Redmine(url=self.server_url, raise_attr_exception=False)

        tools: List[Any] = []
        if enable_get_issue or all:
            tools.append(self.get_issue)
        if enable_create_issue or all:
            tools.append(self.create_issue)
        if enable_update_issue or all:
            tools.append(self.update_issue)
        if enable_search_issues or all:
            tools.append(self.search_issues)
        if enable_add_comment or all:
            tools.append(self.add_comment)
        if enable_log_time or all:
            tools.append(self.log_time)
        if enable_list_projects or all:
            tools.append(self.list_projects)
        if enable_list_users or all:
            tools.append(self.list_users)
        if enable_list_project_members or all:
            tools.append(self.list_project_members)
        if enable_list_versions or all:
            tools.append(self.list_versions)

        super().__init__(name="redmine_tools", tools=tools, **kwargs)

    def _to_int(self, issue_id: str) -> int:
        try:
            return int(issue_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid issue id: {issue_id!r}")

    def _resolve_name(self, name: str, resources: Any, label: str) -> Tuple[Optional[int], Optional[str]]:
        """Resolve a resource name to its id, matching case-insensitively.

        Returns a tuple of (resolved_id, error_json). Exactly one is not None.
        """
        mapping = {resource.name.lower(): resource.id for resource in resources}
        resolved = mapping.get(name.lower())
        if resolved is None:
            return None, json.dumps({"error": f"Unknown {label} '{name}'. Available: {sorted(mapping)}"})
        return resolved, None

    def get_issue(self, issue_id: str, include_comments: bool = False) -> str:
        """Retrieve issue details from Redmine.

        Args:
            issue_id (str): The numeric id of the issue to retrieve.
            include_comments (bool, optional): Whether to include the issue's comments (journal notes). Defaults to False.

        Returns:
            str: A JSON string containing issue details.
        """
        try:
            params = {"include": "journals"} if include_comments else {}
            issue = self.redmine.issue.get(self._to_int(issue_id), **params)
            issue_details = {
                "id": issue.id,
                "project": str(issue.project) if issue.project else "",
                "tracker": str(issue.tracker) if issue.tracker else "",
                "status": str(issue.status) if issue.status else "",
                "priority": str(issue.priority) if issue.priority else "",
                "author": str(issue.author) if issue.author else "",
                "assignee": str(issue.assigned_to) if issue.assigned_to else "Unassigned",
                "subject": issue.subject,
                "description": issue.description or "",
                "done_ratio": issue.done_ratio,
                "version": str(issue.fixed_version) if issue.fixed_version else "",
                "parent_id": getattr(issue.parent, "id", None) if issue.parent else None,
                "estimated_hours": issue.estimated_hours,
            }
            if include_comments:
                issue_details["comments"] = [
                    journal.notes for journal in issue.journals if getattr(journal, "notes", "")
                ]
            log_debug(f"Issue details retrieved for {issue_id}")
            return json.dumps(issue_details)
        except Exception as e:
            log_error(f"Error retrieving issue {issue_id}")
            return json.dumps({"error": str(e)})

    def create_issue(
        self,
        project_id: str,
        subject: str,
        description: str,
        tracker: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to_id: Optional[int] = None,
        version_id: Optional[int] = None,
        parent_issue_id: Optional[int] = None,
        estimated_hours: Optional[float] = None,
        start_date: Optional[str] = None,
        due_date: Optional[str] = None,
    ) -> str:
        """Create a new issue in Redmine.

        Args:
            project_id (str): The identifier of the project in which to create the issue.
            subject (str): The subject (title) of the issue.
            description (str): The description of the issue.
            tracker (str, optional): The tracker name for the issue (e.g. 'Bug', 'Feature', 'Support'). The project default is used when omitted.
            priority (str, optional): The priority name for the issue (e.g. 'Low', 'Normal', 'High'). The project default is used when omitted.
            assigned_to_id (int, optional): The id of the user to assign the issue to.
            version_id (int, optional): The id of the target version (sprint/milestone). Use list_versions to resolve a version name to its id.
            parent_issue_id (int, optional): The id of the parent issue, to create this issue as a subtask.
            estimated_hours (float, optional): The estimated time to complete the issue, in hours.
            start_date (str, optional): The start date in ISO format (YYYY-MM-DD).
            due_date (str, optional): The due date in ISO format (YYYY-MM-DD).

        Returns:
            str: A JSON string with the new issue's id and URL.
        """
        try:
            fields: Dict[str, Any] = {"project_id": project_id, "subject": subject, "description": description}
            if tracker:
                tracker_id, error = self._resolve_name(tracker, self.redmine.tracker.all(), "tracker")
                if error:
                    return error
                fields["tracker_id"] = tracker_id
            if priority:
                priority_id, error = self._resolve_name(
                    priority, self.redmine.enumeration.filter(resource="issue_priorities"), "priority"
                )
                if error:
                    return error
                fields["priority_id"] = priority_id
            if assigned_to_id:
                fields["assigned_to_id"] = assigned_to_id
            if version_id:
                fields["fixed_version_id"] = version_id
            if parent_issue_id:
                fields["parent_issue_id"] = parent_issue_id
            if estimated_hours is not None:
                fields["estimated_hours"] = estimated_hours
            if start_date:
                fields["start_date"] = start_date
            if due_date:
                fields["due_date"] = due_date
            new_issue = self.redmine.issue.create(**fields)
            issue_url = f"{self.server_url}/issues/{new_issue.id}"
            log_debug(f"Issue created with id: {new_issue.id}")
            return json.dumps({"id": new_issue.id, "url": issue_url})
        except Exception as e:
            log_error(f"Error creating issue in project {project_id}")
            return json.dumps({"error": str(e)})

    def update_issue(
        self,
        issue_id: str,
        subject: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        tracker: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to_id: Optional[int] = None,
        done_ratio: Optional[int] = None,
        version_id: Optional[int] = None,
        parent_issue_id: Optional[int] = None,
        estimated_hours: Optional[float] = None,
        start_date: Optional[str] = None,
        due_date: Optional[str] = None,
    ) -> str:
        """Update an existing issue in Redmine.

        Only the provided fields are changed. Use this to move an issue to a new status, reassign it, or set its priority.

        Args:
            issue_id (str): The numeric id of the issue to update.
            subject (str, optional): The new subject (title) of the issue.
            description (str, optional): The new description of the issue.
            status (str, optional): The new status name (e.g. 'In Progress', 'Resolved', 'Closed').
            tracker (str, optional): The new tracker name (e.g. 'Bug', 'Feature', 'Support').
            priority (str, optional): The new priority name (e.g. 'Low', 'Normal', 'High').
            assigned_to_id (int, optional): The id of the user to assign the issue to.
            done_ratio (int, optional): The completion percentage (0-100). Ignored for parent issues, whose value is computed from their subtasks.
            version_id (int, optional): The id of the target version (sprint/milestone). Use list_versions to resolve a version name to its id.
            parent_issue_id (int, optional): The id of the parent issue, to make this issue a subtask.
            estimated_hours (float, optional): The estimated time to complete the issue, in hours.
            start_date (str, optional): The start date in ISO format (YYYY-MM-DD).
            due_date (str, optional): The due date in ISO format (YYYY-MM-DD).

        Returns:
            str: A JSON string indicating success or containing an error message.
        """
        try:
            fields: Dict[str, Any] = {}
            if subject:
                fields["subject"] = subject
            if description is not None:
                fields["description"] = description
            if status:
                status_id, error = self._resolve_name(status, self.redmine.issue_status.all(), "status")
                if error:
                    return error
                fields["status_id"] = status_id
            if tracker:
                tracker_id, error = self._resolve_name(tracker, self.redmine.tracker.all(), "tracker")
                if error:
                    return error
                fields["tracker_id"] = tracker_id
            if priority:
                priority_id, error = self._resolve_name(
                    priority, self.redmine.enumeration.filter(resource="issue_priorities"), "priority"
                )
                if error:
                    return error
                fields["priority_id"] = priority_id
            if assigned_to_id:
                fields["assigned_to_id"] = assigned_to_id
            if done_ratio is not None:
                fields["done_ratio"] = done_ratio
            if version_id:
                fields["fixed_version_id"] = version_id
            if parent_issue_id:
                fields["parent_issue_id"] = parent_issue_id
            if estimated_hours is not None:
                fields["estimated_hours"] = estimated_hours
            if start_date:
                fields["start_date"] = start_date
            if due_date:
                fields["due_date"] = due_date
            if not fields:
                return json.dumps({"error": "No fields provided to update."})
            self.redmine.issue.update(self._to_int(issue_id), **fields)
            log_debug(f"Issue {issue_id} updated")
            return json.dumps({"status": "success", "issue_id": issue_id})
        except Exception as e:
            log_error(f"Error updating issue {issue_id}")
            return json.dumps({"error": str(e)})

    def search_issues(
        self,
        pattern: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        tracker: Optional[str] = None,
        assigned_to_id: Optional[int] = None,
        max_results: int = 50,
    ) -> str:
        """Search for issues, optionally filtering by subject, project, status, tracker and assignee.

        Args:
            pattern (str, optional): Text to match against issue subjects.
            project_id (str, optional): Restrict the search to this project identifier.
            status (str, optional): Filter by status: 'open', 'closed', 'all', or a status name (e.g. 'In Progress').
            tracker (str, optional): Filter by tracker name (e.g. 'Bug', 'Feature', 'Support').
            assigned_to_id (int, optional): Filter by the id of the assigned user.
            max_results (int, optional): Maximum number of results to return. Defaults to 50.

        Returns:
            str: A JSON string containing a list of dictionaries with issue details.
        """
        try:
            filters: Dict[str, Any] = {"status_id": "*", "limit": max_results}
            if pattern:
                filters["subject"] = f"~{pattern}"
            if project_id:
                filters["project_id"] = project_id
            if assigned_to_id:
                filters["assigned_to_id"] = assigned_to_id
            if tracker:
                tracker_id, error = self._resolve_name(tracker, self.redmine.tracker.all(), "tracker")
                if error:
                    return error
                filters["tracker_id"] = tracker_id
            if status:
                lowered = status.lower()
                if lowered in ("open", "closed"):
                    filters["status_id"] = lowered
                elif lowered in ("all", "*"):
                    filters["status_id"] = "*"
                else:
                    status_id, error = self._resolve_name(status, self.redmine.issue_status.all(), "status")
                    if error:
                        return error
                    filters["status_id"] = status_id
            issues = self.redmine.issue.filter(**filters)
            results = []
            for issue in issues:
                results.append(
                    {
                        "id": issue.id,
                        "subject": issue.subject,
                        "tracker": str(issue.tracker) if issue.tracker else "",
                        "status": str(issue.status) if issue.status else "",
                        "priority": str(issue.priority) if issue.priority else "",
                        "assignee": str(issue.assigned_to) if issue.assigned_to else "Unassigned",
                    }
                )
            log_debug(f"Found {len(results)} issues")
            return json.dumps(results)
        except Exception as e:
            log_error("Error searching issues")
            return json.dumps({"error": str(e)})

    def add_comment(self, issue_id: str, comment: str, private_notes: bool = False) -> str:
        """Add a comment to an issue.

        Args:
            issue_id (str): The numeric id of the issue.
            comment (str): The comment text.
            private_notes (bool, optional): Whether the comment is a private note visible only to users with permission. Defaults to False.

        Returns:
            str: A JSON string indicating success or containing an error message.
        """
        if not comment or not comment.strip():
            return json.dumps({"error": "comment cannot be empty"})
        try:
            self.redmine.issue.update(self._to_int(issue_id), notes=comment, private_notes=private_notes)
            log_debug(f"Comment added to issue {issue_id}")
            return json.dumps({"status": "success", "issue_id": issue_id})
        except Exception as e:
            log_error(f"Error adding comment to issue {issue_id}")
            return json.dumps({"error": str(e)})

    def log_time(
        self,
        issue_id: str,
        hours: float,
        activity: Optional[str] = None,
        comment: str = "",
        spent_on: Optional[str] = None,
    ) -> str:
        """Log time spent on an issue.

        Args:
            issue_id (str): The numeric id of the issue to log time against.
            hours (float): The number of hours spent. Must be greater than 0.
            activity (str, optional): The activity name (e.g. 'Design', 'Development'). Required unless the Redmine instance defines a default activity.
            comment (str, optional): A short description of the work done.
            spent_on (str, optional): The date the time was spent, in ISO format (YYYY-MM-DD). Defaults to today.

        Returns:
            str: A JSON string with the created time entry id, or an error message.
        """
        if hours <= 0:
            return json.dumps({"error": "hours must be greater than 0"})
        try:
            fields: Dict[str, Any] = {"issue_id": self._to_int(issue_id), "hours": hours}
            activities = self.redmine.enumeration.filter(resource="time_entry_activities")
            if activity:
                activity_id, error = self._resolve_name(activity, activities, "activity")
                if error:
                    return error
                fields["activity_id"] = activity_id
            elif not any(getattr(item, "is_default", False) for item in activities):
                return json.dumps(
                    {
                        "error": "activity is required (this Redmine instance defines no default activity). "
                        f"Available: {sorted(item.name.lower() for item in activities)}"
                    }
                )
            if comment:
                fields["comments"] = comment
            if spent_on:
                fields["spent_on"] = spent_on
            time_entry = self.redmine.time_entry.create(**fields)
            log_debug(f"Logged {hours}h on issue {issue_id}")
            return json.dumps({"id": time_entry.id, "issue_id": issue_id, "hours": hours})
        except Exception as e:
            log_error(f"Error logging time on issue {issue_id}")
            return json.dumps({"error": str(e)})

    def list_projects(self) -> str:
        """List the projects available on the Redmine server.

        Returns:
            str: A JSON string containing a list of projects with their id, identifier and name.
        """
        try:
            projects = [
                {"id": project.id, "identifier": project.identifier, "name": project.name}
                for project in self.redmine.project.all()
            ]
            log_debug(f"Found {len(projects)} projects")
            return json.dumps(projects)
        except Exception as e:
            log_error("Error listing projects")
            return json.dumps({"error": str(e)})

    def list_users(self) -> str:
        """List the active users on the Redmine server.

        Use this to resolve an assignee name to the numeric id required by create_issue and update_issue.
        This requires an admin token; with a non-admin token use list_project_members instead.

        Returns:
            str: A JSON string containing a list of users with their id, name and login.
        """
        try:
            users = [
                {"id": user.id, "name": f"{user.firstname} {user.lastname}".strip(), "login": user.login}
                for user in self.redmine.user.all()
            ]
            log_debug(f"Found {len(users)} users")
            return json.dumps(users)
        except Exception as e:
            log_error("Error listing users")
            return json.dumps({"error": str(e)})

    def list_project_members(self, project_id: str) -> str:
        """List the users who are members of a project.

        An issue can only be assigned to a member of its project, so use this to find valid assignee ids.

        Args:
            project_id (str): The identifier of the project.

        Returns:
            str: A JSON string containing a list of members with their id and name.
        """
        try:
            members = []
            for membership in self.redmine.project_membership.filter(project_id=project_id):
                user = getattr(membership, "user", None)
                if user:
                    members.append({"id": user.id, "name": str(user)})
            log_debug(f"Found {len(members)} members in project {project_id}")
            return json.dumps(members)
        except Exception as e:
            log_error(f"Error listing members of project {project_id}")
            return json.dumps({"error": str(e)})

    def list_versions(self, project_id: str) -> str:
        """List the versions (sprints/milestones) of a project.

        Use this to resolve a version name to the numeric id required by create_issue and update_issue.

        Args:
            project_id (str): The identifier of the project.

        Returns:
            str: A JSON string containing a list of versions with their id, name and status.
        """
        try:
            versions = [
                {"id": version.id, "name": version.name, "status": str(getattr(version, "status", ""))}
                for version in self.redmine.version.filter(project_id=project_id)
            ]
            log_debug(f"Found {len(versions)} versions in project {project_id}")
            return json.dumps(versions)
        except Exception as e:
            log_error(f"Error listing versions of project {project_id}")
            return json.dumps({"error": str(e)})
