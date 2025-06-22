from os import getenv
from typing import Any, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_info, logger


class LinearTools(Toolkit):
    def __init__(
        self,
        get_user_details: bool = True,
        get_issue_details: bool = True,
        create_issue: bool = True,
        update_issue: bool = True,
        get_user_assigned_issues: bool = True,
        get_workflow_issues: bool = True,
        get_high_priority_issues: bool = True,
        **kwargs,
    ):
        self.api_token = getenv("LINEAR_API_KEY")

        if not self.api_token:
            api_error_message = "API token 'LINEAR_API_KEY' is missing. Please set it as an environment variable."
            logger.error(api_error_message)

        self.endpoint = "https://api.linear.app/graphql"
        self.headers = {"Authorization": f"{self.api_token}"}

        tools: List[Any] = []
        if get_user_details:
            tools.append(self.get_user_details)
        if get_issue_details:
            tools.append(self.get_issue_details)
        if create_issue:
            tools.append(self.create_issue)
        if update_issue:
            tools.append(self.update_issue)
        if get_user_assigned_issues:
            tools.append(self.get_user_assigned_issues)
        if get_workflow_issues:
            tools.append(self.get_workflow_issues)
        if get_high_priority_issues:
            tools.append(self.get_high_priority_issues)

        super().__init__(name="linear tools", tools=tools, **kwargs)

    def _execute_query(self, query, variables=None):
        """Helper method to execute GraphQL queries with optional variables."""

        try:
            response = requests.post(self.endpoint, json={"query": query, "variables": variables}, headers=self.headers)
            response.raise_for_status()

            data = response.json()

            if "errors" in data:
                logger.error(f"GraphQL Error: {data['errors']}")
                raise Exception(f"GraphQL Error: {data['errors']}")

            log_info("GraphQL query executed successfully.")
            return data.get("data")

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            raise

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise

    def get_user_details(self) -> Optional[str]:
        """
        Fetch authenticated user details.
        It will return the user's unique ID, name, and email address from the viewer object in the GraphQL response.

        Returns:
            str or None: A string containing user details like user id, name, and email.

        Raises:
            Exception: If an error occurs during the query execution or data retrieval.
        """

        query = """
        query Me {
          viewer {
            id
            name
            email
          }
        }
        """

        try:
            response = self._execute_query(query)

            if response.get("viewer"):
                user = response["viewer"]
                log_info(
                    f"Retrieved authenticated user details with name: {user['name']}, ID: {user['id']}, Email: {user['email']}"
                )
                return str(user)
            else:
                logger.error("Failed to retrieve the current user details")
                return None

        except Exception as e:
            logger.error(f"Error fetching authenticated user details: {e}")
            raise

    def get_issue_details(self, issue_id: str) -> Optional[str]:
        """
        Retrieve details of a specific issue by issue ID.

        Args:
            issue_id (str): The unique identifier of the issue to retrieve.

        Returns:
            str or None: A string containing issue details like issue id, issue title, and issue description.
                  Returns `None` if the issue is not found.

        Raises:
            Exception: If an error occurs during the query execution or data retrieval.
        """

        query = """
        query IssueDetails ($issueId: String!){
        issue(id: $issueId) {
          id
          title
          description
          }
        }
        """
        variables = {"issueId": issue_id}
        try:
            response = self._execute_query(query, variables)

            if response.get("issue"):
                issue = response["issue"]
                log_info(f"Issue '{issue['title']}' retrieved successfully with ID {issue['id']}.")
                return str(issue)
            else:
                logger.error(f"Failed to retrieve issue with ID {issue_id}.")
                return None

        except Exception as e:
            logger.error(f"Error retrieving issue with ID {issue_id}: {e}")
            raise

    def create_issue(
        self, title: str, description: str, team_id: str, project_id: str, assignee_id: str
    ) -> Optional[str]:
        """
        Create a new issue within a specific project and team.

        Args:
            title (str): The title of the new issue.
            description (str): The description of the new issue.
            team_id (str): The unique identifier of the team in which to create the issue.

        Returns:
            str or None: A string containing the created issue's details like issue id and issue title.
                  Returns `None` if the issue creation fails.

        Raises:
            Exception: If an error occurs during the mutation execution or data retrieval.
        """

        query = """
        mutation IssueCreate ($title: String!, $description: String!, $teamId: String!, $projectId: String!, $assigneeId: String!){
          issueCreate(
            input: { title: $title, description: $description, teamId: $teamId, projectId: $projectId, assigneeId: $assigneeId}
          ) {
            success
            issue {
              id
              title
              url
            }
          }
        }
        """

        variables = {
            "title": title,
            "description": description,
            "teamId": team_id,
            "projectId": project_id,
            "assigneeId": assignee_id,
        }
        try:
            response = self._execute_query(query, variables)
            log_info(f"Response: {response}")

            if response["issueCreate"]["success"]:
                issue = response["issueCreate"]["issue"]
                log_info(f"Issue '{issue['title']}' created successfully with ID {issue['id']}")
                return str(issue)
            else:
                logger.error("Issue creation failed.")
                return None

        except Exception as e:
            logger.error(f"Error creating issue '{title}' for team ID {team_id}: {e}")
            raise

    def update_issue(self, issue_id: str, title: Optional[str]) -> Optional[str]:
        """
        Update the title or state of a specific issue by issue ID.

        Args:
            issue_id (str): The unique identifier of the issue to update.
            title (str, optional): The new title for the issue. If None, the title remains unchanged.

        Returns:
            str or None: A string containing the updated issue's details with issue id, issue title, and issue state (which includes `id` and `name`).
                  Returns `None` if the update is unsuccessful.

        Raises:
            Exception: If an error occurs during the mutation execution or data retrieval.
        """

        query = """
        mutation IssueUpdate ($issueId: String!, $title: String!){
          issueUpdate(
            id: $issueId,
            input: { title: $title}
          ) {
            success
            issue {
              id
              title
              state {
                id
                name
              }
            }
          }
        }
        """
        variables = {"issueId": issue_id, "title": title}

        try:
            response = self._execute_query(query, variables)

            if response["issueUpdate"]["success"]:
                issue = response["issueUpdate"]["issue"]
                log_info(f"Issue ID {issue_id} updated successfully.")
                return str(issue)
            else:
                logger.error(f"Failed to update issue ID {issue_id}. Success flag was false.")
                return None

        except Exception as e:
            logger.error(f"Error updating issue ID {issue_id}: {e}")
            raise

    def get_user_assigned_issues(self, user_id: str) -> Optional[str]:
        """
        Retrieve issues assigned to a specific user by user ID.

        Args:
            user_id (str): The unique identifier of the user for whom to retrieve assigned issues.

        Returns:
            str or None: A string representing the assigned issues to user id,
            where each issue contains issue details (e.g., `id`, `title`).
            Returns None if the user or issues cannot be retrieved.

        Raises:
            Exception: If an error occurs while querying for the user's assigned issues.
        """

        query = """
        query UserAssignedIssues($userId: String!) {
        user(id: $userId) {
          id
          name
          assignedIssues {
            nodes {
              id
              title
              }
            }
          }
        }
        """
        variables = {"userId": user_id}

        try:
            response = self._execute_query(query, variables)

            if response.get("user"):
                user = response["user"]
                issues = user["assignedIssues"]["nodes"]
                log_info(f"Retrieved {len(issues)} issues assigned to user '{user['name']}' (ID: {user['id']}).")
                return str(issues)
            else:
                logger.error("Failed to retrieve user or issues.")
                return None

        except Exception as e:
            logger.error(f"Error retrieving issues for user ID {user_id}: {e}")
            raise

    def get_workflow_issues(self, workflow_id: str) -> Optional[str]:
        """
        Retrieve issues within a specific workflow state by workflow ID.

        Args:
            workflow_id (str): The unique identifier of the workflow state to retrieve issues from.

        Returns:
            str or None: A string representing the issues within the specified workflow state,
            where each issue contains details of an issue (e.g., `title`).
            Returns None if no issues are found or if the workflow state cannot be retrieved.

        Raises:
            Exception: If an error occurs while querying issues for the specified workflow state.
        """

        query = """
        query WorkflowStateIssues($workflowId: String!) {
        workflowState(id: $workflowId) {
          issues {
            nodes {
              title
              }
            }
          }
        }
        """
        variables = {"workflowId": workflow_id}
        try:
            response = self._execute_query(query, variables)

            if response.get("workflowState"):
                issues = response["workflowState"]["issues"]["nodes"]
                log_info(f"Retrieved {len(issues)} issues in workflow state ID {workflow_id}.")
                return str(issues)
            else:
                logger.error("Failed to retrieve issues for the specified workflow state.")
                return None

        except Exception as e:
            logger.error(f"Error retrieving issues for workflow state ID {workflow_id}: {e}")
            raise

    def get_high_priority_issues(self) -> Optional[str]:
        """
        Retrieve issues with a high priority (priority <= 2).

        Returns:
            str or None: A str representing high-priority issues, where it
            contains details of an issue (e.g., `id`, `title`, `priority`).
            Returns None if no issues are retrieved.

        Raises:
            Exception: If an error occurs during the query process.
        """

        query = """
        query HighPriorityIssues {
        issues(filter: {
          priority: { lte: 2 }
        }) {
          nodes {
            id
            title
            priority
            }
          }
        }
        """
        try:
            response = self._execute_query(query)

            if response.get("issues"):
                high_priority_issues = response["issues"]["nodes"]
                log_info(f"Retrieved {len(high_priority_issues)} high-priority issues.")
                return str(high_priority_issues)
            else:
                logger.error("Failed to retrieve high-priority issues.")
                return None

        except Exception as e:
            logger.error(f"Error retrieving high-priority issues: {e}")
            raise
