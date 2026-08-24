from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
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

# The Claude CLI only needs its own auth token (CLAUDE_CODE_OAUTH_TOKEN) to
# run; it never sends email. The Gmail send credentials sit in the same
# process env on the GitHub runner, but this subprocess is the one place that
# feeds untrusted transcript/article text to a model, so there is no reason to
# expose them to it. Stripping them is defence in depth -- no known exploit
# path, but it keeps the secrets out of the process that reads untrusted input.
_SECRET_ENV_VARS = {
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "EMAIL_TO",
    "EMAIL_FROM",
}


class LLMParseError(ValueError):
    """Raised when a model response contains no valid JSON object.

    Episode-side (issue #9): the CLI call itself succeeded, but what it
    returned is unusable. This says nothing about our pipeline, so the
    episode that produced it is recorded terminal and never retried --
    contrast ClaudeUnavailableError below.
    """


class ClaudeUnavailableError(RuntimeError):
    """Raised when the Claude Code CLI itself could not be run or failed
    outright (issue #9): the executable is missing, or it exited
    non-zero (expired/missing CLAUDE_CODE_OAUTH_TOKEN, a subscription
    rate limit, a transient CLI crash, ...).

    Our-side, not episode-side: it says nothing about whatever episode
    happened to be in flight, so collect.py must not burn that episode
    as `failed` when this is raised -- see collect.run_collect's
    handling of the extraction call, and llm.check_claude_available for
    the preflight check run before any transcription starts.
    """


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
    stripped = _SESSION_ENV_VARS | _SECRET_ENV_VARS
    clean_env = {key: value for key, value in os.environ.items() if key not in stripped}
    try:
        result = subprocess.run(
            cmd,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=clean_env,
        )
    except FileNotFoundError as exc:
        # The executable couldn't even be launched (not installed, PATH
        # wrong, ...) -- our-side, exactly like a non-zero exit below.
        raise ClaudeUnavailableError(f"claude CLI executable not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        # A hung CLI (an auth prompt waiting on stdin, a wedged request,
        # ...) is our-side too, not the episode's fault -- so it must
        # defer rather than burn the in-flight episode. At preflight it
        # aborts the whole run, same as any other ClaudeUnavailableError.
        raise ClaudeUnavailableError(f"claude CLI timed out after {timeout}s") from exc
    if result.returncode != 0:
        raise ClaudeUnavailableError(f"claude CLI exited {result.returncode}: {_describe_failure(result)}")
    return result.stdout


def _describe_failure(result: subprocess.CompletedProcess[str]) -> str:
    """Summarise a failed CLI run for the exception message, drawing on
    BOTH streams.

    In `-p --output-format text` mode the CLI writes its human-readable
    error (an expired token, or "usage limit reached" when a
    subscription cap is exhausted) to stdout, not stderr -- so a
    stderr-only message came back blank during the 2026-08 weekly-limit
    outage and hid the cause entirely. Include whichever stream(s)
    carried text, labelled, and say plainly when both were empty.
    """
    parts = []
    if result.stderr and result.stderr.strip():
        parts.append(f"stderr: {result.stderr.strip()[:500]}")
    if result.stdout and result.stdout.strip():
        parts.append(f"stdout: {result.stdout.strip()[:500]}")
    return " | ".join(parts) or "(no output on stderr or stdout)"


RunClaudeFn = Callable[..., str]


def check_claude_available(*, model: str | None = None, run: RunClaudeFn = run_claude) -> None:
    """Preflight health check (issue #9) used by collect.run_collect
    before any download/transcribe work starts. Makes one cheap
    run_claude call and lets ClaudeUnavailableError propagate; the
    caller treats that as "abort the run, retry next time" rather than
    burning Whisper CPU on episodes a known-bad CLI can't score anyway.
    Returns None on success -- the caller only cares whether this
    raised.
    """
    run("Reply with exactly the word OK and nothing else.", "", model=model)
