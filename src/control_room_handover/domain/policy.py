"""Bank-owned control-room policy, kept out of the engine as data (practices check B4).

The staffing baselines and the acknowledgement window are the client's numbers, so they live as
configuration rather than as constants buried in the engine. The defaults here are obviously
synthetic placeholders; a follow-up lifts them into a ``policy:`` block in
``config/settings.yaml`` and loads them through ``config.py`` (recorded as a remaining gap). The
shape is deliberately small: one staffing baseline per registered feed.
"""

from __future__ import annotations

from .models import FeedId, StaffingBaseline

#: Synthetic default staffing baselines, one per feed in the registry. Capacity is
#: ``headcount * items_per_analyst``; the scorecard calls out a feed whose queue exceeds it.
DEFAULT_STAFFING: dict[FeedId, StaffingBaseline] = {
    FeedId.RECON_BREAKS: StaffingBaseline(
        feed_id=FeedId.RECON_BREAKS, headcount=4, items_per_analyst=40
    ),
    FeedId.DISPUTES: StaffingBaseline(feed_id=FeedId.DISPUTES, headcount=3, items_per_analyst=35),
}
