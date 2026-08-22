"""Local OpsFeedPort: replay the golden ops-worklist export fixtures (SDK-free, deterministic).

The ``local`` profile's stand-in for the BigQuery export tables: it reads the bundled fictional
export fixtures (``fixtures/ops_worklist/<feed>.jsonl``), one snapshot per line in the published
contract shape, and parses them through the shared row parser so it cannot drift from the managed
adapter. No SDK, no network, reproducible. The registry lists EXACTLY the two feeds that have
fixtures; a request for anything else raises rather than returning a quiet empty series.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...config import Settings
from ...domain.errors import UnknownFeedError
from ...domain.models import FeedId, FeedSnapshot
from .._feed_parser import snapshot_from_export_row

#: Repo-root fixtures directory, resolved from this file so the CWD does not matter. The local
#: profile is a checkout-only dev / demo / test posture, so shipping fixtures beside the code is
#: correct; a wheel deployment runs the managed adapter.
_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "ops_worklist"

#: Which fixture file backs each registered feed. Adding a feed is adding a member and a file.
_FIXTURES: dict[FeedId, str] = {
    FeedId.RECON_BREAKS: "recon_breaks.jsonl",
    FeedId.DISPUTES: "disputes.jsonl",
}


class LocalOpsFeedAdapter:
    """Deterministic ops-feed replay over the seeded fictional export fixtures."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def feeds(self) -> tuple[FeedId, ...]:
        return tuple(sorted(_FIXTURES, key=lambda f: f.value))

    def snapshots(self, feed_id: FeedId, lookback_days: int) -> tuple[FeedSnapshot, ...]:
        name = _FIXTURES.get(feed_id)
        if name is None:
            raise UnknownFeedError(f"no local fixture for feed {feed_id.value!r}")
        path = _FIXTURE_DIR / name
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        snapshots = [snapshot_from_export_row(row) for row in rows]
        snapshots.sort(key=lambda s: s.as_of)
        return tuple(snapshots[-lookback_days:]) if lookback_days else tuple(snapshots)
