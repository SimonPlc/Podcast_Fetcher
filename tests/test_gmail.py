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

    parts = {part.get_content_type(): part.get_payload(decode=True).decode("utf-8") for part in message.walk() if not part.is_multipart()}
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
    assert len(message.get_all("Subject")) == 1
