"""OAuth for the Gmail API. Tokens are cached locally and never leave your machine."""

from __future__ import annotations

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# gmail.modify: read, label, archive, trash. Cannot permanently delete or send.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def load_cached(token_path: Path) -> Credentials | None:
    """Saved credentials, refreshed if needed, or None if the user must sign in."""
    if not token_path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            return None
        _save(creds, token_path)
        return creds
    return None


def sign_in(credentials_path: Path, token_path: Path) -> Credentials:
    """Open the browser for Google consent and save the resulting token."""
    if not credentials_path.exists():
        raise FileNotFoundError(
            f"{credentials_path} not found. See the README for how to create "
            "a Google Cloud OAuth client (Desktop app) and download it."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save(creds, token_path)
    return creds


def build_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_service(credentials_path: Path, token_path: Path):
    creds = load_cached(token_path) or sign_in(credentials_path, token_path)
    return build_service(creds)


def _save(creds: Credentials, token_path: Path) -> None:
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)
