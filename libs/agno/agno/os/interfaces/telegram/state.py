from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, List, Optional

from agno.utils.log import log_info, log_warning

if TYPE_CHECKING:
    from telebot.async_telebot import AsyncTeleBot


@dataclass
class BotState:
    bot: "AsyncTeleBot"
    bot_username: Optional[str] = None
    bot_id: Optional[int] = None
    processed_updates: dict[int, float] = field(default_factory=dict)
    session_generation: dict[str, int] = field(default_factory=dict)
    commands_registered: bool = False

    DEDUP_TTL: ClassVar[float] = 60.0

    async def get_bot_info(self) -> tuple[str, int]:
        if self.bot_username is None or self.bot_id is None:
            me = await self.bot.get_me()
            self.bot_username = me.username
            self.bot_id = me.id
        assert self.bot_username is not None and self.bot_id is not None
        return self.bot_username, self.bot_id

    async def register_commands(self, commands: Optional[List[dict]], register: bool) -> None:
        if self.commands_registered or not register or not commands:
            return
        try:
            from telebot.types import BotCommand

            bot_commands = [BotCommand(cmd["command"], cmd["description"]) for cmd in commands]
            await self.bot.set_my_commands(bot_commands)
            self.commands_registered = True
            log_info("Bot commands registered successfully")
        except Exception as e:
            log_warning(f"Failed to register bot commands: {e}")

    def check_dedup(self, update_id: int) -> bool:
        now = time.monotonic()
        expired = [uid for uid, ts in self.processed_updates.items() if now - ts > self.DEDUP_TTL]
        for uid in expired:
            del self.processed_updates[uid]
        if update_id in self.processed_updates:
            return True
        self.processed_updates[update_id] = now
        return False

    def bump_session_generation(self, base_key: str) -> None:
        self.session_generation[base_key] = self.session_generation.get(base_key, 0) + 1

    def get_session_id(self, base_key: str) -> str:
        gen = self.session_generation.get(base_key, 0)
        return f"{base_key}:g{gen}" if gen else base_key
