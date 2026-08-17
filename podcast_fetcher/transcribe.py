from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import requests

_DOWNLOAD_CHUNK_BYTES = 1 << 20  # 1 MiB
_loaded_models: dict[str, Any] = {}

# Some CDNs (e.g. Acast) blanket-block the default python-requests UA
# string as a bot heuristic, even for this fully public, unauthenticated
# audio. An honest, identifying UA (same idea as any podcast app sends)
# gets through; no impersonation involved.
_REQUEST_HEADERS = {
    "User-Agent": "Podcast_Fetcher/1.0 (+https://github.com/SimonPlc/Podcast_Fetcher)"
}


@contextmanager
def downloaded_audio(url: str, *, timeout: int = 120) -> Iterator[Path]:
    """Stream an episode's audio enclosure to a temp file for the
    duration of the `with` block; the file (and its containing temp
    directory) is always removed on exit, success or failure.
    """
    with tempfile.TemporaryDirectory(prefix="podcast_fetcher_audio_") as tmp_dir:
        dest = Path(tmp_dir) / "episode_audio"
        with requests.get(url, stream=True, timeout=timeout, headers=_REQUEST_HEADERS) as response:
            response.raise_for_status()
            with dest.open("wb") as f:
                for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                    if chunk:
                        f.write(chunk)
        yield dest


def transcribe_audio(path: Path, model: str) -> str:
    """Transcribe an audio file with local Whisper.

    `whisper` (and its heavy torch dependency) is imported lazily so
    that importing this module -- and everything that imports it, like
    collect.py -- never requires Whisper to be installed. Only actually
    calling this function does. Loaded models are cached per process so
    a run processing several episodes doesn't reload the model each time.
    """
    import whisper  # noqa: PLC0415 -- deliberately lazy, see docstring

    if model not in _loaded_models:
        _loaded_models[model] = whisper.load_model(model)
    result = _loaded_models[model].transcribe(str(path))
    return str(result["text"]).strip()
