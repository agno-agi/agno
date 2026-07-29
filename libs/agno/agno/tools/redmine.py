import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Tuple

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
        get_issue: bool = True,
        create_issue: bool = False,
        update_issue: bool = False,
        search_issues: bool = True,
        add_comment: bool = False,
        log_time: bool = False,
        list_projects: bool = True,
        list_users: bool = True,
        list_project_members: bool = True,
        list_versions: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Redmine toolkit for issue tracking operations.

        Connects to a Redmine server using API token or username/password auth.

        Args:
            server_url: Redmine server URL. Falls back to REDMINE_SERVER_URL env var.
            username: Username for basic auth. Falls back to REDMINE_USERNAME env var.
            password: Password for basic auth. Falls back to REDMINE_PASSWORD env var.
            token: API token (preferred). Falls back to REDMINE_TOKEN env var.
            get_issue: Enable the get_issue tool.
            create_issue: Enable the create_issue tool. Disabled by default (write op).
            update_issue: Enable the update_issue tool. Disabled by default (write op).
            search_issues: Enable the search_issues tool.
            add_comment: Enable the add_comment tool. Disabled by default (write op).
            log_time: Enable the log_time tool. Disabled by default (write op).
            list_projects: Enable the list_projects tool.
            list_users: Enable the list_users tool.
            list_project_members: Enable the list_project_members tool.
            list_versions: Enable the list_versions tool.
            all: Enable all tools.
        """
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

        tools: List[Callable] = []
        if all or get_issue:
            tools.append(self.get_issue)
        if all or create_issue:
            tools.append(self.create_issue)
        if all or update_issue:
            tools.append(self.update_issue)
        if all or search_issues:
            tools.append(self.search_issues)
        if all or add_comment:
            tools.append(self.add_comment)
        if all or log_time:
            tools.append(self.log_time)
        if all or list_projects:
            tools.append(self.list_projects)
        if all or list_users:
            tools.append(self.list_users)
        if all or list_project_members:
            tools.append(self.list_project_members)
        if all or list_versions:
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
            issue_id: The numeric id of the issue to retrieve.
            include_comments: Whether to include comments (journal notes).

        Returns:
            JSON with issue details including project, status, priority, assignee.
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
            project_id: Project identifier to create the issue in.
            subject: Issue title.
            description: Issue description.
            tracker: Tracker name (e.g., Bug, Feature, Support). Uses project default if omitted.
            priority: Priority name (e.g., Low, Normal, High). Uses project default if omitted.
            assigned_to_id: User ID to assign to. Use list_users or list_project_members to find.
            version_id: Target version ID. Use list_versions to find.
            parent_issue_id: Parent issue ID to create as subtask.
            estimated_hours: Estimated hours to complete.
            start_date: Start date (YYYY-MM-DD).
            due_date: Due date (YYYY-MM-DD).

        Returns:
            JSON with id and url of created issue.
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

        Only provided fields are changed. Use to change status, reassign, or update priority.

        Args:
            issue_id: Issue ID to update.
            subject: New title.
            description: New description.
            status: New status name (e.g., In Progress, Resolved, Closed).
            tracker: New tracker name (e.g., Bug, Feature, Support).
            priority: New priority name (e.g., Low, Normal, High).
            assigned_to_id: User ID to assign to.
            done_ratio: Completion percentage (0-100). Ignored for parent issues.
            version_id: Target version ID. Use list_versions to find.
            parent_issue_id: Parent issue ID to make this a subtask.
            estimated_hours: Estimated hours to complete.
            start_date: Start date (YYYY-MM-DD).
            due_date: Due date (YYYY-MM-DD).

        Returns:
            JSON with status success or error message.
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
        """Search for issues with optional filters.

        Args:
            pattern: Text to match against issue subjects.
            project_id: Restrict to this project identifier.
            status: Filter by open, closed, all, or status name (e.g., In Progress).
            tracker: Filter by tracker name (e.g., Bug, Feature, Support).
            assigned_to_id: Filter by assigned user ID.
            max_results: Maximum results to return.

        Returns:
            JSON list of issues with id, subject, tracker, status, priority, assignee.
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
            issue_id: Issue ID to comment on.
            comment: Comment text.
            private_notes: If True, only visible to users with permission.

        Returns:
            JSON with status success or error message.
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
            issue_id: Issue ID to log time against.
            hours: Hours spent (must be > 0).
            activity: Activity name (e.g., Design, Development). Required if no default.
            comment: Description of work done.
            spent_on: Date spent (YYYY-MM-DD). Defaults to today.

        Returns:
            JSON with time entry id or error message.
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
        """List projects available on the Redmine server.

        Returns:
            JSON list of projects with id, identifier, and name.
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
        """List active users on the Redmine server.

        Use to resolve assignee names to IDs for create_issue/update_issue.
        Requires admin token; use list_project_members for non-admin access.

        Returns:
            JSON list of users with id, name, and login.
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
        """List users who are members of a project.

        Use to find valid assignee IDs (issues can only be assigned to project members).

        Args:
            project_id: Project identifier.

        Returns:
            JSON list of members with id and name.
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
        """List versions (sprints/milestones) of a project.

        Use to resolve version names to IDs for create_issue/update_issue.

        Args:
            project_id: Project identifier.

        Returns:
            JSON list of versions with id, name, and status.
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
