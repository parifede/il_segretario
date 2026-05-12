from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


@dataclass(frozen=True)
class GoogleOAuthStatus:
    configured: bool
    credentials_path: str
    token_path: str


class GoogleOAuthConnector:
    def __init__(self, *, credentials_path: str | Path, token_path: str | Path) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)

    def status(self) -> GoogleOAuthStatus:
        return GoogleOAuthStatus(
            configured=self.credentials_path.exists() and self.token_path.exists(),
            credentials_path=str(self.credentials_path),
            token_path=str(self.token_path),
        )

    def credentials(self) -> Credentials:
        if not self.token_path.exists():
            raise FileNotFoundError(self.token_path)

        credentials = Credentials.from_authorized_user_file(str(self.token_path))
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials
