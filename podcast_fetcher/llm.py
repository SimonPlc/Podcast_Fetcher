from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any


class LLMParseError(ValueError):
    """Raised when a model response contains no valid JSON object."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_object(raw: str) -> dict[str, Any]:
    """Extract a JSON object from a model's raw text response.

    Tolerates the common ways models fail to return "just JSON": a
    ```json fenced block, or the object sitting inside surrounding prose
    ("Here is the analysis: {...}"). Tries, in order: the whole string as
    JSON, the contents of the first fenced code block, then the first
    balanced {...} span found anywhere in the string. Raises
    LLMParseError if none of those parse to a JSON object.
    """
    for candidate in _candidates(raw):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LLMParseError(f"no JSON object found in model output: {raw[:200]!r}")


def _candidates(raw: str) -> list[str]:
    candidates = [raw.strip()]

    fence_match = _FENCE_RE.search(raw)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    brace_span = _first_balanced_braces(raw)
    if brace_span:
        candidates.append(brace_span)

    return candidates


def _first_balanced_braces(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def run_claude(prompt: str, stdin_text: str, *, model: str | None = None, timeout: int = 600) -> str:
    """Run the Claude Code CLI as a subprocess, drawing on the caller's
    subscription quota rather than metered API billing (see SPEC.md).
    `prompt` is the instructions; `stdin_text` (e.g. a transcript) is
    piped in so it doesn't have to be embedded/escaped in the prompt.
    """
    # Resolve via PATH/PATHEXT ourselves (shutil.which) rather than
    # leaving it to subprocess: on Windows the CLI is a .cmd/.ps1 shim,
    # and plain CreateProcess (what subprocess uses without shell=True)
    # doesn't search PATHEXT, so "claude" alone isn't found there.
    claude_path = shutil.which("claude") or "claude"
    cmd = [claude_path, "-p", prompt, "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    result = subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr[:500]}")
    return result.stdout
