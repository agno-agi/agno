import json
from os import getenv
from typing import Callable, List, Optional, cast

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from jira import JIRA, Issue
except ImportError:
    raise ImportError("`jira` not installed. Please install using `pip install jira`")


class JiraTools(Toolkit):
    def __init__(
        self,
        server_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        get_issue: bool = True,
        create_issue: bool = False,
        search_issues: bool = True,
        add_comment: bool = False,
        add_worklog: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Jira toolkit.

        Args:
            server_url: Jira server URL. Falls back to JIRA_SERVER_URL env var.
            username: Jira username. Falls back to JIRA_USERNAME env var.
            password: Jira password. Falls back to JIRA_PASSWORD env var.
            token: Jira API token. Falls back to JIRA_TOKEN env var.
            get_issue: Enable the get_issue tool. Defaults to True.
            create_issue: Enable the create_issue tool. Defaults to False
                (creates issues in the remote project).
            search_issues: Enable the search_issues tool. Defaults to True.
            add_comment: Enable the add_comment tool. Defaults to False
                (posts comments on the user's behalf).
            add_worklog: Enable the add_worklog tool. Defaults to False
                (writes worklog entries to the remote issue).
            all: Enable all tools.
        """
        self.server_url = server_url or getenv("JIRA_SERVER_URL")
        self.username = username or getenv("JIRA_USERNAME")
        self.password = password or getenv("JIRA_PASSWORD")
        self.token = token or getenv("JIRA_TOKEN")

        if not self.server_url:
            raise ValueError("JIRA server URL not provided.")

        # Initialize JIRA client
        if self.token and self.username:
            auth = (self.username, self.token)
        elif self.username and self.password:
            auth = (self.username, self.password)
        else:
            auth = None

        if auth:
            self.jira = JIRA(server=self.server_url, basic_auth=cast(tuple[str, str], auth))
        else:
            self.jira = JIRA(server=self.server_url)

        tools: List[Callable] = []
        if all or get_issue:
            tools.append(self.get_issue)
        if all or create_issue:
            tools.append(self.create_issue)
        if all or search_issues:
            tools.append(self.search_issues)
        if all or add_comment:
            tools.append(self.add_comment)
        if all or add_worklog:
            tools.append(self.add_worklog)

        super().__init__(name="jira_tools", tools=tools, **kwargs)

    def get_issue(self, issue_key: str) -> str:
        """Retrieve issue details from Jira.

        Args:
            issue_key: The key of the issue to retrieve (e.g., PROJ-123).

        Returns:
            JSON with issue details including key, project, type, summary.
        """
        try:
            issue = self.jira.issue(issue_key)
            issue = cast(Issue, issue)
            issue_details = {
                "key": issue.key,
                "project": issue.fields.project.key,
                "issuetype": issue.fields.issuetype.name,
                "reporter": issue.fields.reporter.displayName if issue.fields.reporter else "N/A",
                "summary": issue.fields.summary,
                "description": issue.fields.description or "",
            }
            log_debug(f"Issue details retrieved for {issue_key}: {issue_details}")
            return json.dumps(issue_details)
        except Exception as e:
            logger.exception(f"Error retrieving issue {issue_key}")
            return json.dumps({"error": str(e)})

    def create_issue(self, project_key: str, summary: str, description: str, issuetype: str = "Task") -> str:
        """Create a new issue in Jira.

        Args:
            project_key: The project key (e.g., PROJ).
            summary: The issue summary/title.
            description: The issue description.
            issuetype: Issue type. Defaults to Task.

        Returns:
            JSON with new issue key and URL.
        """
        try:
            issue_dict = {
                "project": {"key": project_key},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issuetype},
            }
            new_issue = self.jira.create_issue(fields=issue_dict)
            issue_url = f"{self.server_url}/browse/{new_issue.key}"
            log_debug(f"Issue created with key: {new_issue.key}")
            return json.dumps({"key": new_issue.key, "url": issue_url})
        except Exception as e:
            logger.exception(f"Error creating issue in project {project_key}")
            return json.dumps({"error": str(e)})

    def search_issues(self, jql_str: str, max_results: int = 50) -> str:
        """Search for issues using a JQL query.

        Args:
            jql_str: JQL query string (e.g., "project = PROJ AND status = Open").
            max_results: Maximum results to return. Defaults to 50.

        Returns:
            JSON list of issues with key, summary, status, assignee.
        """
        try:
            issues = self.jira.search_issues(jql_str, maxResults=max_results)
            results = []
            for issue in issues:
                issue = cast(Issue, issue)
                issue_details = {
                    "key": issue.key,
                    "summary": issue.fields.summary,
                    "status": issue.fields.status.name,
                    "assignee": issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned",
                }
                results.append(issue_details)
            log_debug(f"Found {len(results)} issues for JQL '{jql_str}'")
            return json.dumps(results)
        except Exception as e:
            logger.exception(f"Error searching issues with JQL '{jql_str}'")
            return json.dumps([{"error": str(e)}])

    def add_comment(self, issue_key: str, comment: str) -> str:
        """Add a comment to an issue.

        Args:
            issue_key: The issue key (e.g., PROJ-123).
            comment: The comment text.

        Returns:
            JSON with status and issue_key on success.
        """
        try:
            self.jira.add_comment(issue_key, comment)
            log_debug(f"Comment added to issue {issue_key}")
            return json.dumps({"status": "success", "issue_key": issue_key})
        except Exception as e:
            logger.exception(f"Error adding comment to issue {issue_key}")
            return json.dumps({"error": str(e)})

    def add_worklog(self, issue_key: str, time_spent: str, comment: Optional[str] = None) -> str:
        """Add a worklog entry to an issue.

        Args:
            issue_key: The issue key (e.g., PROJ-123).
            time_spent: Time spent in Jira format (e.g., "2h", "30m", "1d 4h").
            comment: Optional description of work done.

        Returns:
            JSON with status, issue_key, and time_spent on success.
        """
        try:
            self.jira.add_worklog(issue=issue_key, timeSpent=time_spent, comment=comment)
            log_debug(f"Worklog of '{time_spent}' added to issue {issue_key}")
            return json.dumps({"status": "success", "issue_key": issue_key, "time_spent": time_spent})
        except Exception as e:
            logger.exception(f"Error adding worklog to issue {issue_key}")
            return json.dumps({"error": str(e)})
