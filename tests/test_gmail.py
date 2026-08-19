from __future__ import annotations

import base64
from email import message_from_bytes
from email.message import Message

from podcast_fetcher.gmail import build_mime_message


def _decode(raw: str) -> Message:
    return message_from_bytes(base64.urlsafe_b64decode(raw.encode("ascii")))


def test_build_mime_message_round_trips_content() -> None:
    raw = build_mime_message(
        to_addr="simon@example.com",
        from_addr="bot@example.com",
        subject="Morning brief",
        text="plain body",
        html="<p>html body</p>",
    )
    message = _decode(raw)
    assert message["To"] == "simon@example.com"
    assert message["From"] == "bot@example.com"
    assert message["Subject"] == "Morning brief"
    assert message.is_multipart()

    parts: dict[str, str] = {}
    for part in message.walk():
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True)
        assert isinstance(payload, bytes)
        parts[part.get_content_type()] = payload.decode("utf-8")
    assert parts["text/plain"] == "plain body"
    assert parts["text/html"] == "<p>html body</p>"


def test_build_mime_message_prevents_header_injection_via_subject_newline() -> None:
    raw = build_mime_message(
        to_addr="simon@example.com",
        from_addr="bot@example.com",
        subject="Evil subject\nBcc: attacker@example.com",
        text="body",
        html="<p>body</p>",
    )
    message = _decode(raw)
    # The newline must not have split into a second, real Bcc header --
    # it's fine for the literal word to survive as inert subject text.
    assert message.get_all("Bcc") is None
    subjects = message.get_all("Subject")
    assert subjects is not None
    assert len(subjects) == 1
