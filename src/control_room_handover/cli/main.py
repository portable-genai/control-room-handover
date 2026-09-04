"""Minimal stdlib CLI: build a shift handover, or verify the audit chain (argparse, no deps)."""

from __future__ import annotations

import argparse
import sys

from hex_service_kit.logging import configure_logging

from ..config import build_container
from ..domain.handover_service import HandoverService
from ..domain.models import HandoverRequest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="control_room_handover")
    sub = parser.add_subparsers(dest="command", required=True)

    handover_cmd = sub.add_parser("handover", help="Build a shift-handover brief.")
    handover_cmd.add_argument("shift_id")
    handover_cmd.add_argument("as_of", help="ISO date the handover is as of, e.g. 2026-08-07.")
    handover_cmd.add_argument("--lookback-days", type=int, default=14)
    handover_cmd.add_argument("--actor", default="cli-user@bank.example")
    handover_cmd.add_argument(
        "--tenant", default="", help="Tenant partition asserted to human-review-console."
    )

    args = parser.parse_args(argv)
    container = build_container()
    # Idempotent: a process that is both an API app and a CLI configures once.
    configure_logging(container.settings.profile, service="control-room-handover")

    if args.command == "handover":
        service = HandoverService(
            ops_feeds=container.ops_feeds,
            generation=container.generation,
            audit=container.audit,
            tts=container.tts,
            tracer=container.tracer,
        )
        brief = service.build_handover(
            HandoverRequest(
                shift_id=args.shift_id,
                as_of=args.as_of,
                lookback_days=args.lookback_days,
            ),
            actor=args.actor,
        )
        card = brief.scorecard
        print(f"{brief.subject}: {brief.severity.value} ({brief.decision.value})")
        print(f"  total backlog: {card.total_queue_depth}; SLA breached: {card.total_sla_breached}")
        for feed in card.feeds:
            callout = " CAPACITY" if feed.capacity_callout else ""
            print(
                f"    {feed.feed_id.value}: queue {feed.queue_depth}, breached "
                f"{feed.sla_breached}, drain {feed.drain_ratio}{callout}"
            )
        # Rule R8 on the CLI path too: the same brief, the same router, in the same call.
        ref = container.review_router.route(brief, maker=args.actor, tenant=args.tenant)
        print(f"  routed for shift-lead acknowledgement: {ref}")
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
