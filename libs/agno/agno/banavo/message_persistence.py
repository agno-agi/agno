"""
Ensure OpenAI Responses API state survives Postgres session round-trips.

Upstream Agno ``Message.to_dict()`` omits ``provider_data``, so ``response_id`` is lost
after ``write_to_storage`` / ``load_team_session``. Without it, GPT-5 reasoning replays strip
assistant ``tool_calls`` and drop ``tool`` messages on the next HTTP request.
"""

from __future__ import annotations


def apply_message_provider_data_persistence_patch() -> None:
    from agno.models.message import Message

    if getattr(Message.to_dict, "_banavo_provider_data_patch", False):
        return

    original_to_dict = Message.to_dict

    def _message_to_dict_include_provider_data(self: Message) -> dict:
        message_dict = original_to_dict(self)
        if self.provider_data:
            message_dict["provider_data"] = self.provider_data
        return message_dict

    Message.to_dict = _message_to_dict_include_provider_data  # type: ignore[method-assign]
    Message.to_dict._banavo_provider_data_patch = True  # type: ignore[attr-defined]


apply_message_provider_data_persistence_patch()
