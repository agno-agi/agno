__all__ = [
    "AuthConfig",
    "GoogleAuth",
    "GoogleSlidesTools",
    "GoogleBigQueryTools",
    "GoogleCalendarTools",
    "GoogleDriveTools",
    "GmailTools",
    "GoogleMapsTools",
    "GooglePlacesTools",
    "GoogleSheetsTools",
]


def __getattr__(name: str):
    if name == "AuthConfig":
        from agno.tools.google.auth import AuthConfig

        return AuthConfig
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
    if name == "GmailTools":
        from agno.tools.google.gmail import GmailTools

        return GmailTools
    if name == "GoogleMapsTools":
        from agno.tools.google.maps import GoogleMapsTools

        return GoogleMapsTools
    if name == "GooglePlacesTools":
        from agno.tools.google.places import GooglePlacesTools

        return GooglePlacesTools
    if name == "GoogleSheetsTools":
        from agno.tools.google.sheets import GoogleSheetsTools

        return GoogleSheetsTools
    raise AttributeError(f"module 'agno.tools.google' has no attribute {name!r}")
