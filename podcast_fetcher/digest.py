from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import date

from podcast_fetcher.config import Config
from podcast_fetcher.gmail import mint_access_token, send_email
from podcast_fetcher.render import render_digest
from podcast_fetcher.store import load_pending, save_pending

logger = logging.getLogger(__name__)

MintTokenFn = Callable[[str, str, str], str]
SendFn = Callable[..., None]


def run_digest(
    config: Config,
    env: Mapping[str, str],
    *,
    mint_token: MintTokenFn = mint_access_token,
    send: SendFn = send_email,
    today: date | None = None,
) -> None:
    """Read the pending queue and email one card per episode (highest
    relevance score first), or a quiet-day note if nothing is queued.
    No LLM call happens here: each episode's card is built entirely
    from the extraction already computed at collect time. The queue is
    cleared only after a successful send -- if sending fails, the
    exception propagates and the queue is left untouched so the next
    run can retry rather than silently losing that day's episodes. The
    processed/dedup store is never read or written here.
    """
    today = today or date.today()
    pending = load_pending()
    items = pending.get("queued", {})

    if items:
        subject = f"Podcast Digest -- {today.isoformat()} ({len(items)} episode{'s' if len(items) != 1 else ''})"
        logger.info("digest: rendering %d queued episode(s)", len(items))
    else:
        subject = f"Podcast Fetcher: quiet day ({today.isoformat()})"
        logger.info("digest: queue empty, sending quiet-day note")

    html, text = render_digest(items)

    if not config.email_to or not config.email_from:
        raise RuntimeError("EMAIL_TO and EMAIL_FROM must be set to send the digest")

    client_id = _require_env(env, "GMAIL_CLIENT_ID")
    client_secret = _require_env(env, "GMAIL_CLIENT_SECRET")
    refresh_token = _require_env(env, "GMAIL_REFRESH_TOKEN")

    access_token = mint_token(client_id, client_secret, refresh_token)
    send(
        access_token,
        to_addr=config.email_to,
        from_addr=config.email_from,
        subject=subject,
        text=text,
        html=html,
    )
    logger.info("digest: email sent to %s", config.email_to)

    save_pending({"queued": {}})


def _require_env(env: Mapping[str, str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise RuntimeError(f"{key} must be set to send the digest")
    return value
