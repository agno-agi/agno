import json
from os import getenv
from typing import Callable, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger


class LinearTools(Toolkit):
    """Linear project management toolkit for issue tracking and team collaboration.

    Requires a Linear API key. Get one from Linear Settings > API > Personal API keys.
    Set LINEAR_API_KEY environment variable or pass api_key parameter.

    Example:
        from agno.tools.linear import LinearTools

        # Read-only by default
        tools = LinearTools()

        # Enable issue creation/updates
        tools = LinearTools(create_issue=True, update_issue=True)

        # Enable all tools
        tools = LinearTools(all=True)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        get_user_details: bool = True,
        get_teams_details: bool = True,
        get_issue_details: bool = True,
        create_issue: bool = False,
        update_issue: bool = False,
        get_user_assigned_issues: bool = True,
        get_workflow_issues: bool = True,
        get_high_priority_issues: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize LinearTools for project management and issue tracking.

        Args:
            api_key: Linear API key. Falls back to LINEAR_API_KEY env var.
            get_user_details: Enable get_user_details tool. Defaults to True.
            get_teams_details: Enable get_teams_details tool. Defaults to True.
            get_issue_details: Enable get_issue_details tool. Defaults to True.
            create_issue: Enable create_issue tool. Defaults to False (creates external records).
            update_issue: Enable update_issue tool. Defaults to False (modifies external records).
            get_user_assigned_issues: Enable get_user_assigned_issues tool. Defaults to True.
            get_workflow_issues: Enable get_workflow_issues tool. Defaults to True.
            get_high_priority_issues: Enable get_high_priority_issues tool. Defaults to True.
            all: Enable all tools. Defaults to False.
        """
        self.api_key = api_key or getenv("LINEAR_API_KEY")

        if not self.api_key:
            raise ValueError("Linear API key is required")

        self.endpoint = "https://api.linear.app/graphql"
        self.headers = {"Authorization": f"{self.api_key}"}

        tools: List[Callable] = []
        if all or get_user_details:
            tools.append(self.get_user_details)
        if all or get_teams_details:
            tools.append(self.get_teams_details)
        if all or get_issue_details:
            tools.append(self.get_issue_details)
        if all or create_issue:
            tools.append(self.create_issue)
        if all or update_issue:
            tools.append(self.update_issue)
        if all or get_user_assigned_issues:
            tools.append(self.get_user_assigned_issues)
        if all or get_workflow_issues:
            tools.append(self.get_workflow_issues)
        if all or get_high_priority_issues:
            tools.append(self.get_high_priority_issues)

        super().__init__(name="linear_tools", tools=tools, **kwargs)

    def _execute_query(self, query, variables=None):
        """Helper method to execute GraphQL queries with optional variables."""

        try:
            response = requests.post(self.endpoint, json={"query": query, "variables": variables}, headers=self.headers)
            response.raise_for_status()

            data = response.json()

            if "errors" in data:
                log_error(f"GraphQL Error: {data['errors']}")
                raise Exception(f"GraphQL Error: {data['errors']}")

            log_info("GraphQL query executed successfully.")
            return data.get("data")

        except requests.exceptions.RequestException:
            logger.exception("Request error")
            raise

        except Exception:
            logger.exception("Unexpected error")
            raise

    def get_user_details(self) -> str:
        """Fetch authenticated user details including ID, name, and email.

        Returns:
            JSON with user id, name, and email.
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
                return json.dumps(user)
            else:
                log_error("Failed to retrieve the current user details")
                return json.dumps({"error": "Failed to retrieve user details"})

        except Exception as e:
            logger.exception("Error fetching authenticated user details")
            return json.dumps({"error": f"Error fetching user details: {e}"})

    def get_teams_details(self) -> str:
        """Fetch the list of teams with their IDs and names.

        Returns:
            JSON array of teams with id and name.
        """
        query = """
        query Teams {
          teams {
            nodes {
              id
              name
            }
          }
        }
        """

        try:
            response = self._execute_query(query)

            if response.get("teams"):
                teams = response["teams"]["nodes"]
                log_info(f"Retrieved authenticated team details: {teams}")
                return json.dumps(teams)
            else:
                log_error("Failed to retrieve team details")
                return json.dumps({"error": "Failed to retrieve team details"})

        except Exception as e:
            logger.exception("Error fetching team details")
            return json.dumps({"error": f"Error fetching team details: {e}"})

    def get_issue_details(self, issue_id: str) -> str:
        """Retrieve details of a specific issue by issue ID.

        Args:
            issue_id: The unique identifier of the issue to retrieve.

        Returns:
            JSON with issue id, title, and description.
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
                return json.dumps(issue)
            else:
                log_error(f"Failed to retrieve issue with ID {issue_id}.")
                return json.dumps({"error": f"Issue with ID {issue_id} not found"})

        except Exception as e:
            logger.exception(f"Error retrieving issue with ID {issue_id}")
            return json.dumps({"error": f"Error retrieving issue: {e}"})

    def create_issue(
        self,
        title: str,
        description: str,
        team_id: str,
        project_id: Optional[str] = None,
        assignee_id: Optional[str] = None,
    ) -> str:
        """Create a new issue within a specific project and team.

        Args:
            title: The title of the new issue.
            description: The description of the new issue.
            team_id: The unique identifier of the team in which to create the issue.
            project_id: The ID of the project (optional).
            assignee_id: The ID of the assignee (optional).

        Returns:
            JSON with created issue id, title, and url.
        """
        query = """
        mutation IssueCreate ($title: String!, $description: String!, $teamId: String!, $projectId: String, $assigneeId: String){
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
        }
        if project_id is not None:
            variables["projectId"] = project_id
        if assignee_id is not None:
            variables["assigneeId"] = assignee_id

        try:
            response = self._execute_query(query, variables)
            log_info(f"Response: {response}")

            if response["issueCreate"]["success"]:
                issue = response["issueCreate"]["issue"]
                log_info(f"Issue '{issue['title']}' created successfully with ID {issue['id']}")
                return json.dumps(issue)
            else:
                log_error("Issue creation failed.")
                return json.dumps({"error": "Issue creation failed"})

        except Exception as e:
            logger.exception(f"Error creating issue '{title}' for team ID {team_id}")
            return json.dumps({"error": f"Error creating issue: {e}"})

    def update_issue(self, issue_id: str, title: Optional[str]) -> str:
        """Update the title of a specific issue by issue ID.

        Args:
            issue_id: The unique identifier of the issue to update.
            title: The new title for the issue. If None, the title remains unchanged.

        Returns:
            JSON with updated issue id, title, and state.
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
                return json.dumps(issue)
            else:
                log_error(f"Failed to update issue ID {issue_id}. Success flag was false.")
                return json.dumps({"error": f"Failed to update issue ID {issue_id}"})

        except Exception as e:
            logger.exception(f"Error updating issue ID {issue_id}")
            return json.dumps({"error": f"Error updating issue: {e}"})

    def get_user_assigned_issues(self, user_id: str) -> str:
        """Retrieve issues assigned to a specific user by user ID.

        Args:
            user_id: The unique identifier of the user for whom to retrieve assigned issues.

        Returns:
            JSON array of issues with id and title.
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
                return json.dumps(issues)
            else:
                log_error("Failed to retrieve user or issues.")
                return json.dumps({"error": f"User with ID {user_id} not found"})

        except Exception as e:
            logger.exception(f"Error retrieving issues for user ID {user_id}")
            return json.dumps({"error": f"Error retrieving assigned issues: {e}"})

    def get_workflow_issues(self, workflow_id: str) -> str:
        """Retrieve issues within a specific workflow state by workflow ID.

        Args:
            workflow_id: The unique identifier of the workflow state to retrieve issues from.

        Returns:
            JSON array of issues with title.
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
                return json.dumps(issues)
            else:
                log_error("Failed to retrieve issues for the specified workflow state.")
                return json.dumps({"error": f"Workflow state with ID {workflow_id} not found"})

        except Exception as e:
            logger.exception(f"Error retrieving issues for workflow state ID {workflow_id}")
            return json.dumps({"error": f"Error retrieving workflow issues: {e}"})

    def get_high_priority_issues(self) -> str:
        """Retrieve issues with a high priority (priority <= 2).

        Returns:
            JSON array of issues with id, title, and priority.
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
                return json.dumps(high_priority_issues)
            else:
                log_error("Failed to retrieve high-priority issues.")
                return json.dumps({"error": "Failed to retrieve high-priority issues"})

        except Exception as e:
            logger.exception("Error retrieving high-priority issues")
            return json.dumps({"error": f"Error retrieving high-priority issues: {e}"})
