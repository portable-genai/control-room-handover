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

    def snapshots(
        self, feed_id: FeedId, lookback_days: int, *, as_of: str
    ) -> tuple[FeedSnapshot, ...]:
        """Return the cited snapshot series for ``feed_id`` over the window, oldest first.

        The window ENDS at ``as_of`` and reaches ``lookback_days`` back from it. That date is
        the handover's own, carried on the request, and it is a required argument here because
        it used to be dropped at this boundary: the service passed only the lookback, and the
        managed adapter filled the gap by reading a wall clock. A handover written for any date
        but today then read the wrong window while its heading reported the requested one, and
        ``domain/acknowledgement.py`` says in as many words that the as-of is an input and never
        a clock read. The offline adapter could not disagree, because it took the last N ROWS of
        a file and never looked at a date at all.

        Never computes: each row is the source feed's own published export. An unknown feed
        raises rather than returning an empty series that would read as a quiet zero.
        """
        ...
