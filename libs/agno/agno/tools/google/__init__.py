__all__ = [
    "GoogleAuth",
    "GoogleSlidesTools",
    "GoogleBigQueryTools",
    "GoogleCalendarTools",
    "GoogleDriveTools",
    "GoogleMeetTools",
    "GoogleTasksTools",
    "GmailTools",
    "GoogleMapTools",
    "GoogleSheetsTools",
]


def __getattr__(name: str):
    if name == "GoogleAuth":
        from agno.tools.google.auth import GoogleAuth

        return GoogleAuth
    if name == "GoogleSlidesTools":
        from agno.tools.google.slides import GoogleSlidesTools

        return GoogleSlidesTools
    if name == "GoogleBigQueryTools":
        from agno.tools.google.bigquery import GoogleBigQueryTools

        return GoogleBigQueryTools
    if name == "GoogleCalendarTools":
        from agno.tools.google.calendar import GoogleCalendarTools

        return GoogleCalendarTools
    if name == "GoogleDriveTools":
        from agno.tools.google.drive import GoogleDriveTools

        return GoogleDriveTools
    if name == "GoogleMeetTools":
        from agno.tools.google.meet import GoogleMeetTools

        return GoogleMeetTools
    if name == "GoogleTasksTools":
        from agno.tools.google.tasks import GoogleTasksTools

        return GoogleTasksTools
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
