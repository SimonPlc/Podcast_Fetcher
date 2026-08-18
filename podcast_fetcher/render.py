from __future__ import annotations

import html as html_lib
from collections.abc import Sequence
from typing import Any

from podcast_fetcher.models import ScoredCandidate

_QUIET_MESSAGE = "Nothing scored relevant enough for today's digest -- quiet day, but the pipeline ran."

_STYLE_BODY = 'font-family: -apple-system, Arial, sans-serif; max-width: 640px; margin: 0 auto; color: #1a1a1a;'
_STYLE_CARD = 'border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 16px;'
_STYLE_META = 'color: #888; font-size: 12px;'
_STYLE_TAG = (
    'display: inline-block; background: #eef; color: #446; border-radius: 4px; '
    'padding: 2px 8px; margin-right: 4px; font-size: 11px;'
)

# Both source kinds render into the same card shape (SPEC: one unified list,
# no separate section); only this action word differs. Default to "Listen"
# so records with no "kind" (podcast episodes, including any already
# committed to state before articles existed) still render correctly.
_LINK_LABELS = {"article": "Read"}
_DEFAULT_LINK_LABEL = "Listen"


def _link_label(record: dict[str, Any]) -> str:
    return _LINK_LABELS.get(record.get("kind", "podcast"), _DEFAULT_LINK_LABEL)


