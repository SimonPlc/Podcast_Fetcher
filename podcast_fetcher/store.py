from __future__ import annotations

from pathlib import Path

from podcast_fetcher.state import read_json, write_json_atomic

PROCESSED_PATH = "state/emailed_episodes.json"
PENDING_PATH = "state/pending_digest.json"


def load_processed(path: str | Path = PROCESSED_PATH) -> dict:
    return read_json(path, default={"processed": {}})


def load_processed_ids(path: str | Path = PROCESSED_PATH) -> set[str]:
    return set(load_processed(path).get("processed", {}).keys())


def save_processed(processed: dict, path: str | Path = PROCESSED_PATH) -> None:
    write_json_atomic(path, processed)


def load_pending(path: str | Path = PENDING_PATH) -> dict:
    return read_json(path, default={"queued": {}})


def load_queued_ids(path: str | Path = PENDING_PATH) -> set[str]:
    return set(load_pending(path).get("queued", {}).keys())


def save_pending(pending: dict, path: str | Path = PENDING_PATH) -> None:
    write_json_atomic(path, pending)
