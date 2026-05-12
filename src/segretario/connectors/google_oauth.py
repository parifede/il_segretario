from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


REQUIRED_GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
)


@dataclass(frozen=True)
class GoogleOAuthStatus:
    configured: bool
    credentials_path: str
    token_path: str
    granted_scopes: tuple[str, ...] = ()
    missing_scopes: tuple[str, ...] = ()

    @property
    def scopes_ok(self) -> bool:
        return not self.missing_scopes


class GoogleOAuthConnector:
    def __init__(self, *, credentials_path: str | Path, token_path: str | Path) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)

    def status(self) -> GoogleOAuthStatus:
        granted_scopes = _granted_scopes(self.token_path)
        missing_scopes = tuple(
            scope for scope in REQUIRED_GOOGLE_SCOPES if scope not in granted_scopes
        )
        return GoogleOAuthStatus(
            configured=self.credentials_path.exists() and self.token_path.exists(),
            credentials_path=str(self.credentials_path),
            token_path=str(self.token_path),
            granted_scopes=tuple(sorted(granted_scopes)),
            missing_scopes=missing_scopes,
        )

    def credentials(self) -> Credentials:
        if not self.token_path.exists():
            raise FileNotFoundError(self.token_path)
        status = self.status()
        if status.missing_scopes:
            missing = ", ".join(status.missing_scopes)
            raise ValueError(
                "Google token missing OAuth scopes: "
                f"{missing}. Run `uv run segretario google login --force`."
            )

        credentials = Credentials.from_authorized_user_file(
            str(self.token_path),
            scopes=REQUIRED_GOOGLE_SCOPES,
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    def login(self, *, force: bool = False) -> GoogleOAuthStatus:
        if force and self.token_path.exists():
            self.token_path.unlink()
        if self.token_path.exists() and self.status().scopes_ok:
            return self.status()

        from google_auth_oauthlib.flow import InstalledAppFlow

        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.credentials_path),
            scopes=REQUIRED_GOOGLE_SCOPES,
        )
        credentials = flow.run_local_server(port=0)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        return self.status()


def _granted_scopes(token_path: Path) -> set[str]:
    if not token_path.exists():
        return set()
    try:
        raw = json.loads(token_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    scopes = raw.get("scopes") or raw.get("scope") or []
    if isinstance(scopes, str):
        return set(scopes.split())
    if isinstance(scopes, list):
        return {str(scope) for scope in scopes}
    return set()
