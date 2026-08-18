from __future__ import annotations

from pathlib import Path

PERSONA_PATH = "prompts/persona.txt"

# Both prompts/extract.txt (per-item extraction, ticket #2/#7) and
# prompts/score_candidates.txt (batched show-scoring, ticket #8) need the
# same relevance persona (priorities, educational-expansion note, 1-5
# scale). Factored out here so there is exactly one statement of those
# priorities rather than two copies that can silently drift apart.
_PERSONA_PLACEHOLDER = "{{PERSONA}}"


def load_persona(path: str | Path = PERSONA_PATH) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def render_with_persona(prompt: str, *, persona: str | None = None) -> str:
    """Fill a prompt's {{PERSONA}} placeholder with the shared persona
    text. Plain string replace, not str.format -- same reasoning as
    extract.render_extract_prompt: the prompts' JSON examples are full of
    literal `{`/`}` characters .format would choke on.
    """
    text = persona if persona is not None else load_persona()
    return prompt.replace(_PERSONA_PLACEHOLDER, text)
