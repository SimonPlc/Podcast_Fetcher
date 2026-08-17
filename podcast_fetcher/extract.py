from __future__ import annotations

from pathlib import Path

from podcast_fetcher.llm import LLMParseError, parse_json_object, run_claude
from podcast_fetcher.models import Episode, ExtractResult

PROMPT_PATH = "prompts/extract.txt"

_REQUIRED_STRING_LIST_FIELDS = ("tags", "summary", "key_claims")


def load_extract_prompt(path: str | Path = PROMPT_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def parse_extraction(raw: str) -> ExtractResult:
    """Parse and validate a raw Claude response into an ExtractResult.

    Tolerant about *how* the JSON is wrapped (see parse_json_object) but
    strict about its shape: a missing field, wrong type, or an
    out-of-range score all raise LLMParseError rather than silently
    producing a malformed record that could poison the digest.
    """
    data = parse_json_object(raw)

    if "score" not in data:
        raise LLMParseError(f"extraction missing 'score': {data!r}")
    score = data["score"]
    if not isinstance(score, int) or isinstance(score, bool):
        raise LLMParseError(f"extraction 'score' must be an integer, got {score!r}")
    if not 1 <= score <= 5:
        raise LLMParseError(f"extraction 'score' out of range 1-5: {score!r}")

    if "one_liner" not in data or not isinstance(data["one_liner"], str):
        raise LLMParseError(f"extraction missing/invalid 'one_liner': {data!r}")

    for field in _REQUIRED_STRING_LIST_FIELDS:
        if field not in data:
            raise LLMParseError(f"extraction missing '{field}': {data!r}")
        value = data[field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise LLMParseError(f"extraction '{field}' must be a list of strings: {value!r}")

    return ExtractResult(
        score=score,
        one_liner=data["one_liner"],
        tags=list(data["tags"]),
        summary=list(data["summary"]),
        key_claims=list(data["key_claims"]),
    )


def extract_episode(
    episode: Episode,
    transcript: str,
    *,
    claude_model: str | None = None,
    prompt: str | None = None,
) -> ExtractResult:
    """Run the extraction prompt against one episode's transcript."""
    instructions = prompt if prompt is not None else load_extract_prompt()
    raw = run_claude(instructions, transcript, model=claude_model)
    return parse_extraction(raw)
