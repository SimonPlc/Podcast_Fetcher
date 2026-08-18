from __future__ import annotations

import base64
from collections.abc import Mapping
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def require_env(env: Mapping[str, str], key: str) -> str:
    """Read a required env var, raising a clear error if unset or empty.
    Shared by digest.py and discover.py -- both mint a Gmail access token
    from the same three secrets before sending, and should fail the same
    way when one is missing.
    """
    value = env.get(key)
    if not value:
        raise RuntimeError(f"{key} must be set to send email")
    return value


def mint_access_token(client_id: str, client_secret: str, refresh_token: str, *, timeout: int = 30) -> str:
    """Exchange the long-lived refresh token for a short-lived access
    token. Called once per send (SPEC.md) rather than cached, since a
    digest run happens at most a couple of times a day.
    """
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError(f"token refresh response had no access_token: {response.text[:300]}")
    return str(token)


def build_mime_message(*, to_addr: str, from_addr: str, subject: str, text: str, html: str) -> str:
    """Build a multipart/alternative (text + HTML) message and return it
    base64url-encoded, ready for Gmail's messages.send `raw` field.
    Subject is stripped of newlines: it originates from LLM-generated
    text (the brief headline), and a raw newline in a header value is a
    header-injection vector in the underlying MIME/SMTP format.
    """
    safe_subject = " ".join(subject.splitlines()).strip()

    message = MIMEMultipart("alternative")
    message["To"] = to_addr
    message["From"] = from_addr
    message["Subject"] = safe_subject
    message.attach(MIMEText(text, "plain", "utf-8"))
    message.attach(MIMEText(html, "html", "utf-8"))

    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def send_email(
    access_token: str,
    *,
    to_addr: str,
    from_addr: str,
    subject: str,
    text: str,
    html: str,
    timeout: int = 30,
) -> None:
    raw = build_mime_message(to_addr=to_addr, from_addr=from_addr, subject=subject, text=text, html=html)
    response = requests.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
        timeout=timeout,
    )
    response.raise_for_status()
