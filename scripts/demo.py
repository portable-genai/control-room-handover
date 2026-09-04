"""The scripted, offline demo: the REAL services, synthetic data, an audit-first output view.

This is the demo as CODE (practices check F1), not a slide deck and not a recording. Every step
below drives the actual handover service, the actual deterministic scorecard engine, the actual
hash-chained audit store and the actual rule-R8 review router over the ``local`` profile, so a
step that stops being true stops passing rather than stops being mentioned.

Three properties make it worth running in front of somebody:

* **Nothing is faked.** No engine stub, no pre-baked JSON. The scorecard numbers, the audit
  records, the routing references and the tamper verdict are produced by the shipped code.
* **It is bounded.** The demo proves an offline, single-process seam. It does not prove
  cross-host deployment, a live console, or the managed profile; those need a cloud project and
  live in ``tests/integration/``.
* **It is replayable.** Same inputs, same output, every time, because the consequential decision
  is deterministic. That is what makes it safe to run live.

Run it directly to write the audit-view JSON, then render that JSON to static pages::

    make demo-static

or drive it one step at a time with ``demo_server.py`` and ``walkthrough.py`` (``make demo``).

Every party, address and identifier here is obviously fictional: ``.example`` domains, RFC 5737
and RFC 3849 literals, and a synthetic national id that exists only to prove redaction happened.

MAINTAINER NOTE: this file is rendered from a template, so no line may change length with the
package or service name. Every cookiecutter value is bound to a short module constant below and
referenced through it, and every import line is short enough that a long package name cannot push
it past the formatter's limit.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hex_service_kit.audit import HashChainedAuditLog
from hex_service_kit.identity import RequestContext
from hex_service_kit.serialization import to_jsonable

from control_room_handover.config import (
    Settings,
    build_container,
)
from control_room_handover.domain import (
    kernel,
    models,
)
from control_room_handover.domain.handover_service import (
    HandoverService,
)
from control_room_handover.domain.pii import (
    JURISDICTIONS,
)


def loaded_cloud_sdks() -> tuple[str, ...]:
    """Every managed-SDK module currently importable in THIS interpreter, sorted.

    Public because the demo, the walkthrough's checks and the test suite all ask the same
    question and must not each answer it slightly differently.
    """
    return tuple(sorted(name for name in sys.modules if name.split(".")[0] == "google"))


#: Rendered identity, bound once so no other line's length depends on how long a name is.
SERVICE_NAME = "Control Room Handover"
CATALOG_ID = "F5"
REPOSITORY = "control-room-handover"

# --------------------------------------------------------------------------------------- #
# Synthetic data. Fictional shifts, .example domains, a synthetic national id only.
# --------------------------------------------------------------------------------------- #

#: The VERIFIED principal the demo attributes work to. A client never asserts this.
ACTOR = "outgoing-lead@bank.example"
TENANT = "demo-bank"

#: A planted identifier, so the redaction panel has an independent literal to look for rather
#: than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

#: The shift-handover asks the arc builds, one per BUILD beat, over the golden export fixtures.
AS_OF = "2026-08-07"
SCORECARD_SHIFT = "asia-day"
HANDOVER_SHIFT = "asia-night"
REDACTION_SHIFT = "emea-day"


def _pii_brief() -> models.HandoverBrief:
    """A synthetic brief carrying a planted national id in a citation, for the redaction beat.

    Constructed rather than produced by the pipeline: the ops feeds carry no per-person data by
    design, so the redaction proof plants an identifier deliberately and shows the outbound
    review payload masks it before it can reach the shared console.
    """
    citation = kernel.Citation(
        source_id="recon_breaks",
        title="Ops worklist export",
        snippet="break tied to NRIC " + PLANTED_NRIC + " and ops@gamma.example on file",
    )
    scorecard = models.ControlRoomScorecard(
        as_of=AS_OF,
        feeds=(),
        total_queue_depth=0,
        total_sla_breached=0,
        overall_severity=kernel.Severity.HIGH,
        citations=(citation,),
    )
    return models.HandoverBrief(
        subject="Shift handover " + REDACTION_SHIFT + " as of " + AS_OF,
        severity=kernel.Severity.HIGH,
        decision=kernel.Decision.ESCALATED,
        summary="A recon break with personal data attached, pending sign-off.",
        requires_human_review=True,
        scorecard=scorecard,
        citations=(citation,),
    )


# --------------------------------------------------------------------------------------- #
# The presenter arc
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Step:
    """One presenter beat: what it shows, and the sentence the presenter reads aloud."""

    key: str
    label: str
    narration: str


#: The scripted arc, in order. ``walkthrough.py`` asserts the server reaches each key in turn and
#: carries an expectation per key, so a step added here without an expectation there fails the
#: self-test rather than silently extending the demo.
STEPS: tuple[Step, ...] = (
    Step(
        key="opened",
        label="Service bound on the offline profile",
        narration=(
            "The whole stack is bound from one settings file: no cloud project, no credentials, "
            "no SDK. Every port has an offline implementation, which is why this demo and the "
            "gate both run on a plane."
        ),
    ),
    Step(
        key="scorecard",
        label="The control-room scorecard: every number engine-computed and cited",
        narration=(
            "The F1 and F2 ops feeds are read raw and cited. The queue depths, SLA breaches, "
            "drain ratios, capacity call-outs and anomalies are computed by a pure stdlib engine, "
            "never by a model, so an auditor can re-run every figure."
        ),
    ),
    Step(
        key="handover",
        label="The handover brief: narrated over the numbers, routed for sign-off (rule R8)",
        narration=(
            "The model narrates the scorecard and adds no number; an invented figure would be "
            "discarded. A handover is not done until the incoming lead signs off, so it is routed "
            "to the review console in the same call that produced it."
        ),
    ),
    Step(
        key="redaction",
        label="Personal data is masked BEFORE it reaches the shared review console",
        narration=(
            "A break with a national id attached. The identifier is masked before the brief "
            "leaves the process to the shared console, which sees many markets, so it is scrubbed "
            "against every configured jurisdiction, not only this one."
        ),
    ),
    Step(
        key="review_queue",
        label="What the reviewer receives, already redacted on the wire",
        narration=(
            "The outbound review queue. Every routed handover is accounted for, and no personal "
            "data is on the wire. A flag with no routing reference is auto-execution with extra "
            "steps."
        ),
    ),
    Step(
        key="audit",
        label="The audit trail verifies, and exports in an open format",
        narration=(
            "The trail is append-only and hash-chained, with an external head anchor on a "
            "separate volume. It exports to JSON Lines and reloads into a fresh store with every "
            "link intact: the record is yours, not this codebase's."
        ),
    ),
    Step(
        key="tamper",
        label="A rewritten record is DETECTED, not merely discouraged",
        narration=(
            "An attacker with file access drops the append-only triggers and rewrites one record. "
            "The store cannot prevent that. The hash chain names the exact record that broke, "
            "which is the honest guarantee: tamper-EVIDENT, not tamper-proof."
        ),
    ),
    Step(
        key="portability",
        label="The exit path fails fast instead of failing silently",
        narration=(
            "The same calls on the on-premises profile, with no code edited and no domain module "
            "touched. Every unimplemented seam refuses loudly. A placeholder that returned "
            "successfully would convert a handover into an unreviewed one."
        ),
    ),
)

STEP_KEYS: tuple[str, ...] = tuple(step.key for step in STEPS)


# --------------------------------------------------------------------------------------- #
# Panels: the audit-first output view (the result, its evidence, the findings, what is next)
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Row:
    """One labelled fact in a panel. ``tone`` drives the colour, never the meaning."""

    label: str
    value: str
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Panel:
    """One block of the output view: a title, labelled facts, and an interpretation."""

    title: str
    rows: tuple[Row, ...] = ()
    note: str = ""
    tone: str = ""


@dataclass(frozen=True, slots=True)
class StepResult:
    """Everything one step produced, ready to render or to assert against."""

    key: str
    label: str
    narration: str
    panels: tuple[Panel, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)


Produced = tuple[list[Panel], dict[str, Any]]


class DemoRun:
    """A live demo, advanced one step at a time over the real services.

    The run owns a working directory holding the durable audit store and its external anchor.
    They are separate directories on purpose: an anchor that lives beside the store it witnesses
    is rewritten by whatever rewrites the store.
    """

    def __init__(self, workdir: Path | None = None) -> None:
        self._cloud_sdk_before = frozenset(loaded_cloud_sdks())
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        if workdir is None:
            self._tempdir = tempfile.TemporaryDirectory(prefix="demo-run-")
            workdir = Path(self._tempdir.name)
        self.workdir = workdir
        self.audit_path = workdir / "store" / "audit.sqlite3"
        self.anchor_path = workdir / "anchor" / "head.json"
        self.anchor_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(
            profile="local",
            audit_path=str(self.audit_path),
            audit_anchor_path=str(self.anchor_path),
            tenant=TENANT,
        )
        self.container = build_container(self.settings)
        self.service = HandoverService(
            ops_feeds=self.container.ops_feeds,
            generation=self.container.generation,
            audit=self.container.audit,
            tts=self.container.tts,
            tracer=self.container.tracer,
        )
        self.results: list[StepResult] = []
        self.briefs = 0
        self.routed = 0
        self.chain_ok = True
        self._main: models.HandoverBrief | None = None
        self._perform(STEPS[0])

    # -------------------------------------------------------------- control

    @property
    def index(self) -> int:
        """Index of the step most recently performed."""
        return len(self.results) - 1

    @property
    def done(self) -> bool:
        return len(self.results) >= len(STEPS)

    def advance(self) -> StepResult:
        """Perform the next step, or re-return the last one when the arc is finished."""
        if self.done:
            return self.results[-1]
        return self._perform(STEPS[len(self.results)])

    def run_to_end(self) -> None:
        while not self.done:
            self.advance()

    def _perform(self, step: Step) -> StepResult:
        handler: Callable[[], Produced] = getattr(self, "_step_" + step.key)
        panels, facts = handler()
        result = StepResult(
            key=step.key,
            label=step.label,
            narration=step.narration,
            panels=tuple(panels),
            facts=facts,
        )
        self.results.append(result)
        return result

    # -------------------------------------------------------------- steps

    def _step_opened(self) -> Produced:
        bindings = [
            Row(port, self.settings.adapters[port][self.settings.profile].split(":")[-1])
            for port in sorted(self.settings.adapters)
        ]
        profiles = sorted({name for table in self.settings.adapters.values() for name in table})
        sdk = [name for name in loaded_cloud_sdks() if name not in self._cloud_sdk_before]
        deployment = Panel(
            title="Deployment",
            rows=(
                Row("Service", SERVICE_NAME),
                Row("Profile", self.settings.profile, "ok"),
                Row("Profiles bound for every port", ", ".join(profiles)),
                Row("Residency region", self.settings.region),
                Row("Jurisdiction PII packs", ", ".join(JURISDICTIONS)),
            ),
            note=(
                "One environment variable selects the adapter family for every port. Nothing "
                "below was edited to make the service run offline."
            ),
        )
        adapters = Panel(
            title="Bound adapters",
            rows=tuple(bindings),
            note="The binding map lives in config/settings.yaml, not in the code.",
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Cloud SDK modules imported", ", ".join(sdk) or "none", "bad" if sdk else "ok"),
                Row("Credentials required", "none", "ok"),
                Row("Network required", "none", "ok"),
            ),
            note=(
                "The managed adapters import their SDK lazily, so this profile runs with none "
                "installed at all."
            ),
            tone="bad" if sdk else "ok",
        )
        facts = {"profile": self.settings.profile, "sdk_modules": sdk, "profiles": profiles}
        return [deployment, adapters, findings], facts

    def _build(self, shift: str) -> models.HandoverBrief:
        brief = self.service.build_handover(
            models.HandoverRequest(shift_id=shift, as_of=AS_OF), actor=ACTOR
        )
        self.briefs += 1
        return brief

    def _step_scorecard(self) -> Produced:
        brief = self._build(SCORECARD_SHIFT)
        self._main = brief
        card = brief.scorecard
        rows = [
            Row(
                feed.feed_id.value,
                (
                    "queue "
                    + str(feed.queue_depth)
                    + ", breached "
                    + str(feed.sla_breached)
                    + ", drain "
                    + str(feed.drain_ratio)
                ),
                "bad" if feed.capacity_callout else "ok",
            )
            for feed in card.feeds
        ]
        scorecard = Panel(
            title="Control-room scorecard: " + card.as_of,
            rows=tuple(rows),
            note=(
                "Every figure is computed by the deterministic engine over the raw cited feed "
                "rows. A model narrates these; it never produces them."
            ),
        )
        totals = Panel(
            title="Totals",
            rows=(
                Row("Total backlog", str(card.total_queue_depth)),
                Row("Total SLA breached", str(card.total_sla_breached), "bad"),
                Row("Overall severity", card.overall_severity.value, "bad"),
                Row(
                    "Feeds bound",
                    str(len(card.feeds)),
                    "ok" if len(card.feeds) >= 2 else "bad",
                ),
            ),
            note="F1 recon breaks and F2 disputes are the two feeds this wave binds.",
        )
        facts = {
            "total_queue": card.total_queue_depth,
            "total_breached": card.total_sla_breached,
            "overall_severity": card.overall_severity.value,
            "feeds": len(card.feeds),
        }
        return [scorecard, totals], facts

    def _step_handover(self) -> Produced:
        brief = self._build(HANDOVER_SHIFT)
        review_ref = self.container.review_router.route(brief, maker=ACTOR, tenant=TENANT)
        self.routed += 1
        decision = Panel(
            title="Handover brief: " + brief.subject,
            rows=(
                Row("Overall severity", brief.severity.value, "bad"),
                Row("Requires sign-off", str(brief.requires_human_review)),
                Row(
                    "Narration grounded",
                    str(brief.narration_grounded),
                    "ok" if brief.narration_grounded else "bad",
                ),
                Row("Routed for acknowledgement", review_ref, "ok" if review_ref else "bad"),
                Row("Attributed to", ACTOR),
            ),
            note=(
                "Setting the flag is not the handover; routing is. The reference records where "
                "it went, so a buffered handover is never mistaken for an acknowledged one."
            ),
            tone="ok" if review_ref and brief.narration_grounded else "bad",
        )
        evidence = Panel(
            title="Evidence",
            rows=tuple(
                Row(citation.title, citation.snippet or citation.source_id)
                for citation in brief.citations
            )
            or (Row("citations", "NONE", "bad"),),
            note="Every claim carries its source feed. An uncited number is a hallucination risk.",
        )
        facts = {
            "requires_human_review": brief.requires_human_review,
            "review_ref": review_ref,
            "narration_grounded": brief.narration_grounded,
        }
        return [decision, evidence], facts

    def _step_redaction(self) -> Produced:
        # A third real handover keeps the audit trail growing (the tamper step needs an interior
        # record), then a PII-bearing brief is routed to prove the wire is scrubbed.
        self._build(REDACTION_SHIFT)
        brief = _pii_brief()
        review_ref = self.container.review_router.route(brief, maker=ACTOR, tenant=TENANT)
        self.routed += 1
        pending = list(self.container.review_router.outbox.pending())
        payload = to_jsonable(pending[-1])
        leaked = PLANTED_NRIC in json.dumps(payload, sort_keys=True)
        redaction = Panel(
            title="Redact before the wire",
            rows=(
                Row("Identifier in the source citation", PLANTED_NRIC, "warn"),
                Row(
                    "Identifier in the outbound payload",
                    "PRESENT" if leaked else "absent",
                    "bad" if leaked else "ok",
                ),
                Row("Routed for acknowledgement", review_ref, "ok" if review_ref else "bad"),
            ),
            note=(
                "The review console is a shared sink across markets, so the payload is scrubbed "
                "against every configured jurisdiction before it leaves the process."
            ),
            tone="bad" if leaked else "ok",
        )
        facts = {"planted_identifier_leaked": leaked, "review_ref": review_ref}
        return [redaction], facts

    def _step_review_queue(self) -> Produced:
        pending = list(self.container.review_router.outbox.pending())
        rows: list[Row] = []
        leaked = False
        for item in pending:
            payload = to_jsonable(item)
            leaked = leaked or PLANTED_NRIC in json.dumps(payload, sort_keys=True)
            rows.append(Row(str(getattr(item, "source_key", "review")), _summarise(payload)))
        queue = Panel(
            title="Outbound review queue",
            rows=tuple(rows) or (Row("queue", "empty", "bad"),),
            note=(
                "Queued, not submitted. The reference the caller received says exactly that, so "
                "a buffered handover is never mistaken for an acknowledged one."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Handovers routed", str(self.routed)),
                Row(
                    "In the queue",
                    str(len(pending)),
                    "ok" if len(pending) == self.routed else "bad",
                ),
                Row(
                    "Personal data on the wire",
                    "LEAKED" if leaked else "none",
                    "bad" if leaked else "ok",
                ),
            ),
            note="Every routed handover is accounted for, and nothing personal is on the wire.",
            tone="bad" if leaked or len(pending) != self.routed else "ok",
        )
        return [queue, findings], {"pending": len(pending), "wire_leak": leaked}

    def _step_audit(self) -> Produced:
        log = self.container.audit.log
        report = self.container.audit.verify()
        self.chain_ok = report.ok
        export = self.workdir / "export" / "audit.jsonl"
        export.parent.mkdir(parents=True, exist_ok=True)
        written = log.export_jsonl(export)
        restored = HashChainedAuditLog(":memory:")
        reloaded = restored.import_jsonl(export)
        round_trip = restored.verify_chain()
        anchored = bool(self.settings.audit_anchor_path) and self.anchor_path.exists()
        trail = Panel(
            title="Audit trail",
            rows=(
                Row("Records", str(report.entries)),
                Row("Hash-chained", str(report.chained)),
                Row(
                    "Unverifiable (unchained)",
                    str(report.legacy),
                    "ok" if report.legacy == 0 else "bad",
                ),
                Row("Verdict", report.detail, "ok" if report.ok else "bad"),
                Row(
                    "External head anchor",
                    "configured" if anchored else "absent",
                    "ok" if anchored else "warn",
                ),
            ),
            note=(
                "The chain alone cannot detect a truncated tail: dropping the newest rows leaves "
                "a shorter chain that verifies perfectly. The anchor, kept on a different volume, "
                "is what closes that gap."
            ),
            tone="ok" if report.ok else "bad",
        )
        portable = Panel(
            title="Open-format round trip",
            rows=(
                Row("Exported records", str(written)),
                Row("Reloaded into a fresh store", str(reloaded)),
                Row("Chain after reload", round_trip.detail, "ok" if round_trip.ok else "bad"),
            ),
            note=(
                "JSON Lines with the hashes included, so a consumer can re-verify the trail "
                "without this codebase. That is what makes the record portable."
            ),
            tone="ok" if round_trip.ok else "bad",
        )
        facts = {
            "chain_ok": report.ok,
            "entries": report.entries,
            "exported": written,
            "round_trip_ok": round_trip.ok,
            "anchored": anchored,
        }
        return [trail, portable], facts

    def _step_tamper(self) -> Produced:
        before = self.container.audit.verify()
        target = _rewrite_a_record(self.audit_path)
        after = self.container.audit.verify()
        self.chain_ok = after.ok
        detected = (not after.ok) and after.first_bad_seq == target
        attack = Panel(
            title="The tamper",
            rows=(
                Row("Append-only triggers", "dropped by the attacker", "warn"),
                Row("Record rewritten in place", "seq " + str(target), "warn"),
                Row("Verdict before the rewrite", before.detail, "ok"),
            ),
            note=(
                "File access beats a database trigger. A store that claims otherwise is "
                "describing a policy, not a control."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Chain intact", "YES" if after.ok else "no", "bad" if after.ok else "ok"),
                Row("First broken record", str(after.first_bad_seq), "ok"),
                Row("Detail", after.detail),
                Row(
                    "Named the exact rewritten record",
                    "yes" if detected else "no",
                    "ok" if detected else "bad",
                ),
            ),
            note=(
                "Tamper-EVIDENT, not tamper-proof. The guarantee is that a rewrite cannot pass "
                "unnoticed, and that the report names which record broke."
            ),
            tone="ok" if detected else "bad",
        )
        facts = {"tampered_seq": target, "detected": detected, "chain_ok": after.ok}
        return [attack, findings], facts

    def _step_portability(self) -> Produced:
        onprem = build_container(Settings(profile="onprem", tenant=TENANT))
        rows: list[Row] = []
        refused: list[str] = []
        absent: list[str] = []
        for port, call in EXIT_CALLS.items():
            expected_absent = port in EXIT_ABSENT
            try:
                call(onprem)
            except NotImplementedError as exc:
                if expected_absent:
                    rows.append(Row(port, "REFUSED, but is meant to be absent", "bad"))
                else:
                    refused.append(port)
                    rows.append(Row(port, "refused: " + str(exc).split(":")[0], "ok"))
            else:
                if expected_absent:
                    absent.append(port)
                    rows.append(Row(port, "absent, by design (a diagnostic, not a control)", "ok"))
                else:
                    rows.append(Row(port, "SUCCEEDED SILENTLY", "bad"))
        exit_panel = Panel(
            title="Exit profile (onprem)",
            rows=tuple(rows),
            note=(
                "Selected by one environment variable. No domain module was edited and no import "
                "changed."
            ),
            tone="ok" if len(refused) + len(absent) == len(EXIT_CALLS) else "bad",
        )
        bounds = Panel(
            title="What this does and does not prove",
            rows=(
                Row("Proved", "every port is swappable and every seam is named"),
                Row("Proved", "an unimplemented seam refuses instead of dropping work"),
                Row("NOT proved", "a running on-premises deployment exists"),
                Row("NOT proved", "model, infrastructure or whole-system portability"),
            ),
            note=(
                "Bounded claims are the point. Run scripts/portability_demo.py for the full seam "
                "tour, with a pass or fail per named check."
            ),
        )
        return [exit_panel, bounds], {
            "refused": sorted(refused),
            "absent": sorted(absent),
        }

    # -------------------------------------------------------------- state

    def state(self) -> dict[str, Any]:
        """The whole run as JSON-safe data: what the UI renders and the walkthrough asserts."""
        current = self.results[-1]
        return {
            "service": SERVICE_NAME,
            "repository": REPOSITORY,
            "profile": self.settings.profile,
            "region": self.settings.region,
            "step": current.key,
            "step_index": self.index,
            "step_count": len(STEPS),
            "label": current.label,
            "next": "" if self.done else STEPS[len(self.results)].label,
            "done": self.done,
            "totals": {
                "briefs": self.briefs,
                "routed": self.routed,
                "chain_ok": self.chain_ok,
            },
            "steps": [_step_to_dict(result) for result in self.results],
        }


def _step_to_dict(result: StepResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "label": result.label,
        "narration": result.narration,
        "facts": result.facts,
        "panels": [
            {
                "title": panel.title,
                "note": panel.note,
                "tone": panel.tone,
                "rows": [
                    {"label": row.label, "value": row.value, "tone": row.tone} for row in panel.rows
                ],
            }
            for panel in result.panels
        ],
    }


def _summarise(payload: Any) -> str:
    """One readable line for a queued review, without dumping the whole payload."""
    if isinstance(payload, dict):
        parts = [
            str(payload[key])
            for key in ("title", "severity", "maker", "tenant")
            if payload.get(key)
        ]
        if parts:
            return " / ".join(parts)
    return json.dumps(payload, sort_keys=True)[:120]


def _rewrite_a_record(store: Path) -> int:
    """Drop the append-only triggers and rewrite one INTERIOR record, as an attacker would.

    Returns the ``seq`` that was rewritten. An interior row is chosen deliberately: rewriting the
    newest row is the easy case, and the chain has to catch a rewrite in the middle of the trail
    too.
    """
    conn = sqlite3.connect(store)
    try:
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
        rows = conn.execute("SELECT seq, event_json FROM audit_log ORDER BY seq ASC").fetchall()
        if len(rows) < 3:
            raise RuntimeError("the tamper step needs an interior record to rewrite")
        middle = rows[len(rows) // 2]
        payload = json.loads(middle[1])
        payload["decision"] = "allowed"
        payload["severity"] = "low"
        conn.execute(
            "UPDATE audit_log SET event_json = ? WHERE seq = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), int(middle[0])),
        )
        conn.commit()
        return int(middle[0])
    finally:
        conn.close()


def _exit_audit(container: Any) -> Any:
    return container.audit.record(
        kernel.AuditEvent(
            action="shift_handover",
            actor=ACTOR,
            decision=kernel.Decision.ESCALATED,
            severity=kernel.Severity.HIGH,
            redacted_summary="Shift handover asia-day as of 2026-08-07",
        )
    )


def _exit_review(container: Any) -> Any:
    return container.review_router.route(_pii_brief(), maker=ACTOR, tenant=TENANT)


def _exit_identity(container: Any) -> Any:
    return container.identity.resolve(RequestContext(headers={"x-dev-persona": "approver"}))


def _exit_feeds(container: Any) -> Any:
    return container.ops_feeds.feeds()


def _exit_generation(container: Any) -> Any:
    return container.generation.generate(
        models.LlmRequest(messages=(models.LlmMessage(role="user", content="x"),))
    )


def _exit_tts(container: Any) -> Any:
    from control_room_handover.ports.tts import SpeechSynthesisRequest

    return container.tts.synthesize(
        SpeechSynthesisRequest(request_id="x", text="handover", locale="en-SG")
    )


def _exit_tracer(container: Any) -> Any:
    with container.tracer.span("exit.tour", action="portability"):
        return None


def _exit_evaluation(container: Any) -> Any:
    return container.evaluation.gate("eval/datasets/golden_cases.jsonl")


#: The calls the exit profile must REFUSE, one per port with an exit placeholder. Add a port, add
#: a row: a seam nobody calls is a seam nobody knows is unimplemented.
EXIT_CALLS: dict[str, Callable[[Any], Any]] = {
    "audit": _exit_audit,
    "identity": _exit_identity,
    "review_router": _exit_review,
    "tracer": _exit_tracer,
    "evaluation": _exit_evaluation,
    "ops_feeds": _exit_feeds,
    "generation": _exit_generation,
    "tts": _exit_tts,
}


#: Diagnostic seams that complete as an honest no-op under the exit profile.
EXIT_ABSENT: frozenset[str] = frozenset({"tracer"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scripted offline demo end to end.")
    parser.add_argument(
        "output",
        nargs="?",
        default="demo.json",
        help="where to write the audit-view JSON (default: demo.json)",
    )
    parser.add_argument("--quiet", action="store_true", help="write the JSON and print nothing")
    args = parser.parse_args(argv)

    run = DemoRun()
    run.run_to_end()
    state = run.state()
    Path(args.output).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        for step in state["steps"]:
            print("[" + step["key"] + "] " + step["label"])
        totals = state["totals"]
        print("briefs=" + str(totals["briefs"]) + " routed=" + str(totals["routed"]))
        print("wrote " + args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
