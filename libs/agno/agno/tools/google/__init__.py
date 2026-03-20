__all__ = [
    "GoogleBigQueryTools",
    "GoogleCalendarTools",
    "GoogleDriveTools",
    "GmailTools",
    "GoogleMapTools",
    "GoogleOAuth",
    "GoogleSheetsTools",
]


def __getattr__(name: str):
    if name == "GoogleOAuth":
        from agno.tools.google.oauth import GoogleOAuth

        return GoogleOAuth
    if name == "GoogleBigQueryTools":
        from agno.tools.google.bigquery import GoogleBigQueryTools

        return GoogleBigQueryTools
    if name == "GoogleCalendarTools":
        from agno.tools.google.calendar import GoogleCalendarTools

        return GoogleCalendarTools
    if name == "GoogleDriveTools":
        from agno.tools.google.drive import GoogleDriveTools

        return GoogleDriveTools
    if name == "GmailTools":
        from agno.tools.google.gmail import GmailTools

        return GmailTools
    if name == "GoogleMapTools":
        from agno.tools.google.maps import GoogleMapTools

        return GoogleMapTools
    if name == "GoogleSheetsTools":
        from agno.tools.google.sheets import GoogleSheetsTools

        return GoogleSheetsTools
    raise AttributeError(f"module 'agno.tools.google' has no attribute {name!r}")
