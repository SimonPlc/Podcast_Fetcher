from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import requests

_DOWNLOAD_CHUNK_BYTES = 1 << 20  # 1 MiB
_loaded_models: dict[str, Any] = {}

# Whisper `small` mishears finance jargon (e.g. "least cost resolution" ->
# "lease cost resolution", "IORB"/"SOFR"/"SOMA" garbled), and the extraction
# model then faithfully repeats the error. Passing a domain glossary as
# Whisper's `initial_prompt` biases decoding toward these terms at the source,
# for zero extra compute -- cheaper and safer than a larger, slower model.
# It is prior context, not a transcript prefix, so it never appears in output.
_DOMAIN_PROMPT = (
    "Finance and markets discussion. Likely terms: repo, reverse repo, SOFR, "
    "IORB, OIS, basis, standing repo facility (SRF), discount window, reserves, "
    "SOMA, FOMC, FHLB, quantitative tightening (QT), quantitative easing (QE), "
    "Treasury bills, T-bills, MBS, agency MBS, LCR (liquidity coverage ratio), "
    "least cost resolution, FDIC, SVB, CLO, ABS, RMBS, CMBS, CDS, CDX, iTraxx, "
    "total return swap, securitization, leveraged finance, private credit, "
    "investment grade, high yield, collateral, duration, front-end rates."
)

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
    """Transcribe an audio file with local faster-whisper.

    faster-whisper is a CTranslate2 reimplementation of Whisper: the same
    models, but ~4x faster on CPU with int8 quantisation and no torch
    dependency -- which is what lets the more accurate `medium` model run
    on the free CPU runner within the collect time budget, roughly where
    openai-whisper's `small` used to land.

    `faster_whisper` is imported lazily so that importing this module --
    and everything that imports it, like collect.py -- never requires the
    transcription stack to be installed; only actually calling this
    function does. Loaded models are cached per process so a run
    processing several episodes doesn't reload the model each time.
    """
    from faster_whisper import WhisperModel  # noqa: PLC0415 -- deliberately lazy, see docstring

    if model not in _loaded_models:
        _loaded_models[model] = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _info = _loaded_models[model].transcribe(
        str(path),
        initial_prompt=_DOMAIN_PROMPT,
        language="en",
    )
    # transcribe() returns a lazy generator of segments; consuming it is
    # what actually runs the model. Each segment.text carries a leading
    # space, so strip per-segment and rejoin.
    return " ".join(segment.text.strip() for segment in segments).strip()
