import json
import os
from typing import Optional, cast

from agno.tools import Toolkit
from agno.utils.log import logger

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
    ):
        super().__init__(name="jira_tools")

        self.server_url = server_url or os.getenv("JIRA_SERVER_URL")
        self.username = username or os.getenv("JIRA_USERNAME")
        self.password = password or os.getenv("JIRA_PASSWORD")
        self.token = token or os.getenv("JIRA_TOKEN")

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

        # Register methods
        self.register(self.get_issue)
        self.register(self.create_issue)
        self.register(self.search_issues)
        self.register(self.add_comment)
        # You can register more methods here

    def get_issue(self, issue_key: str) -> str:
        """
        Retrieves issue details from Jira.

        :param issue_key: The key of the issue to retrieve.
        :return: A JSON string containing issue details.
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
            logger.debug(f"Issue details retrieved for {issue_key}: {issue_details}")
            return json.dumps(issue_details)
        except Exception as e:
            logger.error(f"Error retrieving issue {issue_key}: {e}")
            return json.dumps({"error": str(e)})

    def create_issue(self, project_key: str, summary: str, description: str, issuetype: str = "Task") -> str:
        """
        Creates a new issue in Jira.

        :param project_key: The key of the project in which to create the issue.
        :param summary: The summary of the issue.
        :param description: The description of the issue.
        :param issuetype: The type of issue to create.
        :return: A JSON string with the new issue's key and URL.
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
            logger.debug(f"Issue created with key: {new_issue.key}")
            return json.dumps({"key": new_issue.key, "url": issue_url})
        except Exception as e:
            logger.error(f"Error creating issue in project {project_key}: {e}")
            return json.dumps({"error": str(e)})

    def search_issues(self, jql_str: str, max_results: int = 50) -> str:
        """
        Searches for issues using a JQL query.

        :param jql_str: The JQL query string.
        :param max_results: Maximum number of results to return.
        :return: A JSON string containing a list of dictionaries with issue details.
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
            logger.debug(f"Found {len(results)} issues for JQL '{jql_str}'")
            return json.dumps(results)
        except Exception as e:
            logger.error(f"Error searching issues with JQL '{jql_str}': {e}")
            return json.dumps([{"error": str(e)}])

    def add_comment(self, issue_key: str, comment: str) -> str:
        """
        Adds a comment to an issue.

        :param issue_key: The key of the issue.
        :param comment: The comment text.
        :return: A JSON string indicating success or containing an error message.
        """
        try:
            self.jira.add_comment(issue_key, comment)
            logger.debug(f"Comment added to issue {issue_key}")
            return json.dumps({"status": "success", "issue_key": issue_key})
        except Exception as e:
            logger.error(f"Error adding comment to issue {issue_key}: {e}")
            return json.dumps({"error": str(e)})
