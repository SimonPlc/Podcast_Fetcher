from __future__ import annotations

import logging
import os
import sys

from podcast_fetcher.collect import run_collect
from podcast_fetcher.config import load_config
from podcast_fetcher.digest import maybe_send_missed_digest, run_digest_if_due
from podcast_fetcher.discover import run_discover
from podcast_fetcher.feeds import load_discovery_terms, load_feeds

FEEDS_PATH = "feeds.yaml"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(os.environ)

    if config.run_mode == "collect":
        feeds = load_feeds(FEEDS_PATH)
        # Before collecting, not after: a collect run can spend its full
        # 50-minute budget transcribing, and a brief that was already a
        # morning late should not wait behind that.
        #
        # Never let the catch-up take collection down with it, though. It
        # is a recovery path that touches Gmail, and a bad refresh token
        # or a send failure must not stop the pipeline from doing the
        # expensive work it was actually scheduled for. The slot stays
        # unsettled on failure, so the next collect run retries it.
        try:
            maybe_send_missed_digest(config, os.environ, feeds)
        except Exception:
            logging.getLogger(__name__).exception(
                "missed-digest catch-up failed; continuing with collect"
            )
        run_collect(feeds, config)
        return 0

    if config.run_mode == "digest":
        run_digest_if_due(config, os.environ, load_feeds(FEEDS_PATH))
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
