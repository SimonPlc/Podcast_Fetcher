from __future__ import annotations

import logging
import os
import sys

from podcast_fetcher.collect import run_collect
from podcast_fetcher.config import load_config
from podcast_fetcher.feeds import load_feeds

FEEDS_PATH = "feeds.yaml"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(os.environ)
    feeds = load_feeds(FEEDS_PATH)

    if config.run_mode == "collect":
        run_collect(feeds, config)
        return 0

    logging.getLogger(__name__).error("Unsupported RUN_MODE=%r (only 'collect' is implemented so far)", config.run_mode)
    return 1


if __name__ == "__main__":
    sys.exit(main())