def render_digest(items: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Render one card per queued episode, highest relevance score
    first -- so the shows worth listening to are clear and each is
    individually accessible. An empty queue renders a quiet-day note
    (SPEC: "a quiet-day note when there is nothing relevant"), never an
    empty shell.
    """
    if not items:
        return _render_quiet_html(), _render_quiet_text()
    ordered = sorted(items.values(), key=lambda record: record.get("score", 0), reverse=True)
    return _render_html(ordered), _render_text(ordered)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value))


def _render_html(episodes: list[dict[str, Any]]) -> str:
    parts = [f'<div style="{_STYLE_BODY}"><h1>Morning Brief</h1>']
    for episode in episodes:
        parts.append(f'<div style="{_STYLE_CARD}">')
        title = _esc(episode.get("title", "Untitled"))
        url = _esc(episode.get("url", "#"))
        feed = _esc(episode.get("feed_name", "Unknown"))
        score = episode.get("score", "?")
        parts.append(f'<h2 style="margin-top: 0;"><a href="{url}">{title}</a></h2>')
        parts.append(
            f'<p style="{_STYLE_META}">{feed} &middot; score {score}/5 '
            f'&middot; <a href="{url}">{_link_label(episode)}</a></p>'
        )

        tags = episode.get("tags") or []
        if tags:
            parts.append("".join(f'<span style="{_STYLE_TAG}">{_esc(tag)}</span>' for tag in tags))

        one_liner = episode.get("one_liner")
        if one_liner:
            parts.append(f"<p><em>{_esc(one_liner)}</em></p>")

        summary = episode.get("summary") or []
        if summary:
            parts.append("<ul>" + "".join(f"<li>{_esc(bullet)}</li>" for bullet in summary) + "</ul>")

        key_claims = episode.get("key_claims") or []
        if key_claims:
            parts.append(f'<p style="{_STYLE_META}"><strong>Key claims</strong></p>')
            parts.append("<ul>" + "".join(f"<li>{_esc(claim)}</li>" for claim in key_claims) + "</ul>")

        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def _render_text(episodes: list[dict[str, Any]]) -> str:
    lines = ["MORNING BRIEF", ""]
    for episode in episodes:
        title = episode.get("title", "Untitled")
        feed = episode.get("feed_name", "Unknown")
        score = episode.get("score", "?")
        lines.append(f"{title} ({feed}) -- score {score}/5")
        lines.append(f"{_link_label(episode)}: {episode.get('url', '')}")

        one_liner = episode.get("one_liner")
        if one_liner:
            lines.append(one_liner)

        tags = episode.get("tags") or []
        if tags:
            lines.append("Tags: " + ", ".join(tags))

        for bullet in episode.get("summary") or []:
            lines.append(f"- {bullet}")

        key_claims = episode.get("key_claims") or []
        if key_claims:
            lines.append("Key claims:")
            for claim in key_claims:
                lines.append(f"- {claim}")

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_quiet_html() -> str:
    return f'<div style="{_STYLE_BODY}"><p>{_esc(_QUIET_MESSAGE)}</p></div>'


def _render_quiet_text() -> str:
    return _QUIET_MESSAGE + "\n"


# --- Monthly discovery-sweep email (ticket #5) ---

_DISCOVERY_INTRO = (
    "Monthly discovery sweep -- nothing was added automatically. Review each "
    "candidate below and add it to feeds.yaml yourself if it's worth including."
)
_DISCOVERY_QUIET_MESSAGE = "No new candidate shows found this month."
_DISCOVERY_UNSCORED_NOTE = (
    "Claude relevance scoring failed for this sweep, so these candidates are "
    "UNSCORED and shown unfiltered -- review them more carefully than usual."
)


def render_discovery(candidates: Sequence[ScoredCandidate], *, unscored: bool = False) -> tuple[str, str]:
    """Render the monthly discover-run email: one row per proposed show
    (name, feed URL, score, one-line reason, and the search term that
    surfaced it), or a no-new-candidates note if the sweep found nothing
    that cleared the threshold -- mirroring render_digest's quiet-day
    note rather than an empty shell. Always states plainly that nothing
    was added automatically: discover only ever proposes, a human
    approves by hand-editing feeds.yaml (SPEC.md).

    `unscored=True` (issue #8's scoring-failure fallback) means every
    `ScoredCandidate.score`/`.reason` is None -- Claude scoring failed
    and the whole surviving candidate list is being emailed unfiltered
    instead of sending nothing, and the email says so explicitly rather
    than silently showing blank scores.
    """
    if not candidates:
        return _render_discovery_quiet_html(), _render_discovery_quiet_text()
    return _render_discovery_html(candidates, unscored=unscored), _render_discovery_text(candidates, unscored=unscored)


def _render_discovery_html(candidates: Sequence[ScoredCandidate], *, unscored: bool) -> str:
    parts = [
        f'<div style="{_STYLE_BODY}"><h1>New Show Candidates</h1>',
        f"<p><strong>{_esc(_DISCOVERY_INTRO)}</strong></p>",
    ]
    if unscored:
        parts.append(f'<p style="color: #b00020;"><strong>{_esc(_DISCOVERY_UNSCORED_NOTE)}</strong></p>')
    for item in candidates:
        candidate = item.candidate
        parts.append(f'<div style="{_STYLE_CARD}">')
        parts.append(f'<h2 style="margin-top: 0;">{_esc(candidate.name)}</h2>')
        if item.score is not None:
            parts.append(f'<p style="{_STYLE_META}">Score: {item.score}/5</p>')
            if item.reason:
                parts.append(f"<p><em>{_esc(item.reason)}</em></p>")
        else:
            parts.append(f'<p style="{_STYLE_META}">Score: unscored</p>')
        parts.append(f'<p style="{_STYLE_META}">Feed: {_esc(candidate.feed_url)}</p>')
        parts.append(f'<p style="{_STYLE_META}">Found via search term: &quot;{_esc(candidate.term)}&quot;</p>')
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def _render_discovery_text(candidates: Sequence[ScoredCandidate], *, unscored: bool) -> str:
    lines = ["NEW SHOW CANDIDATES", "", _DISCOVERY_INTRO, ""]
    if unscored:
        lines.append(_DISCOVERY_UNSCORED_NOTE)
        lines.append("")
    for item in candidates:
        candidate = item.candidate
        lines.append(candidate.name)
        if item.score is not None:
            lines.append(f"Score: {item.score}/5")
            if item.reason:
                lines.append(item.reason)
        else:
            lines.append("Score: unscored")
        lines.append(f"Feed: {candidate.feed_url}")
        lines.append(f'Found via search term: "{candidate.term}"')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_discovery_quiet_html() -> str:
    return f'<div style="{_STYLE_BODY}"><p>{_esc(_DISCOVERY_QUIET_MESSAGE)}</p><p>{_esc(_DISCOVERY_INTRO)}</p></div>'


def _render_discovery_quiet_text() -> str:
    return _DISCOVERY_QUIET_MESSAGE + "\n" + _DISCOVERY_INTRO + "\n"
