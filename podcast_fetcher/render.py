from __future__ import annotations

import html as html_lib
from typing import Any

from podcast_fetcher.models import Brief

_QUIET_MESSAGE = "Nothing scored relevant enough to make today's brief -- quiet day, but the pipeline ran."

_STYLE_BODY = 'font-family: -apple-system, Arial, sans-serif; max-width: 640px; margin: 0 auto; color: #1a1a1a;'
_STYLE_H2 = 'font-size: 17px; margin-top: 24px;'
_STYLE_SOURCE = 'color: #888; font-size: 12px;'


def render_digest(brief: Brief | None, sources_by_id: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Render the digest email. `sources_by_id` maps episode guid ->
    trusted record (feed_name/title/url) from our own state -- source
    attributions are resolved from here, never trusted verbatim from the
    LLM's `source_ids`. `brief=None` renders the quiet-day note (SPEC:
    "a quiet-day note when there is nothing relevant"), never an empty
    shell of the populated template.
    """
    if brief is None:
        return _render_quiet_html(), _render_quiet_text()
    return _render_brief_html(brief, sources_by_id), _render_brief_text(brief, sources_by_id)


def _esc(text: str) -> str:
    return html_lib.escape(text)


def _source_label(guid: str, sources_by_id: dict[str, dict[str, Any]]) -> str:
    record = sources_by_id.get(guid)
    if record is None:
        return guid
    return f"{record.get('feed_name', 'Unknown')}: {record.get('title', guid)}"


def _render_brief_html(brief: Brief, sources_by_id: dict[str, dict[str, Any]]) -> str:
    parts = [
        f'<div style="{_STYLE_BODY}">',
        f"<h1>{_esc(brief.headline)}</h1>",
        f"<p><strong>TL;DR:</strong> {_esc(brief.tldr)}</p>",
    ]

    for theme in brief.themes:
        parts.append(f'<h2 style="{_STYLE_H2}">{_esc(theme.name)}</h2><ul>')
        for point in theme.points:
            sources = ", ".join(_source_label(sid, sources_by_id) for sid in point.source_ids)
            attribution = f' <span style="{_STYLE_SOURCE}">[{_esc(sources)}]</span>' if sources else ""
            parts.append(f"<li>{_esc(point.text)}{attribution}</li>")
        parts.append("</ul>")

    parts.append(_render_html_bullet_section("Watch", brief.watch))
    parts.append(_render_html_bullet_section("Learned", brief.learned))

    if sources_by_id:
        parts.append(f'<h2 style="{_STYLE_H2}">Sources</h2><ul>')
        for guid, record in sources_by_id.items():
            title = _esc(str(record.get("title", guid)))
            feed = _esc(str(record.get("feed_name", "Unknown")))
            url = _esc(str(record.get("url", "#")))
            parts.append(f'<li><a href="{url}">{feed}: {title}</a></li>')
        parts.append("</ul>")

    parts.append("</div>")
    return "\n".join(part for part in parts if part)


def _render_html_bullet_section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    bullets = "".join(f"<li>{_esc(item)}</li>" for item in items)
    return f'<h2 style="{_STYLE_H2}">{title}</h2><ul>{bullets}</ul>'


def _render_brief_text(brief: Brief, sources_by_id: dict[str, dict[str, Any]]) -> str:
    lines = [brief.headline, "", f"TL;DR: {brief.tldr}", ""]

    for theme in brief.themes:
        lines.append(theme.name)
        for point in theme.points:
            sources = ", ".join(_source_label(sid, sources_by_id) for sid in point.source_ids)
            suffix = f" [{sources}]" if sources else ""
            lines.append(f"- {point.text}{suffix}")
        lines.append("")

    lines += _render_text_bullet_section("WATCH", brief.watch)
    lines += _render_text_bullet_section("LEARNED", brief.learned)

    if sources_by_id:
        lines.append("SOURCES")
        for record in sources_by_id.values():
            lines.append(f"- {record.get('feed_name', 'Unknown')}: {record.get('title', '')} ({record.get('url', '')})")

    return "\n".join(lines).rstrip() + "\n"


def _render_text_bullet_section(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [title, *[f"- {item}" for item in items], ""]


def _render_quiet_html() -> str:
    return f'<div style="{_STYLE_BODY}"><p>{_esc(_QUIET_MESSAGE)}</p></div>'


def _render_quiet_text() -> str:
    return _QUIET_MESSAGE + "\n"
