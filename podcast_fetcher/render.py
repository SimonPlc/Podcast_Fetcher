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


def _render_recap_html(episode: dict[str, Any]) -> str:
    """Recap block: new-shape records carry `recap` (a prose paragraph);
    the two episodes already queued in state/pending_digest.json when the
    recap format shipped instead carry the old bullet-point `summary`
    list and no `recap` at all, so they still render as bullets rather
    than going blank (backward compat -- see the recap-format ticket).
    """
    recap = episode.get("recap")
    if recap:
        return f"<p>{_esc(recap)}</p>"
    summary = episode.get("summary") or []
    if summary:
        return "<ul>" + "".join(f"<li>{_esc(bullet)}</li>" for bullet in summary) + "</ul>"
    return ""


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

        recap_html = _render_recap_html(episode)
        if recap_html:
            parts.append(recap_html)

        implications = episode.get("implications")
        if implications:
            parts.append(f'<p style="{_STYLE_META}"><strong>Why it matters</strong></p>')
            parts.append(f"<p>{_esc(implications)}</p>")

        watch = episode.get("watch") or []
        if watch:
            parts.append(f'<p style="{_STYLE_META}"><strong>Watch</strong></p>')
            parts.append("<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in watch) + "</ul>")

        terms = episode.get("terms") or []
        if terms:
            parts.append(f'<p style="{_STYLE_META}"><strong>Terms</strong></p>')
            parts.append("<ul>" + "".join(f"<li>{_esc(term)}</li>" for term in terms) + "</ul>")

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

        # Recap block: new-shape records carry `recap` (prose); old-shape
        # records (already-queued episodes from before the recap format
        # shipped) carry `summary` bullets instead -- see
        # _render_recap_html for the same backward-compat reasoning.
        recap = episode.get("recap")
        if recap:
            lines.append(recap)
        else:
            for bullet in episode.get("summary") or []:
                lines.append(f"- {bullet}")

        implications = episode.get("implications")
        if implications:
            lines.append("Why it matters:")
            lines.append(implications)

        watch = episode.get("watch") or []
        if watch:
            lines.append("Watch:")
            for item in watch:
                lines.append(f"- {item}")

        terms = episode.get("terms") or []
        if terms:
            lines.append("Terms:")
            for term in terms:
                lines.append(f"- {term}")

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
_DISCOVERY_SCORING_UNAVAILABLE = (
    "Claude relevance scoring was unavailable for this sweep, so no candidates "
    "could be judged. Nothing has been proposed and nothing has been marked as "
    "seen; every candidate will be reconsidered on the next run."
)


def _deferred_note(deferred_count: int) -> str:
    shows = "show" if deferred_count == 1 else "shows"
    return (
        f"{deferred_count} further candidate {shows} could not be scored this run "
        f"and will be retried next time."
    )


def render_discovery(candidates: Sequence[ScoredCandidate], *, deferred_count: int = 0) -> tuple[str, str]:
    """Render the monthly discover-run email: one row per proposed show
    (name, feed URL, score, one-line reason, and the search term that
    surfaced it), or a no-new-candidates note if the sweep found nothing
    that cleared the threshold -- mirroring render_digest's quiet-day
    note rather than an empty shell. Always states plainly that nothing
    was added automatically: discover only ever proposes, a human
    approves by hand-editing feeds.yaml (SPEC.md).

    `deferred_count` is how many candidates could not be scored (their
    chunk failed, or the model omitted them). They are never listed,
    because an unvetted show is exactly what this email exists to filter
    out, but their number is reported so a silently shrinking sweep is
    visible. With no candidates at all and a non-zero deferred count,
    the whole scoring pass failed and the email says so.
    """
    if not candidates:
        if deferred_count:
            return _render_unavailable_html(), _render_unavailable_text()
        return _render_discovery_quiet_html(), _render_discovery_quiet_text()
    return (
        _render_discovery_html(candidates, deferred_count),
        _render_discovery_text(candidates, deferred_count),
    )


def _render_discovery_html(candidates: Sequence[ScoredCandidate], deferred_count: int) -> str:
    parts = [
        f'<div style="{_STYLE_BODY}"><h1>New Show Candidates</h1>',
        f"<p><strong>{_esc(_DISCOVERY_INTRO)}</strong></p>",
    ]
    for item in candidates:
        candidate = item.candidate
        parts.append(f'<div style="{_STYLE_CARD}">')
        parts.append(f'<h2 style="margin-top: 0;">{_esc(candidate.name)}</h2>')
        parts.append(f'<p style="{_STYLE_META}">Score: {item.score}/5</p>')
        if item.reason:
            parts.append(f"<p><em>{_esc(item.reason)}</em></p>")
        parts.append(f'<p style="{_STYLE_META}">Feed: {_esc(candidate.feed_url)}</p>')
        parts.append(f'<p style="{_STYLE_META}">Found via search term: &quot;{_esc(candidate.term)}&quot;</p>')
        parts.append("</div>")
    if deferred_count:
        parts.append(f'<p style="{_STYLE_META}">{_esc(_deferred_note(deferred_count))}</p>')
    parts.append("</div>")
    return "\n".join(parts)


def _render_discovery_text(candidates: Sequence[ScoredCandidate], deferred_count: int) -> str:
    lines = ["NEW SHOW CANDIDATES", "", _DISCOVERY_INTRO, ""]
    for item in candidates:
        candidate = item.candidate
        lines.append(candidate.name)
        lines.append(f"Score: {item.score}/5")
        if item.reason:
            lines.append(item.reason)
        lines.append(f"Feed: {candidate.feed_url}")
        lines.append(f'Found via search term: "{candidate.term}"')
        lines.append("")
    if deferred_count:
        lines.append(_deferred_note(deferred_count))
    return "\n".join(lines).rstrip() + "\n"


def _render_discovery_quiet_html() -> str:
    return f'<div style="{_STYLE_BODY}"><p>{_esc(_DISCOVERY_QUIET_MESSAGE)}</p><p>{_esc(_DISCOVERY_INTRO)}</p></div>'


def _render_discovery_quiet_text() -> str:
    return _DISCOVERY_QUIET_MESSAGE + "\n" + _DISCOVERY_INTRO + "\n"


def _render_unavailable_html() -> str:
    return (
        f'<div style="{_STYLE_BODY}">'
        f'<p style="color: #b00020;"><strong>{_esc(_DISCOVERY_SCORING_UNAVAILABLE)}</strong></p></div>'
    )


def _render_unavailable_text() -> str:
    return _DISCOVERY_SCORING_UNAVAILABLE + "\n"
