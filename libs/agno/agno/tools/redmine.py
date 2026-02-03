import json
import os
from typing import Any, List, Optional, cast

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from redminelib import Redmine
except ImportError:
    raise ImportError("`REDMINE` not installed. Please install using `pip install python-redmine`")


def search_by_id(issues_resource_set, id):
    print(f"Searching by id {id}")
    found = []
    for issue in issues_resource_set:
        if int(id) == issue.id:
            found.append(issue)
    return found

def search_by_subject(issues_resource_set, pattern):
    print(f"Searching by pattern {pattern}")
    found = []
    pattern_lower = pattern.lower()
    for issue in issues_resource_set:
        if pattern_lower in issue.subject.lower():
            found.append(issue)
    return found

class RedmineTools(Toolkit):
    def __init__(
        self,
        server_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        **kwargs,
    ):
        self.server_url = server_url or os.getenv("REDMINE_SERVER_URL")
        self.username = username or os.getenv("REDMINE_USERNAME")
        self.password = password or os.getenv("REDMINE_PASSWORD")
        self.token = token or os.getenv("REDMINE_TOKEN")

        if not self.server_url:
            raise ValueError("REDMINE server URL not provided.")

        # Initialize REDMINE client
        if self.token:
            self.redmine = Redmine(url=self.server_url, key=self.token)
        elif self.username and self.password:
            self.redmine = Redmine(url=self.server_url, username=self.username, password=self.password)
        else:
            self.redmine = Redmine(url=self.server_url)

        tools: List[Any] = []
        tools.append(self.get_issue)
        tools.append(self.create_issue)
        tools.append(self.search_issues)
        tools.append(self.add_comment)

        super().__init__(name="redmine_tools", tools=tools, **kwargs)

    def get_issue(self, issue_key: str) -> str:
        """
        Retrieves issue details from Redmine.

        :param issue_key: The key of the issue to retrieve.
        :return: A JSON string containing issue details.
        """
        try:
            issues = self.redmine.issue.all()
            results = search_by_id(issues, issue_key)
            issue = results[0]
            issue_details = {
                "key": issue.id,
                "project": issue.project,
                "issuetype": issue.tracker,
                "reporter": issue.author,
                "summary": issue.subject,
                "description": issue.description or "",
            }
            log_debug(f"Issue details retrieved for {issue_key}: {issue_details}")
            return issue_details
        except Exception as e:
            logger.error(f"Error retrieving issue {issue_key}: {e}")
            return json.dumps({"error": str(e)})

    def create_issue(self, project_key: str, summary: str, description: str, assigned_to_id: int, issuetype: str = "Funcionalidade") -> str:
        """
        Creates a new issue in Redmine. Page #19 in the documentation

        :param project_key: The key of the project in which to create the issue.
        :param summary: The summary of the issue.
        :param description: The description of the issue.
        :param issuetype: The type of issue to create.
        :return: A JSON string with the new issue's key and URL.
        """
        tracker_list = {'Defeito': 1, 'Funcionalidade': 2, 'Suporte': 3}
        try:
            print(f"Creating issue in project {project_key} with summary {summary} and tracker {tracker_list[issuetype]} and issuetype { issuetype}")
            new_issue = self.redmine.issue.create(project_id= project_key, subject= summary, tracker_id= tracker_list[issuetype], description= description, assigned_to_id= assigned_to_id, watcher_user_ids= [assigned_to_id])
            issue_url = f"{self.server_url}/issues/{new_issue.id}"
            log_debug(f"Issue created with key: {new_issue.id}")
            return json.dumps({"key": new_issue.id, "url": issue_url})
        except Exception as e:
            logger.error(f"Error creating issue in project {project_key}: {e}")
            return json.dumps({"error": str(e)})

    def search_issues(self, pattern: str, max_results: int = 50) -> str:
        """
        Searches for issues using a pattern.

        :param pattern: The pattern string.
        :param max_results: Maximum number of results to return.
        :return: A list of dictionaries with issue details.
        """
        try:
            issues = self.redmine.issue.all(limit=max_results)
            results = search_by_subject(issues, pattern)
            log_debug(f"Found {len(results)} issues for pattern '{pattern}'")
            found = []
            for issue in results:
                # issue = cast(Issue, issue)
                issue_details = {
                    "key": issue.id,
                    "summary": issue.subject,
                    "status": issue.status,
                    "assignee": issue.assigned_to.name if issue.assigned_to else "Unassigned",
                }
                found.append(issue_details)
            return found
        except Exception as e:
            logger.error(f"Error searching issues with pattern '{pattern}': {e}")
            return json.dumps([{"error": str(e)}])

    def add_comment(self, issue_key: str, comment: str) -> str:
        """
        Adds a comment to an issue.

        :param issue_key: The key of the issue.
        :param comment: The comment text.
        :return: A JSON string indicating success or containing an error message.
        """
        try:
            self.redmine.issue.update(int(issue_key), notes=comment)
            log_debug(f"Comment added to issue {issue_key}")
            return json.dumps({"status": "success", "issue_key": issue_key})
        except Exception as e:
            logger.error(f"Error adding comment to issue {issue_key}: {e}")
            return json.dumps({"error": str(e)})

