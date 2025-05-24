from dataclasses import dataclass


@dataclass
class ApiRoutes:
    # User paths
    USER_HEALTH: str = "/v1/user/health"
    USER_SIGN_IN: str = "/v1/user/signin"
    USER_CLI_AUTH: str = "/v1/user/cliauth"
    USER_AUTHENTICATE: str = "/v1/user/authenticate"
    USER_CREATE_ANON: str = "/v1/user/create/anon"

    # Workspace paths
    WORKSPACE_CREATE: str = "/v1/workspace/create"
    WORKSPACE_UPDATE: str = "/v1/workspace/update"
    WORKSPACE_DELETE: str = "/v1/workspace/delete"
    WORKSPACE_EVENT_CREATE: str = "/v1/workspace/event/create"

    # Team paths
    TEAM_READ_ALL: str = "/v1/team/read/all"

    # Agent paths
    AGENT_SESSION_CREATE: str = "/v1/agent-sessions"
    AGENT_RUN_CREATE: str = "/v1/agent-runs"
    AGENT_CREATE: str = "/v2/agents"

    # App paths
    APP_CREATE: str = "/v2/apps"
    # Team paths
    TEAM_RUN_CREATE: str = "/v1/team-runs"
    TEAM_SESSION_CREATE: str = "/v1/team-sessions"
    TEAM_CREATE: str = "/v2/teams"

    # Workflow paths
    WORKFLOW_CREATE: str = "/v2/workflows"
    # Telemetry paths
    # TODO: Update to use the new telemetry paths
    AGENT_TELEMETRY_SESSION_CREATE: str = "/v1/telemetry/agent/session/create"
    AGENT_TELEMETRY_RUN_CREATE: str = "/v1/telemetry/agent/run/create"

    TEAM_TELEMETRY_RUN_CREATE: str = "/v1/telemetry/team-runs"

    # Playground paths
    PLAYGROUND_ENDPOINT_CREATE: str = "/v1/playground/endpoint/create"
    PLAYGROUND_APP_DEPLOY: str = "/v1/playground/app/deploy"

    # Eval paths
    EVAL_RUN_CREATE: str = "/v2/eval-runs"
