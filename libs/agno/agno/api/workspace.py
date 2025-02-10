from typing import Dict, List, Optional, Union

from httpx import Response

from agno.api.api import api, invalid_response
from agno.api.routes import ApiRoutes
from agno.api.schemas.team import TeamIdentifier
from agno.api.schemas.user import UserSchema
from agno.api.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceEvent,
    WorkspaceSchema,
    WorkspaceUpdate,
)
from agno.cli.settings import agno_cli_settings
from agno.utils.log import logger


def create_workspace_for_user(
    user: UserSchema, workspace: WorkspaceCreate, team: Optional[TeamIdentifier] = None
) -> Optional[WorkspaceSchema]:
    logger.debug("--**-- Creating workspace")
    with api.AuthenticatedClient() as api_client:
        try:
            payload = {
                "user": user.model_dump(include={"id_user", "email"}),
                "workspace": workspace.model_dump(exclude_none=True),
            }
            if team is not None:
                payload["team"] = team.model_dump(exclude_none=True)

            r: Response = api_client.post(
                ApiRoutes.WORKSPACE_CREATE,
                json=payload,
                timeout=2.0,
            )
            if invalid_response(r):
                try:
                    error_msg = r.json().get("detail", "Permission denied")
                except Exception:
                    error_msg = f"Could not create workspace: {r.text}"
                logger.error(error_msg)
                return None

            response_json: Union[Dict, List] = r.json()
            if response_json is None:
                return None

            created_workspace: WorkspaceSchema = WorkspaceSchema.model_validate(response_json)
            if created_workspace is not None:
                return created_workspace
        except Exception as e:
            logger.debug(f"Could not create workspace: {e}")
    return None


def update_workspace_for_user(user: UserSchema, workspace: WorkspaceUpdate) -> Optional[WorkspaceSchema]:
    logger.debug("--**-- Updating workspace for user")
    with api.AuthenticatedClient() as api_client:
        try:
            payload = {
                "user": user.model_dump(include={"id_user", "email"}),
                "workspace": workspace.model_dump(exclude_none=True),
            }

            r: Response = api_client.post(
                ApiRoutes.WORKSPACE_UPDATE,
                json=payload,
            )
            if invalid_response(r):
                try:
                    error_msg = r.json().get("detail", "Could not update workspace")
                except Exception:
                    error_msg = f"Could not update workspace: {r.text}"
                logger.error(error_msg)
                return None

            response_json: Union[Dict, List] = r.json()
            if response_json is None:
                return None

            updated_workspace: WorkspaceSchema = WorkspaceSchema.model_validate(response_json)
            if updated_workspace is not None:
                return updated_workspace
        except Exception as e:
            logger.debug(f"Could not update workspace: {e}")
    return None


def update_workspace_for_team(
    user: UserSchema, workspace: WorkspaceUpdate, team: TeamIdentifier
) -> Optional[WorkspaceSchema]:
    logger.debug("--**-- Updating workspace for team")
    with api.AuthenticatedClient() as api_client:
        try:
            payload = {
                "user": user.model_dump(include={"id_user", "email"}),
                "team_workspace": workspace.model_dump(exclude_none=True).update({"id_team": team.id_team}),
            }

            r: Response = api_client.post(
                ApiRoutes.WORKSPACE_UPDATE,
                json=payload,
            )
            if invalid_response(r):
                try:
                    error_msg = r.json().get("detail", "Could not update workspace")
                except Exception:
                    error_msg = f"Could not update workspace: {r.text}"
                logger.error(error_msg)
                return None

            response_json: Union[Dict, List] = r.json()
            if response_json is None:
                return None

            updated_workspace: WorkspaceSchema = WorkspaceSchema.model_validate(response_json)
            if updated_workspace is not None:
                return updated_workspace
        except Exception as e:
            logger.debug(f"Could not update workspace: {e}")
    return None


def log_workspace_event(user: UserSchema, workspace_event: WorkspaceEvent) -> bool:
    if not agno_cli_settings.api_enabled:
        return False

    logger.debug("--**-- Log workspace event")
    with api.AuthenticatedClient() as api_client:
        try:
            r: Response = api_client.post(
                ApiRoutes.WORKSPACE_EVENT_CREATE,
                json={
                    "user": user.model_dump(include={"id_user", "email"}),
                    "event": workspace_event.model_dump(exclude_none=True),
                },
            )
            if invalid_response(r):
                return False

            response_json: Union[Dict, List] = r.json()
            if response_json is None:
                return False

            if isinstance(response_json, dict) and response_json.get("status") == "success":
                return True
            return False
        except Exception as e:
            logger.debug(f"Could not log workspace event: {e}")
    return False
