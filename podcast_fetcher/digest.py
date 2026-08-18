from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import date

from podcast_fetcher.config import Config
from podcast_fetcher.gmail import mint_access_token, send_email
from podcast_fetcher.models import Brief
from podcast_fetcher.render import render_digest
from podcast_fetcher.store import load_pending, save_pending
from podcast_fetcher.synthesize import build_queue_payload, synthesize_digest

logger = logging.getLogger(__name__)

SynthesizeFn = Callable[..., Brief]
MintTokenFn = Callable[[str, str, str], str]
SendFn = Callable[..., None]


def run_digest(
    config: Config,
    env: Mapping[str, str],
    *,
    synthesize: SynthesizeFn = synthesize_digest,
    mint_token: MintTokenFn = mint_access_token,
    send: SendFn = send_email,
    today: date | None = None,
) -> None:
    """Read the pending queue, synthesize a cross-episode brief (or a
    quiet-day note if nothing is queued), render it, and email it. The
    queue is cleared only after a successful send -- if sending fails,
    the exception propagates and the queue is left untouched so the
    next run can retry rather than silently losing that day's episodes.
    The processed/dedup store is never read or written here.
    """
    today = today or date.today()
    pending = load_pending()
    _, sources_by_id = build_queue_payload(pending)

    if sources_by_id:
        brief = synthesize(pending, claude_model=config.claude_model)
        subject = brief.headline
        logger.info("digest: synthesized brief from %d queued episode(s)", len(sources_by_id))
    else:
        brief = None
        subject = f"Podcast Fetcher: quiet day ({today.isoformat()})"
        logger.info("digest: queue empty, sending quiet-day note")

    html, text = render_digest(brief, sources_by_id)

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
