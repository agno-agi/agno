from typing import Dict, List, Optional, Union

from httpx import Response, codes

from agno.api.api import api, invalid_response
from agno.api.routes import ApiRoutes
from agno.api.schemas.user import EmailPasswordAuthSchema, UserSchema
from agno.cli.config import AgnoCliConfig
from agno.cli.settings import agno_cli_settings
from agno.utils.log import logger


def user_ping() -> bool:
    if not agno_cli_settings.api_enabled:
        return False

    logger.debug("--**-- Ping user api")
    with api.Client() as api_client:
        try:
            r: Response = api_client.get(ApiRoutes.USER_HEALTH)
            if invalid_response(r):
                return False

            if r.status_code == codes.OK:
                return True
        except Exception as e:
            logger.debug(f"Could not ping user api: {e}")
    return False


def authenticate_and_get_user(auth_token: str, existing_user: Optional[UserSchema] = None) -> Optional[UserSchema]:
    if not agno_cli_settings.api_enabled:
        return None

    from agno.cli.credentials import read_auth_token

    logger.debug("--**-- Getting user")
    auth_header = {agno_cli_settings.auth_token_header: auth_token}
    anon_user = None
    if existing_user is not None:
        if existing_user.email == "anon":
            logger.debug(f"Claiming anonymous user: {existing_user.id_user}")
            anon_user = {
                "email": existing_user.email,
                "id_user": existing_user.id_user,
                "auth_token": read_auth_token() or "",
            }
    with api.Client() as api_client:
        try:
            r: Response = api_client.post(ApiRoutes.USER_CLI_AUTH, headers=auth_header, json=anon_user)
            if invalid_response(r):
                return None

            user_data = r.json()
            if not isinstance(user_data, dict):
                return None

            return UserSchema.model_validate(user_data)

        except Exception as e:
            logger.debug(f"Could not authenticate user: {e}")
    return None


def sign_in_user(sign_in_data: EmailPasswordAuthSchema) -> Optional[UserSchema]:
    if not agno_cli_settings.api_enabled:
        return None

    from agno.cli.credentials import save_auth_token

    logger.debug("--**-- Signing in user")
    with api.Client() as api_client:
        try:
            r: Response = api_client.post(ApiRoutes.USER_SIGN_IN, json=sign_in_data.model_dump())
            if invalid_response(r):
                return None

            agno_auth_token = r.headers.get(agno_cli_settings.auth_token_header)
            if agno_auth_token is None:
                logger.error("Could not authenticate user")
                return None

            user_data = r.json()
            if not isinstance(user_data, dict):
                return None

            current_user: UserSchema = UserSchema.model_validate(user_data)

            if current_user is not None:
                save_auth_token(agno_auth_token)
                return current_user
        except Exception as e:
            logger.debug(f"Could not sign in user: {e}")
    return None


def user_is_authenticated() -> bool:
    if not agno_cli_settings.api_enabled:
        return False

    logger.debug("--**-- Checking if user is authenticated")
    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if agno_config is None:
        return False
    user: Optional[UserSchema] = agno_config.user
    if user is None:
        return False

    with api.AuthenticatedClient() as api_client:
        try:
            r: Response = api_client.post(
                ApiRoutes.USER_AUTHENTICATE, json=user.model_dump(include={"id_user", "email"})
            )
            if invalid_response(r):
                return False

            response_json: Union[Dict, List] = r.json()
            if response_json is None or not isinstance(response_json, dict):
                logger.error("Could not parse response")
                return False
            if response_json.get("status") == "success":
                return True
        except Exception as e:
            logger.debug(f"Could not check if user is authenticated: {e}")
    return False


def create_anon_user() -> Optional[UserSchema]:
    if not agno_cli_settings.api_enabled:
        return None

    from agno.cli.credentials import save_auth_token

    logger.debug("--**-- Creating anon user")
    with api.Client() as api_client:
        try:
            r: Response = api_client.post(
                ApiRoutes.USER_CREATE_ANON,
                json={"user": {"email": "anon", "username": "anon", "is_machine": True}},
                timeout=2.0,
            )
            if invalid_response(r):
                return None

            agno_auth_token = r.headers.get(agno_cli_settings.auth_token_header)
            if agno_auth_token is None:
                logger.debug("Could not create anon user")
                return None

            user_data = r.json()
            if not isinstance(user_data, dict):
                return None

            current_user: UserSchema = UserSchema.model_validate(user_data)
            if current_user is not None:
                save_auth_token(agno_auth_token)
                return current_user
        except Exception as e:
            logger.debug(f"Could not create anon user: {e}")
    return None
