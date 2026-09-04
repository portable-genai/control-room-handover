"""OpsFeedPort: the boundary that reads the F1 / F2 ops-worklist export snapshots.

Modelled on performance-marketing-optimisation's ``MetricsPort``: it returns RAW, cited rows only
and computes nothing. The scorecard engine owns every ratio and verdict. The registry lists EXACTLY
the two feeds that exist in this wave (F1 recon breaks, F2 disputes); an unknown feed is refused and
a snapshot missing a required field fails closed in the model's own validation, never silently
defaulted.

The primary managed adapter reads the F1 and F2 export tables in BigQuery; the offline adapter
replays golden export fixtures; the on-premises adapter is a fail-fast placeholder. The domain
depends on none of them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import FeedId, FeedSnapshot


@runtime_checkable
class OpsFeedPort(Protocol):
    def feeds(self) -> tuple[FeedId, ...]:
        """The feeds this deployment is wired to read. Exactly the registered set, never more."""
        ...

    def snapshots(self, feed_id: FeedId, lookback_days: int) -> tuple[FeedSnapshot, ...]:
        """Return the cited snapshot series for ``feed_id`` over the window, oldest first.

        Never computes: each row is the source feed's own published export. An unknown feed
        raises rather than returning an empty series that would read as a quiet zero.
        """
        ...
