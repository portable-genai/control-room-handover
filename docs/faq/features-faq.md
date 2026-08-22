# Features FAQ

For product, operations, and delivery teams: what this agent does, what is deterministic versus
narrated, and where its responsibilities **stop** and a sibling catalog system takes over.
Cross-references: [`README.md`](../../README.md), [`DEMO.md`](../../DEMO.md),
[`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`docs/ops-metrics-contract.md`](../ops-metrics-contract.md).

### What does F5 actually produce?

A cited **control-room scorecard** and a **shift-handover brief**. From the ops-worklist export
snapshots of the queues it is bound to, it computes per feed: queue depth, the four backlog aging
buckets, SLA clock-state counts and the breach rate, throughput, the drain ratio (throughput over
queue depth), a capacity call-out against the configured staffing baseline, and robust-z anomaly
findings. Those roll up into a control-room severity. The brief adds a narrated summary and is
routed to the incoming shift lead for acknowledgement, on a deadline clock that goes `PENDING`,
then `ACKNOWLEDGED` or `BREACHED`.

### What is deterministic versus done by the model?

The consequential work is **deterministic and replayable**, pure stdlib and unit-tested:
`domain/scorecard_engine.py` computes every figure, `domain/anomaly.py` runs the robust-z spike and
drop detection, `domain/acknowledgement.py` is a pure function of the routed time and the sign-off
time, and `domain/handover_service.py` stitches them together. The model **only narrates**. It
never sets a number: its response is schema-validated and every digit in it must appear in the
engine evidence, or the narration is discarded and a deterministic summary used instead. See
[`docs/model-card.md`](../model-card.md) for the full boundary.

### Where do the numbers come from?

From the versioned **ops-worklist export** contract, one snapshot row per feed per `as_of`. The
feed port (`ports/ops_feeds.py`) returns those rows RAW and cited and computes nothing, so every
derived figure has exactly one home. The two feeds bound in this wave are `recon_breaks` (F1,
`recon-breaks-engine`) and `disputes` (F2, `disputes-chargebacks-manager`). Adding a feed
is one more `FeedId` member plus its fixture and staffing baseline, never new engine code. The
contract and the recorded assumption about its bounded coverage are in
[`docs/ops-metrics-contract.md`](../ops-metrics-contract.md).

### Is anything auto-approved? Does the handover complete itself?

No. `requires_human_review` is unconditionally true on a handover, and the brief is routed to the
**Hrz7** Human-Review and Maker-Checker Console through the shared `review-kit` client
(dependency rule R8) in the same call that produced it, with the payload redacted before the wire
and the verified principal threaded as maker. A handover is not done when it is written; it is done
when the incoming shift lead signs off, and the acknowledgement clock records a breach if the
window elapses without one.

### How many surfaces are there, and can they drift?

Five, and they cannot drift, because they share the domain service rather than reimplementing it:
the FastAPI app (`api/`), the argparse CLI (`cli/`), the agent tools (`agent/`, advertised on the
A2A card at `/.well-known/agent-card.json`), the embeddable micro-frontend (`ui/`) and the eval
harness. Each routes an escalated result to human review in the same call, so rule R8 does not hold
on four surfaces out of five. `tests/unit/test_review_routing.py` asserts the routing on the API,
CLI and agent paths.

### Which capabilities does this repo own versus integrate from the catalog?

It **owns** the control-room scorecard, the anomaly detection, the handover brief and the
acknowledgement clock. It **integrates** the cross-cutting concerns below rather than rebuilding
them. The Status column is what is true today, not an aspiration; the same rows are in
[`COMPLIANCE.md`](../../COMPLIANCE.md).

| Concern | Owned by (catalog id / repo) | F5's role today |
|---|---|---|
| Human review / maker-checker console | **Hrz7** `human-review-console` | wired: every handover routes for acknowledgement (R8), in all three profiles |
| AI-quality / eval / model-risk promotion gate | **Hrz4** `model-quality-gate` | half wired: `--mode gate` is the client and refuses off the managed profile; the bundle is not yet registered |
| Agent registry, versioning, entitlements | **Hrz3** `agent-registry` | half wired: the A2A card is served; registration is outstanding |
| Observability, tracing, immutable WORM audit | **Hrz5** `agent-observability` | half wired: the audit half is local and tamper-evident; the shared sink is outstanding |
| Runtime guardrail: prompt-injection defence, output screening | **Hrz1** `agent-guardrail-gateway` | **not wired.** No `GuardrailPort` exists. Bind it before untrusted text reaches the model |
| Governed RAG / ACL-aware knowledge base | **Hrz2** `enterprise-knowledge-base` | not used: this vertical retrieves nothing, so P-05 and R3 do not apply yet |
| Reconciliation matching and break resolution | **F1** `recon-breaks-engine` | consumed as a worklist snapshot; F5 owns no matching logic |
| Dispute and chargeback lifecycle | **F2** `disputes-chargebacks-manager` | consumed as a worklist snapshot; F5 owns no dispute logic |

So the guardrail, the audit sink, the eval platform, the review console and the upstream queues are
*dependencies*, not features of this repo.

### Can this be used for a different set of queues?

Yes, that is the point of the design. The feed registry is data plus a fixture, and the scorecard
engine reads a snapshot shape rather than any queue's semantics. To point it at your own operations
you change the `FeedId` members, the staffing baselines, the fixtures and the golden eval cases, not
the engine. See [`docs/ADOPTING.md`](../ADOPTING.md) and [adoption-faq.md](adoption-faq.md).

### How do I see it working?

`make demo` runs the presenter-paced walkthrough against the REAL services over the `local`
profile; `make demo-selftest` is the same arc headless and unattended, asserting every step;
`make demo-static` writes the audit-first HTML panels for screenshots. Everything runs offline on
synthetic, obviously fictional data with no cloud and no API key. `make portability` runs the
executable portability claim. See [`DEMO.md`](../../DEMO.md) and
[`scripts/README.md`](../../scripts/README.md).
