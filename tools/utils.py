from googleapiclient.discovery import build
from auth import get_google_creds


def get_service(api: str, version: str):
    """Build and return an authenticated Google API service client."""
    creds = get_google_creds()
    return build(api, version, credentials=creds, cache_discovery=False)
