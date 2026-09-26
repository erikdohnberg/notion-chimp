"""Gmail sender using OAuth (installed-app flow) and the Gmail API.

Only the gmail.send scope is requested: notion-chimp can send as you but
can't read your mailbox.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from .base import OutgoingEmail, build_mime

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _paths(options: dict) -> tuple[Path, Path]:
    creds = options.get("credentials_file") or os.environ.get("GMAIL_CREDENTIALS_FILE", "credentials.json")
    token = options.get("token_file") or os.environ.get("GMAIL_TOKEN_FILE", "token.json")
    return Path(creds), Path(token)


def authorize(options: dict | None = None, open_browser: bool = True):
    """Run the OAuth consent flow once and cache the refresh token."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise RuntimeError("Gmail support needs: pip install 'notion-chimp[gmail]'") from e

    creds_path, token_path = _paths(options or {})
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not creds_path.exists():
            raise FileNotFoundError(
                f"{creds_path} not found. Download an OAuth client (Desktop app) JSON "
                "from Google Cloud Console; see README 'Gmail setup'."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=open_browser)
    token_path.write_text(creds.to_json())
    os.chmod(token_path, 0o600)
    return creds


class GmailSender:
    name = "gmail"

    def __init__(self, options: dict | None = None):
        self.options = options or {}
        self._service = None

    def _svc(self):
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build("gmail", "v1", credentials=authorize(self.options, open_browser=False),
                                  cache_discovery=False)
        return self._service

    def send(self, email: OutgoingEmail) -> str:
        raw = base64.urlsafe_b64encode(build_mime(email).as_bytes()).decode()
        sent = self._svc().users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent.get("id", "")
