from __future__ import annotations

import logging
import os
import sys

from podcast_fetcher.collect import run_collect
from podcast_fetcher.config import load_config
from podcast_fetcher.digest import run_digest
from podcast_fetcher.discover import run_discover
from podcast_fetcher.feeds import load_discovery_terms, load_feeds

FEEDS_PATH = "feeds.yaml"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(os.environ)

    if config.run_mode == "collect":
        run_collect(load_feeds(FEEDS_PATH), config)
        return 0

    if config.run_mode == "digest":
        run_digest(config, os.environ, load_feeds(FEEDS_PATH))
        return 0

    if config.run_mode == "discover":
        run_discover(load_feeds(FEEDS_PATH), load_discovery_terms(FEEDS_PATH), config, os.environ)
        return 0

    logging.getLogger(__name__).error(
        "Unsupported RUN_MODE=%r (expected 'collect', 'digest', or 'discover')", config.run_mode
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
