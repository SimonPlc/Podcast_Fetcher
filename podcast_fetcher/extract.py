from __future__ import annotations

from pathlib import Path

from podcast_fetcher.llm import LLMParseError, parse_json_object, run_claude
from podcast_fetcher.models import Article, Episode, ExtractResult

PROMPT_PATH = "prompts/extract.txt"

_REQUIRED_STRING_LIST_FIELDS = ("tags", "summary", "key_claims")

# The shared prompt has one {{KIND}} placeholder telling the model what
# kind of source item it's reading, so it can calibrate (e.g. an abstract
# is a purpose-written summary, not the paper -- see prompts/extract.txt).
_KIND_PLACEHOLDER = "{{KIND}}"
_KIND_DESCRIPTIONS = {
    "transcript": "a transcript of one podcast episode",
    "article": "the full text of one written article",
    "abstract": "the abstract of one longer research paper -- not the full paper",
}


def load_extract_prompt(path: str | Path = PROMPT_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def render_extract_prompt(kind: str, *, prompt: str | None = None) -> str:
    """Fill the shared extraction prompt's {{KIND}} placeholder.

    Plain string replace, not str.format: the prompt's JSON example is
    full of literal `{`/`}` characters that .format would choke on.
    """
    instructions = prompt if prompt is not None else load_extract_prompt()
    return instructions.replace(_KIND_PLACEHOLDER, _KIND_DESCRIPTIONS[kind])


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
    instructions = render_extract_prompt("transcript", prompt=prompt)
    raw = run_claude(instructions, transcript, model=claude_model)
    return parse_extraction(raw)


def extract_article(
    article: Article,
    *,
    claude_model: str | None = None,
    prompt: str | None = None,
) -> ExtractResult:
    """Run the extraction prompt against one article's (or abstract's)
    body -- same prompt and strict-JSON contract as extract_episode, just
    told which kind of source it's reading via article.source_kind.
    """
    instructions = render_extract_prompt(article.source_kind, prompt=prompt)
    raw = run_claude(instructions, article.body, model=claude_model)
    return parse_extraction(raw)
