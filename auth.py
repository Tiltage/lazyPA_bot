# auth.py — run once to generate token.json; also provides get_google_creds()
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from config import GOOGLE_SCOPES


def get_google_creds() -> Credentials:
    """Load and silently refresh Google credentials from token.json."""
    creds = Credentials.from_authorized_user_file("token.json", GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return creds


def main():
    """Interactive OAuth flow — run this once to create token.json."""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", GOOGLE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    print("Auth complete. token.json saved.")


if __name__ == "__main__":
    main()
