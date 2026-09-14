"""The app's Home tab: who this is and where it runs."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from agno.utils.log import log_error

AGNO_OS_URL = "https://os.agno.com"


def build_home_view(entity_name: str, description: Optional[str] = None) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = [{"type": "header", "text": {"type": "plain_text", "text": entity_name[:150]}}]
    if description:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": description[:3000]}})
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Powered by <{AGNO_OS_URL}|AgentOS>"}],
        }
    )
    return {"type": "home", "blocks": blocks}


class HomeTab:
    def __init__(self, client_factory: Callable[[], Any], entity_name: str, description: Optional[str] = None) -> None:
        self._client_factory = client_factory
        self.entity_name = entity_name
        self.description = description

    async def publish(self, slack_user_id: str) -> None:
        try:
            await self._client_factory().views_publish(
                user_id=slack_user_id, view=build_home_view(self.entity_name, self.description)
            )
        except Exception as exc:
            log_error(f"views.publish failed for {slack_user_id}: {exc}")
