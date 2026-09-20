"""Google OAuth + Gmail API client helpers.

OAuth uses the installed google-auth-oauthlib Flow; the Gmail service is built
from a stored refresh token so background syncs need no user interaction.
Scope is read-only — we never modify the mailbox.
"""
from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from ..core.config import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def _flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = settings.google_redirect_uri
    # confidential client: skip PKCE so the stateless callback needs no stored verifier
    flow.autogenerate_code_verifier = False
    return flow


def authorization_url(state: str) -> str:
    """Consent URL; access_type=offline + prompt=consent forces a refresh token."""
    url, _ = _flow(state).authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return url


def exchange_code(code: str) -> Credentials:
    flow = _flow()
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_from_refresh_token(refresh_token: str) -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def build_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def profile_email(service) -> str:
    return service.users().getProfile(userId="me").execute()["emailAddress"]
