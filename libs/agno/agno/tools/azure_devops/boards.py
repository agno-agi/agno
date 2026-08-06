import asyncio
import json
from typing import Any, Dict, List, Optional

from agno.tools.azure_devops.base import AzureDevOpsBaseTools
from agno.utils.log import log_debug, log_error

try:
    from azure.devops.v7_1.work_item_tracking.models import (
        CommentCreate,
        JsonPatchOperation,
        TeamContext,
        Wiql,
    )
except ImportError:
    raise ImportError("`azure-devops` not installed. Please install using `pip install azure-devops`")


def _format_field_value(field_value: Any) -> str:
    if field_value is None:
        return "None"
    if isinstance(field_value, dict):
        if "displayName" in field_value:
            return f"{field_value.get('displayName')} ({field_value.get('uniqueName', '')})"
        return ", ".join([f"{k}: {v}" for k, v in field_value.items()])
    if hasattr(field_value, "display_name") and hasattr(field_value, "unique_name"):
        return f"{field_value.display_name} ({field_value.unique_name})"
    if hasattr(field_value, "display_name"):
        return field_value.display_name
    return str(field_value)


def _format_work_item(work_item: Any, project_fields: Any) -> str:
    field_map = {field.reference_name: field.name for field in project_fields}
    fields = work_item.fields or {}
    details = [f"# Work Item {work_item.id}"]

    for field_name in sorted(fields.keys()):
        formatted_value = _format_field_value(fields[field_name])
        friendly_name = field_map.get(field_name, field_name)
        details.append(f"- **{friendly_name}**: {formatted_value}")

    work_item_url = ""
    if getattr(work_item, "relations", None):
        details.append("\n## Related Items")
        for link in work_item.relations:
            direct_url = link.url.replace("_apis/wit/workItems", "_workitems/edit")
            work_item_url = direct_url
            details.append(f"- {link.rel} URL: {direct_url}")
            if getattr(link, "attributes", None):
                details.append(f"  :: Attributes: {link.attributes}")

    base_url = "/".join(work_item_url.split("/")[:-1])
    base_url = base_url + "/" + str(work_item.id)
    details.append(f"Work Item URL: [link]({base_url})")

    return "\n".join(details)


def _format_work_item_custom(work_item: Any) -> str:
    base_url = work_item.url.replace("_apis/wit/workItems", "_workitems/edit")
    fields = work_item.fields or {}

    desired_fields = [
        "System.Title",
        "System.IterationPath",
        "System.BoardColumn",
        "System.WorkItemType",
        "System.State",
        "System.Reason",
        "System.AssignedTo",
        "System.CreatedDate",
        "System.CreatedBy",
        "System.ChangedDate",
        "System.ChangedBy",
        "System.CommentCount",
        "Microsoft.VSTS.Common.ClosedDate",
        "Microsoft.VSTS.Scheduling.OriginalEstimate",
        "Microsoft.VSTS.Scheduling.RemainingWork",
        "Microsoft.VSTS.Scheduling.CompletedWork",
        "Microsoft.VSTS.Common.Priority",
        "Microsoft.VSTS.Common.ValueArea",
        "System.Parent",
    ]

    details = [f"# Work Item {work_item.id}", f"Work Item URL: [link]({base_url})"]
    for key in desired_fields:
        value = fields.get(key)
        if isinstance(value, dict) and "displayName" in value:
            value = value["displayName"]
        details.append(f"- {key}: {value}")

    return "\n".join(details)


def _format_comment(comment: Any) -> str:
    created_date = ""
    if getattr(comment, "created_date", None):
        created_date = f" on {comment.created_date}"

    author = "Unknown"
    if getattr(comment, "created_by", None) and getattr(comment.created_by, "display_name", None):
        author = comment.created_by.display_name

    text = comment.text if getattr(comment, "text", None) else "No text"
    return f"## Comment by {author}{created_date}:\n{text}"


