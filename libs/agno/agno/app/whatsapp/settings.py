from __future__ import annotations

from agno.app.settings import APIAppSettings


class WhatsappAppSettings(APIAppSettings):
    """App settings for whatsapp apps that can be set using environment variables."""

    title: str = "whatsapp-app"
