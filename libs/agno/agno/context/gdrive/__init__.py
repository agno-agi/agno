from agno.context.gdrive.provider import DEFAULT_GDRIVE_INSTRUCTIONS, GoogleDriveContextProvider

# Backwards-compat alias (deprecated, use GoogleDriveContextProvider)
GDriveContextProvider = GoogleDriveContextProvider

__all__ = ["DEFAULT_GDRIVE_INSTRUCTIONS", "GoogleDriveContextProvider", "GDriveContextProvider"]
