from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

# If run_claude is ever invoked from inside an active Claude Code
# session (e.g. manual local testing, or a wrapper script launched from
# one), these env vars leak into the subprocess and make the CLI treat
# itself as a child of that session -- pulling in its context (project
# memory, ongoing conversation) instead of running as a fresh, isolated
# call. GitHub Actions runners never have these set, so production is
# unaffected; stripping them here just makes every invocation behave
# the same regardless of where it's launched from. An explicit denylist
# (not a "CLAUDE*" prefix strip) because CLAUDE_CODE_OAUTH_TOKEN, which
# authentication depends on, must survive.
_SESSION_ENV_VARS = {
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "CLAUDECODE",
    "AI_AGENT",
}


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


def _resolve_claude_executable() -> str:
    """Locate the claude CLI, preferring a real executable over a shell
    shim wherever possible.

    On Windows, `claude` typically installs as a `.cmd`/`.ps1` shim in
    the npm global bin dir, which wraps a real `claude.exe` a few
    directories deeper (`node_modules/@anthropic-ai/claude-code/bin/`).
    Invoking the shim requires Windows to route the call through
    cmd.exe (plain CreateProcess can't execute a .cmd directly) -- and
    that extra hop was confirmed, via direct testing, to silently
    truncate large piped stdin before it ever reached the model. Using
    the real .exe directly avoids the hop, and the truncation, entirely.
    Other platforms have no such shim/relay, so a plain PATH lookup
    (shutil.which) is correct there as-is.
    """
    if os.name == "nt":
        exec_path = os.environ.get("CLAUDE_CODE_EXECPATH")
        if exec_path and Path(exec_path).is_file():
            return exec_path

        which_path = shutil.which("claude")
        if which_path:
            candidate = (
                Path(which_path).parent
                / "node_modules"
                / "@anthropic-ai"
                / "claude-code"
                / "bin"
                / "claude.exe"
            )
            if candidate.is_file():
                return str(candidate)

    return shutil.which("claude") or "claude"


def run_claude(prompt: str, stdin_text: str, *, model: str | None = None, timeout: int = 600) -> str:
    """Run the Claude Code CLI as a subprocess, drawing on the caller's
    subscription quota rather than metered API billing (see SPEC.md).
    `prompt` is the instructions; `stdin_text` (e.g. a transcript) is
    piped in so it doesn't have to be embedded/escaped in the prompt.
    """
    claude_path = _resolve_claude_executable()
    cmd = [claude_path, "-p", prompt, "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    clean_env = {key: value for key, value in os.environ.items() if key not in _SESSION_ENV_VARS}
    result = subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=clean_env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr[:500]}")
    return result.stdout