def _format_standard_fields(
    title: Optional[str],
    description: Optional[str],
    state: Optional[str],
    assigned_to: Optional[str],
    iteration_path: Optional[str],
    area_path: Optional[str],
    story_points: Optional[str],
    priority: Optional[str],
    tags: Optional[str],
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if title:
        fields["System.Title"] = title
    if description:
        fields["System.Description"] = description
    if state:
        fields["System.State"] = state
    if assigned_to:
        fields["System.AssignedTo"] = assigned_to
    if iteration_path:
        fields["System.IterationPath"] = iteration_path
    if area_path:
        fields["System.AreaPath"] = area_path
    if story_points is not None:
        fields["Microsoft.VSTS.Scheduling.StoryPoints"] = str(story_points)
    if priority is not None:
        fields["Microsoft.VSTS.Common.Priority"] = str(priority)
    if tags:
        fields["System.Tags"] = tags
    return fields


def _ensure_system_prefix(field_name: str) -> str:
    if field_name.startswith("System.") or field_name.startswith("Microsoft."):
        return field_name

    common_fields = {
        "title": "System.Title",
        "description": "System.Description",
        "state": "System.State",
        "assignedto": "System.AssignedTo",
        "assigned": "System.AssignedTo",
        "iterationpath": "System.IterationPath",
        "iteration": "System.IterationPath",
        "areapath": "System.AreaPath",
        "area": "System.AreaPath",
        "tags": "System.Tags",
        "storypoints": "Microsoft.VSTS.Scheduling.StoryPoints",
        "priority": "Microsoft.VSTS.Common.Priority",
    }
    normalized = field_name.lower().replace("_", "").replace(" ", "")
    return common_fields.get(normalized, field_name)


def _build_field_document(fields: Dict[str, Any], operation: str = "add") -> List[Any]:
    document = []
    for field_name, field_value in fields.items():
        path = field_name if field_name.startswith("/fields/") else f"/fields/{field_name}"
        document.append(JsonPatchOperation(op=operation, path=path, value=field_value))
    return document


def _build_link_document(target_id: Any, link_type: str, org_url: str) -> List[Any]:
    return [
        JsonPatchOperation(
            op="add",
            path="/relations/-",
            value={"rel": link_type, "url": f"{org_url}/_apis/wit/workItems/{target_id}"},
        )
    ]


class AzureDevOpsBoardsTools(AzureDevOpsBaseTools):
    """Toolkit for Azure DevOps Boards: work items, comments, sprints and fields."""

    def __init__(
        self,
        organization_url: Optional[str] = None,
        personal_access_token: Optional[str] = None,
        project: Optional[str] = None,
        enable_search_tasks: bool = True,
        enable_get_task: bool = True,
        enable_create_task: bool = True,
        enable_update_task: bool = True,
        enable_add_parent_child_link: bool = True,
        enable_get_task_comment: bool = True,
        enable_add_task_comment: bool = True,
        enable_get_sprints: bool = True,
        enable_get_fields: bool = True,
        **kwargs: Any,
    ):
        tools: List[Any] = []
        async_tools: List[tuple[Any, str]] = []

        if enable_search_tasks:
            tools.append(self.search_tasks)
            async_tools.append((self.asearch_tasks, "search_tasks"))
        if enable_get_task:
            tools.append(self.get_task)
            async_tools.append((self.aget_task, "get_task"))
        if enable_create_task:
            tools.append(self.create_task)
            async_tools.append((self.acreate_task, "create_task"))
        if enable_update_task:
            tools.append(self.update_task)
            async_tools.append((self.aupdate_task, "update_task"))
        if enable_add_parent_child_link:
            tools.append(self.add_parent_child_link)
            async_tools.append((self.aadd_parent_child_link, "add_parent_child_link"))
        if enable_get_task_comment:
            tools.append(self.get_task_comment)
            async_tools.append((self.aget_task_comment, "get_task_comment"))
        if enable_add_task_comment:
            tools.append(self.add_task_comment)
            async_tools.append((self.aadd_task_comment, "add_task_comment"))
        if enable_get_sprints:
            tools.append(self.get_sprints)
            async_tools.append((self.aget_sprints, "get_sprints"))
        if enable_get_fields:
            tools.append(self.get_fields)
            async_tools.append((self.aget_fields, "get_fields"))

        super().__init__(
            organization_url=organization_url,
            personal_access_token=personal_access_token,
            project=project,
            name="azure_devops_boards",
            tools=tools,
            async_tools=async_tools,
            **kwargs,
        )

    # ------------------------------------------------------------------ #
    # Private helpers that require SDK clients
    # ------------------------------------------------------------------ #
    def _get_team_members(self, project: str) -> str:
        core_client = self._get_core_client()
        teams = core_client.get_teams(project_id=project)
        if not teams:
            raise Exception(f"Team not found in project '{project}'.")
        team = teams[0]
        members = core_client.get_team_members_with_extended_properties(project_id=project, team_id=team.id)
        return ", ".join([member.identity.display_name for member in members])

    def _get_valid_states(self, project: str, work_item_type: str) -> str:
        wit_client = self._get_wit_client()
        work_item_type_def = wit_client.get_work_item_type(project=project, type=work_item_type)
        return ", ".join([state.name for state in work_item_type_def.states])

    def _get_valid_iteration_paths(self, project: str) -> str:
        work_client = self._get_work_client()
        team_iterations = work_client.get_team_iterations(team_context=TeamContext(project_id=project))
        return ", ".join([iteration.path for iteration in team_iterations])

    def _get_valid_board_columns(self, project: str, work_item_type: str) -> str:
        work_client = self._get_work_client()
        team_context = TeamContext(project_id=project)
        board_refs = work_client.get_boards(team_context=team_context)

        matching_board = None
        for ref in board_refs:
            board = work_client.get_board(team_context=team_context, id=ref.id)
            if board.work_item_type.lower() == work_item_type.lower():
                matching_board = board
                break
        if not matching_board:
            return ""

        board_columns = work_client.get_board_columns(team_context=team_context, id=matching_board.id)
        return ", ".join([col.name for col in board_columns.value])

    # ------------------------------------------------------------------ #
    # Public tools
    # ------------------------------------------------------------------ #
    def search_tasks(
        self,
        wiql_fields: str = "[System.Id]",
        wiql_where: Optional[str] = None,
        wiql_order: Optional[str] = None,
        top: int = 30,
        project: Optional[str] = None,
    ) -> str:
        """Execute a WIQL query to retrieve work items from Azure DevOps.

        Args:
            wiql_fields: Comma-separated fields for the SELECT clause. Defaults to "[System.Id]".
            wiql_where: Optional additional WHERE conditions (combined with the project filter).
            wiql_order: Optional ORDER BY clause.
            top: Maximum number of work items to return. Defaults to 30.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the formatted work items or an error.
        """
        resolved_project = None
        try:
            resolved_project = self._resolve_project(project)
            wit_client = self._get_wit_client()
            team_context = TeamContext(project_id=resolved_project)

            fields = wiql_fields.strip() if wiql_fields and wiql_fields.strip() else "[System.Id]"
            additional_where = wiql_where.strip() if wiql_where else ""
            where_clause = "[System.TeamProject] = @project"
            if additional_where:
                where_clause = f"{where_clause} AND {additional_where}"

            wiql_query = f"SELECT {fields}\nFROM WorkItems\nWHERE {where_clause}"
            if wiql_order and wiql_order.strip():
                wiql_query += f"\nORDER BY {wiql_order.strip()}"

            wiql_results = wit_client.query_by_wiql(Wiql(query=wiql_query), team_context, top=top).work_items
            if not wiql_results:
                return json.dumps({"results": [], "message": "No work items found matching the query."})

            work_item_ids = [int(item.id) for item in wiql_results]
            work_items = wit_client.get_work_items(ids=work_item_ids, expand="Fields", error_policy="omit")
            formatted = [_format_work_item_custom(item) for item in work_items if item]
            return json.dumps({"results": formatted})
        except Exception as e:
            log_error(f"Error searching Azure DevOps work items: {e}")
            message = str(e)
            if "TF51011" in message or "The specified iteration path does not exist" in message:
                sprints = self._safe(self._get_valid_iteration_paths, resolved_project)
                return json.dumps(
                    {
                        "error": "The specified sprint does not exist or is incorrect.",
                        "available_sprints": sprints,
                    }
                )
            return json.dumps({"error": message})

    async def asearch_tasks(
        self,
        wiql_fields: str = "[System.Id]",
        wiql_where: Optional[str] = None,
        wiql_order: Optional[str] = None,
        top: int = 30,
        project: Optional[str] = None,
    ) -> str:
        """Execute a WIQL query to retrieve work items from Azure DevOps (async).

        Args:
            wiql_fields: Comma-separated fields for the SELECT clause. Defaults to "[System.Id]".
            wiql_where: Optional additional WHERE conditions (combined with the project filter).
            wiql_order: Optional ORDER BY clause.
            top: Maximum number of work items to return. Defaults to 30.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the formatted work items or an error.
        """
        return await asyncio.to_thread(self.search_tasks, wiql_fields, wiql_where, wiql_order, top, project)

    def get_task(self, item_id: str, project: Optional[str] = None) -> str:
        """Retrieve detailed information about one or multiple work items.

        Args:
            item_id: A single work item ID, or several IDs separated by commas.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the formatted work item(s) or an error.
        """
        try:
            resolved_project = self._resolve_project(project)
            wit_client = self._get_wit_client()
            project_fields = wit_client.get_fields(project=resolved_project)

            if "," in item_id:
                ids = [int(part.strip()) for part in item_id.split(",") if part.strip()]
                work_items = wit_client.get_work_items(
                    ids=ids, project=resolved_project, error_policy="omit", expand="all"
                )
                formatted = [_format_work_item(item, project_fields) for item in work_items if item]
                if not formatted:
                    return json.dumps({"results": [], "message": "No work items found."})
                return json.dumps({"results": formatted})

            work_item = wit_client.get_work_item(id=int(item_id), project=resolved_project, expand="all")
            return json.dumps({"result": _format_work_item(work_item, project_fields)})
        except Exception as e:
            log_error(f"Error retrieving Azure DevOps work item(s): {e}")
            return json.dumps({"error": str(e)})

    async def aget_task(self, item_id: str, project: Optional[str] = None) -> str:
        """Retrieve detailed information about one or multiple work items (async).

        Args:
            item_id: A single work item ID, or several IDs separated by commas.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the formatted work item(s) or an error.
        """
        return await asyncio.to_thread(self.get_task, item_id, project)

    def create_task(
        self,
        title: str,
        work_item_type: str,
        description: Optional[str] = None,
        state: Optional[str] = None,
        assigned_to: Optional[str] = None,
        parent_id: Optional[str] = None,
        iteration_path: Optional[str] = None,
        area_path: Optional[str] = None,
        story_points: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None,
    ) -> str:
        """Create a new work item in Azure DevOps.

        Args:
            title: The work item title.
            work_item_type: The work item type (e.g. "Task", "Bug", "User Story").
            description: Optional description.
            state: Optional initial state.
            assigned_to: Optional assignee (must be a valid team member).
            parent_id: Optional parent work item ID to link as a child.
            iteration_path: Optional iteration (sprint) path.
            area_path: Optional area path.
            story_points: Optional story points value.
            priority: Optional priority value.
            tags: Optional semicolon-separated tags.
            fields: Optional extra fields as a dict of field name to value.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the created work item or an error with valid-value hints.
        """
        resolved_project = None
        try:
            resolved_project = self._resolve_project(project)
            wit_client = self._get_wit_client()
            project_fields = wit_client.get_fields(project=resolved_project)

            all_fields = _format_standard_fields(
                title, description, state, assigned_to, iteration_path, area_path, story_points, priority, tags
            )
            if fields:
                for field_name, field_value in fields.items():
                    all_fields[_ensure_system_prefix(field_name)] = field_value

            if not all_fields.get("System.Title"):
                return json.dumps({"error": "Title is required for work item creation."})

            document = _build_field_document(all_fields)
            new_work_item = wit_client.create_work_item(
                document=document, project=resolved_project, type=work_item_type
            )

            if parent_id:
                try:
                    link_document = _build_link_document(
                        parent_id, "System.LinkTypes.Hierarchy-Reverse", self.organization_url or ""
                    )
                    new_work_item = wit_client.update_work_item(
                        document=link_document, id=new_work_item.id, project=resolved_project
                    )
                except Exception as link_error:
                    return json.dumps(
                        {
                            "result": _format_work_item(new_work_item, project_fields),
                            "warning": "Work item created, but failed to link to the parent work item.",
                            "details": str(link_error),
                        }
                    )

            log_debug(f"Created Azure DevOps work item {new_work_item.id}")
            return json.dumps({"result": _format_work_item(new_work_item, project_fields)})
        except Exception as e:
            return json.dumps(
                self._field_error(e, resolved_project, work_item_type, assigned_to, state, iteration_path)
            )

    async def acreate_task(
        self,
        title: str,
        work_item_type: str,
        description: Optional[str] = None,
        state: Optional[str] = None,
        assigned_to: Optional[str] = None,
        parent_id: Optional[str] = None,
        iteration_path: Optional[str] = None,
        area_path: Optional[str] = None,
        story_points: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None,
    ) -> str:
        """Create a new work item in Azure DevOps (async).

        Args:
            title: The work item title.
            work_item_type: The work item type (e.g. "Task", "Bug", "User Story").
            description: Optional description.
            state: Optional initial state.
            assigned_to: Optional assignee (must be a valid team member).
            parent_id: Optional parent work item ID to link as a child.
            iteration_path: Optional iteration (sprint) path.
            area_path: Optional area path.
            story_points: Optional story points value.
            priority: Optional priority value.
            tags: Optional semicolon-separated tags.
            fields: Optional extra fields as a dict of field name to value.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the created work item or an error with valid-value hints.
        """
        return await asyncio.to_thread(
            self.create_task,
            title,
            work_item_type,
            description,
            state,
            assigned_to,
            parent_id,
            iteration_path,
            area_path,
            story_points,
            priority,
            tags,
            fields,
            project,
        )

    def update_task(
        self,
        item_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        state: Optional[str] = None,
        assigned_to: Optional[str] = None,
        iteration_path: Optional[str] = None,
        area_path: Optional[str] = None,
        story_points: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None,
    ) -> str:
        """Modify an existing work item's fields and properties.

        Args:
            item_id: The work item ID to update.
            title: Optional new title.
            description: Optional new description.
            state: Optional new state.
            assigned_to: Optional new assignee (must be a valid team member).
            iteration_path: Optional new iteration (sprint) path.
            area_path: Optional new area path.
            story_points: Optional new story points value.
            priority: Optional new priority value.
            tags: Optional new semicolon-separated tags.
            fields: Optional extra fields as a dict of field name to value.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the updated work item or an error with valid-value hints.
        """
        resolved_project = None
        try:
            resolved_project = self._resolve_project(project)
            wit_client = self._get_wit_client()
            project_fields = wit_client.get_fields(project=resolved_project)

            all_fields = _format_standard_fields(
                title, description, state, assigned_to, iteration_path, area_path, story_points, priority, tags
            )
            if isinstance(fields, dict):
                for field_name, field_value in fields.items():
                    all_fields[_ensure_system_prefix(field_name)] = field_value

            if not all_fields:
                return json.dumps({"error": "At least one field must be specified for update."})

            document = _build_field_document(all_fields, "replace")
            updated_work_item = wit_client.update_work_item(
                document=document, id=int(item_id), project=resolved_project
            )
            log_debug(f"Updated Azure DevOps work item {item_id}")
            return json.dumps({"result": _format_work_item(updated_work_item, project_fields)})
        except Exception as e:
            error = self._field_error(e, resolved_project, "Task", assigned_to, state, iteration_path)
            if "field 'system.boardcolumn" in str(e).lower() and resolved_project:
                columns = self._safe(self._get_valid_board_columns, resolved_project, "Task")
                error = {"error": "Invalid board column.", "valid_columns": columns}
            return json.dumps(error)

    async def aupdate_task(
        self,
        item_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        state: Optional[str] = None,
        assigned_to: Optional[str] = None,
        iteration_path: Optional[str] = None,
        area_path: Optional[str] = None,
        story_points: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None,
    ) -> str:
        """Modify an existing work item's fields and properties (async).

        Args:
            item_id: The work item ID to update.
            title: Optional new title.
            description: Optional new description.
            state: Optional new state.
            assigned_to: Optional new assignee (must be a valid team member).
            iteration_path: Optional new iteration (sprint) path.
            area_path: Optional new area path.
            story_points: Optional new story points value.
            priority: Optional new priority value.
            tags: Optional new semicolon-separated tags.
            fields: Optional extra fields as a dict of field name to value.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the updated work item or an error with valid-value hints.
        """
        return await asyncio.to_thread(
            self.update_task,
            item_id,
            title,
            description,
            state,
            assigned_to,
            iteration_path,
            area_path,
            story_points,
            priority,
            tags,
            fields,
            project,
        )

    def add_parent_child_link(
        self,
        parent_id: str,
        child_id: str,
        project: Optional[str] = None,
    ) -> str:
        """Add a parent-child relationship between two work items.

        Args:
            parent_id: The parent work item ID.
            child_id: The child work item ID.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the updated child work item or an error.
        """
        try:
            resolved_project = self._resolve_project(project)
            wit_client = self._get_wit_client()
            project_fields = wit_client.get_fields(project=resolved_project)

            link_document = _build_link_document(
                parent_id, "System.LinkTypes.Hierarchy-Reverse", self.organization_url or ""
            )
            updated_work_item = wit_client.update_work_item(
                document=link_document, id=int(child_id), project=resolved_project
            )
            return json.dumps({"result": _format_work_item(updated_work_item, project_fields)})
        except Exception as e:
            log_error(f"Error adding Azure DevOps parent-child link: {e}")
            return json.dumps({"error": str(e)})

    async def aadd_parent_child_link(
        self,
        parent_id: str,
        child_id: str,
        project: Optional[str] = None,
    ) -> str:
        """Add a parent-child relationship between two work items (async).

        Args:
            parent_id: The parent work item ID.
            child_id: The child work item ID.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the updated child work item or an error.
        """
        return await asyncio.to_thread(self.add_parent_child_link, parent_id, child_id, project)

    def get_task_comment(self, item_id: str, project: Optional[str] = None) -> str:
        """Retrieve all user-submitted comments from a work item.

        Args:
            item_id: The work item ID.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the formatted comments or an error.
        """
        try:
            resolved_project = self._resolve_project(project)
            wit_client = self._get_wit_client()
            comments = wit_client.get_comments(project=resolved_project, work_item_id=int(item_id))
            formatted = [_format_comment(comment) for comment in comments.comments]
            if not formatted:
                return json.dumps({"comments": [], "message": "No comments found for this work item."})
            return json.dumps({"comments": formatted})
        except Exception as e:
            log_error(f"Error getting Azure DevOps work item comments: {e}")
            return json.dumps({"error": str(e)})

    async def aget_task_comment(self, item_id: str, project: Optional[str] = None) -> str:
        """Retrieve all user-submitted comments from a work item (async).

        Args:
            item_id: The work item ID.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the formatted comments or an error.
        """
        return await asyncio.to_thread(self.get_task_comment, item_id, project)

    def add_task_comment(self, item_id: str, comment: str, project: Optional[str] = None) -> str:
        """Add a new comment to a work item.

        Args:
            item_id: The work item ID.
            comment: The comment text to add.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the created comment or an error.
        """
        try:
            resolved_project = self._resolve_project(project)
            wit_client = self._get_wit_client()
            new_comment = wit_client.add_comment(
                request=CommentCreate(text=comment), project=resolved_project, work_item_id=int(item_id)
            )
            return json.dumps({"result": _format_comment(new_comment)})
        except Exception as e:
            log_error(f"Error adding Azure DevOps work item comment: {e}")
            return json.dumps({"error": str(e)})

    async def aadd_task_comment(self, item_id: str, comment: str, project: Optional[str] = None) -> str:
        """Add a new comment to a work item (async).

        Args:
            item_id: The work item ID.
            comment: The comment text to add.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the created comment or an error.
        """
        return await asyncio.to_thread(self.add_task_comment, item_id, comment, project)

    def get_sprints(self, project: Optional[str] = None) -> str:
        """Retrieve the list of sprints (iterations) from an Azure DevOps project.

        Args:
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of sprints (name, path, is_current).
        """
        try:
            resolved_project = self._resolve_project(project)
            work_client = self._get_work_client()
            team_iterations = work_client.get_team_iterations(team_context=TeamContext(project_id=resolved_project))
            sprints = [
                {
                    "name": item.name,
                    "path": item.path,
                    "is_current": getattr(item.attributes, "time_frame", None) == "current",
                }
                for item in team_iterations
            ]
            return json.dumps({"sprints": sprints})
        except Exception as e:
            log_error(f"Error getting Azure DevOps sprints: {e}")
            return json.dumps({"error": str(e)})

    async def aget_sprints(self, project: Optional[str] = None) -> str:
        """Retrieve the list of sprints (iterations) from an Azure DevOps project (async).

        Args:
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of sprints (name, path, is_current).
        """
        return await asyncio.to_thread(self.get_sprints, project)

    def get_fields(self, project: Optional[str] = None) -> str:
        """Retrieve the list of fields available in an Azure DevOps project.

        Args:
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string mapping field reference names to display names.
        """
        try:
            resolved_project = self._resolve_project(project)
            wit_client = self._get_wit_client()
            project_fields = wit_client.get_fields(project=resolved_project)
            field_map = {field.reference_name: field.name for field in project_fields}
            return json.dumps({"fields": field_map})
        except Exception as e:
            log_error(f"Error getting Azure DevOps fields: {e}")
            return json.dumps({"error": str(e)})

    async def aget_fields(self, project: Optional[str] = None) -> str:
        """Retrieve the list of fields available in an Azure DevOps project (async).

        Args:
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string mapping field reference names to display names.
        """
        return await asyncio.to_thread(self.get_fields, project)

    # ------------------------------------------------------------------ #
    # Error enrichment
    # ------------------------------------------------------------------ #
    def _field_error(
        self,
        error: Exception,
        project: Optional[str],
        work_item_type: str,
        assigned_to: Optional[str],
        state: Optional[str],
        iteration_path: Optional[str],
    ) -> Dict[str, Any]:
        message = str(error)
        lowered = message.lower()
        log_error(f"Error on Azure DevOps work item operation: {message}")

        if not project:
            return {"error": message}

        if "unknown identity" in lowered:
            return {
                "error": f"Invalid assignee: '{assigned_to}' is not recognized as a member of the team.",
                "valid_assignees": self._safe(self._get_team_members, project),
            }
        if "field 'state' contains" in lowered:
            return {
                "error": f"Invalid state: '{state}' is not valid for work item type '{work_item_type}'.",
                "valid_states": self._safe(self._get_valid_states, project, work_item_type),
            }
        if "field 'system.iterationpath'" in lowered:
            return {
                "error": f"Invalid iteration path: '{iteration_path}' is not a recognized sprint.",
                "valid_iteration_paths": self._safe(self._get_valid_iteration_paths, project),
            }
        return {"error": message}

    @staticmethod
    def _safe(func: Any, *args: Any) -> str:
        try:
            return func(*args)
        except Exception as e:
            log_error(f"Failed to fetch valid values: {e}")
            return ""
