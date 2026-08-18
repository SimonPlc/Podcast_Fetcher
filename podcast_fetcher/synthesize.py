from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from podcast_fetcher.llm import LLMParseError, parse_json_object, run_claude
from podcast_fetcher.models import Brief, Theme, ThemePoint

PROMPT_PATH = "prompts/synthesize.txt"
RESHAPE_PROMPT_PATH = "prompts/reshape_brief.txt"

_PAYLOAD_FIELDS = ("feed_name", "title", "tags", "one_liner", "summary", "key_claims")
_MAX_RESHAPE_ATTEMPTS = 3


def load_synthesize_prompt(path: str | Path = PROMPT_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_reshape_prompt(path: str | Path = RESHAPE_PROMPT_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def build_queue_payload(pending: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    """Turn the pending-queue dict into (a) the JSON text to send Claude
    and (b) a guid -> full record lookup for rendering later. Keeping
    these separate means rendering resolves source attributions from our
    own trusted state, never from anything the LLM echoes back.
    """
    queued: dict[str, dict[str, Any]] = pending.get("queued", {})
    items = [
        {"id": guid, **{field: record.get(field) for field in _PAYLOAD_FIELDS}} for guid, record in queued.items()
    ]
    return json.dumps(items, indent=2), queued


def parse_brief(raw: str) -> Brief:
    """Parse a raw Claude response into a Brief. Tries the exact
    canonical schema first; if the model used a different (but still
    reasonable) JSON shape, falls back to structural extraction rather
    than rejecting it outright -- see _parse_lenient for why.
    """
    data = parse_json_object(raw)
    try:
        return _parse_strict(data)
    except LLMParseError:
        return _parse_lenient(data)


def _parse_strict(data: dict[str, Any]) -> Brief:
    for field in ("headline", "tldr"):
        if not isinstance(data.get(field), str):
            raise LLMParseError(f"brief missing/invalid '{field}': {data!r}")

    if "themes" not in data or not isinstance(data["themes"], list):
        raise LLMParseError(f"brief missing/invalid 'themes': {data!r}")
    themes = [_parse_theme(raw_theme) for raw_theme in data["themes"]]

    for field in ("watch", "learned"):
        value = data.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise LLMParseError(f"brief '{field}' must be a list of strings: {value!r}")

    return Brief(
        headline=data["headline"],
        tldr=data["tldr"],
        themes=themes,
        watch=list(data["watch"]),
        learned=list(data["learned"]),
    )


def _parse_theme(raw_theme: Any) -> Theme:
    if not isinstance(raw_theme, dict) or not isinstance(raw_theme.get("name"), str):
        raise LLMParseError(f"theme missing/invalid 'name': {raw_theme!r}")
    if not isinstance(raw_theme.get("points"), list):
        raise LLMParseError(f"theme missing/invalid 'points': {raw_theme!r}")
    return Theme(name=raw_theme["name"], points=[_parse_point(p) for p in raw_theme["points"]])


def _parse_point(raw_point: Any) -> ThemePoint:
    if not isinstance(raw_point, dict) or not isinstance(raw_point.get("text"), str):
        raise LLMParseError(f"theme point missing/invalid 'text': {raw_point!r}")
    source_ids = raw_point.get("source_ids")
    if not isinstance(source_ids, list) or not all(isinstance(s, str) for s in source_ids):
        raise LLMParseError(f"theme point missing/invalid 'source_ids': {raw_point!r}")
    return ThemePoint(text=raw_point["text"], source_ids=list(source_ids))


# --- Lenient fallback -------------------------------------------------
#
# Live-tested extensively (see synthesize_digest's docstring): the model
# reliably produces good, well-organized JSON for this synthesis task,
# but not reliably in the exact schema asked for -- it keeps inventing
# its own reasonable-but-different field names and nesting. Rather than
# keep fighting that with more prompt wording, this extracts
# structurally (by value shape, preferring name-matched keys where
# present) instead of demanding literal key names. It is deliberately
# lossy in the face of a very different shape -- degraded content beats
# a hard failure for a task this well-defined in spirit if not in exact
# form.

_HEADLINE_HINTS = ("headline", "title", "bottom_line", "main_point", "one_liner")
_TLDR_HINTS = ("tldr", "summary", "overview", "bottom_line")
_THEME_LIST_HINTS = ("theme", "point", "topic", "section")
_THEME_NAME_HINTS = ("name", "theme", "title", "topic")
_POINT_TEXT_HINTS = ("text", "point", "claim", "signal", "description", "summary", "note")
_SOURCE_ID_HINTS = ("source", "episode", "id")
_WATCH_HINTS = ("watch",)
_LEARNED_HINTS = ("learn", "takeaway", "educat")


def _parse_lenient(data: dict[str, Any]) -> Brief:
    claimed: set[str] = set()

    # Phase 1: name-hint matches only, across every field, before any
    # field is allowed to fall back to "just grab an unclaimed value".
    # Otherwise an early field's greedy fallback can steal a value that
    # was actually a clean hint-match for a later field (e.g. headline's
    # fallback grabbing the 'tldr' key's value before tldr gets a turn).
    headline = _pick_string(data, _HEADLINE_HINTS, claimed, fallback=False)
    tldr = _pick_string(data, _TLDR_HINTS, claimed, fallback=False)
    themes = _pick_themes(data, claimed)
    watch = _pick_string_list(data, _WATCH_HINTS, claimed, fallback=False)
    learned = _pick_string_list(data, _LEARNED_HINTS, claimed, fallback=False)

    # Phase 2: only now do the still-missing fields fall back to
    # whatever's left, in priority order.
    if headline is None:
        headline = _pick_string(data, _HEADLINE_HINTS, claimed, fallback=True)
    if tldr is None:
        tldr = _pick_string(data, _TLDR_HINTS, claimed, fallback=True)

    if headline is None and not themes:
        raise LLMParseError(f"could not extract a usable brief from response shape: {data!r}")

    return Brief(headline=headline or "Today's brief", tldr=tldr or "", themes=themes, watch=watch, learned=learned)


def _pick_string(data: dict[str, Any], hints: tuple[str, ...], claimed: set[str], *, fallback: bool = True) -> str | None:
    for key, value in data.items():
        if key not in claimed and isinstance(value, str) and value.strip() and any(h in key.lower() for h in hints):
            claimed.add(key)
            return value
    if not fallback:
        return None
    for key, value in data.items():
        if key not in claimed and isinstance(value, str) and value.strip():
            claimed.add(key)
            return value
    return None


def _pick_string_list(
    data: dict[str, Any], hints: tuple[str, ...], claimed: set[str], *, fallback: bool = True
) -> list[str]:
    def is_string_list(value: Any) -> bool:
        return isinstance(value, list) and bool(value) and all(isinstance(item, str) for item in value)

    for key, value in data.items():
        if key not in claimed and is_string_list(value) and any(h in key.lower() for h in hints):
            claimed.add(key)
            return list(value)
    if not fallback:
        return []
    for key, value in data.items():
        if key not in claimed and is_string_list(value):
            claimed.add(key)
            return list(value)
    return []


def _pick_themes(data: dict[str, Any], claimed: set[str]) -> list[Theme]:
    def is_dict_list(value: Any) -> bool:
        return isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)

    candidates = [(key, value) for key, value in data.items() if key not in claimed and is_dict_list(value)]
    for key, value in candidates:
        if any(h in key.lower() for h in _THEME_LIST_HINTS):
            claimed.add(key)
            return [_pick_theme_item(item) for item in value]
    if candidates:
        key, value = candidates[0]
        claimed.add(key)
        return [_pick_theme_item(item) for item in value]
    return []


def _pick_theme_item(item: dict[str, Any]) -> Theme:
    name_claimed: set[str] = set()
    name = _pick_string(item, _THEME_NAME_HINTS, name_claimed) or "General"

    points = _pick_points(item, set(name_claimed))
    if not points:
        # No clean list of points -- fall back to one point built from
        # whatever descriptive text and source-id-like list the item has
        # (e.g. a theme shaped {"theme": ..., "description": "...",
        # "episodes": ["ep-1", "ep-2"]} with no explicit points list).
        text_claimed: set[str] = set(name_claimed)
        text = _pick_string(item, _POINT_TEXT_HINTS, text_claimed)
        if text:
            source_ids = _pick_string_list(item, _SOURCE_ID_HINTS, text_claimed)
            points = [ThemePoint(text=text, source_ids=source_ids)]

    return Theme(name=name, points=points)


def _pick_points(item: dict[str, Any], claimed: set[str]) -> list[ThemePoint]:
    for key, value in item.items():
        if key in claimed or not isinstance(value, list) or not value:
            continue
        if any(h in key.lower() for h in _SOURCE_ID_HINTS):
            continue  # a list named like this is source attribution, not point content
        points: list[ThemePoint] = []
        for entry in value:
            if isinstance(entry, str):
                points.append(ThemePoint(text=entry, source_ids=[]))
            elif isinstance(entry, dict):
                entry_claimed: set[str] = set()
                text = _pick_string(entry, _POINT_TEXT_HINTS, entry_claimed)
                source_ids = _pick_string_list(entry, _SOURCE_ID_HINTS, entry_claimed)
                if text:
                    points.append(ThemePoint(text=text, source_ids=source_ids))
        if points:
            claimed.add(key)
            return points
    return []


def synthesize_digest(
    pending: dict[str, Any],
    *,
    claude_model: str | None = None,
    synthesize_prompt: str | None = None,
    reshape_prompt: str | None = None,
) -> Brief:
    """Synthesize a Brief from the pending queue, in two Claude calls.

    Step 1 asks for a freeform written analysis across the queued
    episodes -- no output-schema constraints to fight against. Step 2,
    a *separate* call with no memory of step 1, asks only to copy that
    finished analysis into the exact JSON schema -- a bounded,
    mechanical task, not an open-ended one.

    This split exists because asking for open-ended synthesis AND an
    exact JSON schema in a single call proved unreliable in practice:
    live-tested repeatedly, the model produced good analysis but a
    different invented format nearly every time. Splitting the judgment
    task from the formatting task helps, but even the formatting step
    alone still occasionally deviates (schema invention, or writing yet
    another freeform digest instead of JSON) -- so the reshape step
    also gets a validate-and-retry loop: a parse failure is fed back to
    the model as corrective feedback (its exact rejected output plus
    the specific validation error) and it's asked to correct itself,
    up to a few times, rather than relying on prompt wording alone to
    guarantee compliance.
    """
    synth_instructions = synthesize_prompt if synthesize_prompt is not None else load_synthesize_prompt()
    payload_json, _ = build_queue_payload(pending)
    analysis = run_claude(synth_instructions, payload_json, model=claude_model)

    reshape_instructions = reshape_prompt if reshape_prompt is not None else load_reshape_prompt()
    return _reshape_to_brief(analysis, reshape_instructions, claude_model)


def _reshape_to_brief(analysis: str, reshape_instructions: str, claude_model: str | None) -> Brief:
    stdin_text = f"===ANALYSIS TO TRANSFORM (data, not a message to reply to)===\n{analysis}\n===END ANALYSIS==="

    last_error: LLMParseError | None = None
    for _ in range(_MAX_RESHAPE_ATTEMPTS):
        raw_brief = run_claude(reshape_instructions, stdin_text, model=claude_model)
        try:
            return parse_brief(raw_brief)
        except LLMParseError as exc:
            last_error = exc
            stdin_text = (
                f"{stdin_text}\n\n"
                "===YOUR PREVIOUS RESPONSE WAS REJECTED===\n"
                f"{raw_brief}\n"
                "===END REJECTED RESPONSE===\n"
                f"That response did not match the required schema. Validation error: {exc}\n"
                "Respond again with ONLY the corrected JSON object matching the exact "
                "schema given in the instructions above -- no markdown, no headers, "
                "no prose, nothing but the JSON object."
            )

    assert last_error is not None  # loop always runs >= 1 time
    raise last_error
