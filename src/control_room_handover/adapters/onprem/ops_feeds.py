"""On-prem OpsFeedPort: fail-fast portability placeholder (the sovereign-exit proof, P-12).

The client reads the ops-worklist exports from its own warehouse, so this binding refuses at call
time rather than returning an empty series. Refusing is the correct failure: a reader that
silently returned nothing would produce a scorecard grounded in an empty backlog and a handover
that understated every queue.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import FeedId, FeedSnapshot


class OnPremOpsFeedAdapter:
    """Satisfies OpsFeedPort but refuses: bind the client's own warehouse export reader."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def feeds(self) -> tuple[FeedId, ...]:
        raise NotImplementedError(
            "on-prem ops-feed reading is a portability placeholder: bind the client's own "
            "warehouse export reader (see docs/onprem-migration.md)."
        )

    def snapshots(self, feed_id: FeedId, lookback_days: int) -> tuple[FeedSnapshot, ...]:
        raise NotImplementedError(
            "on-prem ops-feed reading is a portability placeholder: bind the client's own "
            "warehouse export reader (see docs/onprem-migration.md)."
        )
