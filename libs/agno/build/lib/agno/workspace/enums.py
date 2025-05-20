from enum import Enum


class WorkspaceStarterTemplate(str, Enum):
    agent_app = "agent-app"
    agent_api = "agent-api"
