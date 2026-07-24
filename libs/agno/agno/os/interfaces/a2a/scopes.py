from typing import Dict, List


def get_a2a_scope_mappings(prefix: str = "/a2a") -> Dict[str, List[str]]:
    # Execution routes require :run, read-only routes require :read.
    # The /v1 JSON-RPC dispatchers multiplex methods (SendMessage, GetTask, ...) on one URL,
    # so the route gate carries the coarsest scope (:run) and the dispatcher re-checks the
    # per-method scope (GetTask -> :read) inside the handler.
    p = prefix.rstrip("/")
    return {
        f"GET {p}/agents/*/.well-known/agent-card.json": ["agents:read"],
        f"POST {p}/agents/*/v1": ["agents:run"],
        f"POST {p}/agents/*/v1/message:send": ["agents:run"],
        f"POST {p}/agents/*/v1/message:stream": ["agents:run"],
        f"POST {p}/agents/*/v1/tasks:get": ["agents:read"],
        f"POST {p}/agents/*/v1/tasks:cancel": ["agents:run"],
        f"GET {p}/teams/*/.well-known/agent-card.json": ["teams:read"],
        f"POST {p}/teams/*/v1": ["teams:run"],
        f"POST {p}/teams/*/v1/message:send": ["teams:run"],
        f"POST {p}/teams/*/v1/message:stream": ["teams:run"],
        f"POST {p}/teams/*/v1/tasks:get": ["teams:read"],
        f"POST {p}/teams/*/v1/tasks:cancel": ["teams:run"],
        f"GET {p}/workflows/*/.well-known/agent-card.json": ["workflows:read"],
        f"POST {p}/workflows/*/v1": ["workflows:run"],
        f"POST {p}/workflows/*/v1/message:send": ["workflows:run"],
        f"POST {p}/workflows/*/v1/message:stream": ["workflows:run"],
        f"POST {p}/message/send": ["agents:run"],
        f"POST {p}/message/stream": ["agents:run"],
    }
