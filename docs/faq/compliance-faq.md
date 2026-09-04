# Compliance FAQ

For compliance, operational-risk, and model-risk teams assessing the repo's regulatory posture.
Cross-references: [`COMPLIANCE.md`](../../COMPLIANCE.md) (the full P-01 to P-13 and R1 to R8
mapping with an evidence file per row, plus the adopter-owned crosswalk),
[`SPEC.md`](../../SPEC.md), [`docs/model-card.md`](../model-card.md),
[`docs/practices-audit.md`](../practices-audit.md).

### Is this making operational decisions autonomously?

No. It is a **decision-support** service. Every handover sets `requires_human_review` and is routed
to the `human-review-console` through the shared `review-kit` client
(dependency rule R8) in the same call that produced it, not left in a flag nobody reads. A handover
is complete only when the incoming shift lead acknowledges it, and
`domain/acknowledgement.py` records a `BREACHED` state if the window elapses without a sign-off.
Nothing is provisioned, closed or reassigned by this service.

### How is personal data handled?

The request path is aggregate queue metrics, not customer records, but operational free text can
carry an identifier, so redaction is applied at every boundary rather than once.
`domain/pii.py` selects and ORDERS the jurisdiction rows from the shared `pii-kit`, and
`domain/handover_service.py` redacts before the model sees the evidence, before the audit write and
before the review payload leaves the process, the last of those against the rows for every
jurisdiction because the review console is a shared sink. The eval scores `pii_safety >= 0.99` two
ways (a pack scan plus an independent planted-literal oracle) and
`tests/unit/test_not_falsely_green.py` proves the metric can go red.

What is **not** in place is runtime guardrail screening: no `GuardrailPort` is bound, so nothing
performs prompt-injection defence or output filtering. That is the open **R1** row, and the `agent-guardrail-gateway` is where it belongs when a fork wires it.

### How is the work auditable and reproducible?

Every handover writes an already-redacted, append-only `AuditEvent` with the decision, the severity
and the citation set, and every figure carries a `Citation` back to the feed row it was computed
from. The consequential math is deterministic, so an auditor can recompute any queue depth, breach
rate, drain ratio or capacity call-out from the same snapshots without the model. The audit actor
is the server-verified principal, never a value from the request body.

The in-repo store is hash-chained AND externally anchored, because a hash chain alone cannot detect
a truncated tail: `CONTROLROOM_AUDIT_ANCHOR` writes the chain head to a different volume, and
`tests/unit/test_audit_anchor.py` proves the detection along with the control case that goes
undetected without it. The enterprise WORM sink is `agent-observability`; the local chain is the offline
stand-in, and its limits are stated rather than glossed (see
[security-faq.md](security-faq.md)).

### Is data residency enforced, or only documented?

Enforced at deploy time, with the enforcement in `infra/terraform/` rather than in prose. The region
is chosen once and shared by the runtime (`region` in `config/settings.yaml`, reported on
`/healthz` and on the agent card) and the deploy (`var.region`), and it is validated against
`var.allowed_regions` at plan time so an unvetted region fails `terraform plan`. On top of that:
`org_policy.tf` applies the `gcp.resourceLocations` Org Policy allowlist restricted to the selected
region's location group, so an out-of-jurisdiction resource cannot be created rather than merely
being avoided by convention; `kms.tf` creates a REGIONAL CMEK key ring and key with 90-day
rotation, bound per resource with no project-wide grant; `vpc_sc.tf` stands up a VPC-SC perimeter
around the sovereignty-critical APIs, dry-run first (`var.vpc_sc_enforce = false`) so violations
surface on the alert before enforcement; and `logging_worm.tf` writes the audit stream to a
retention-locked bucket.

Three honest qualifications. The Org Policy and perimeter layers are gated on
`var.enable_org_policies` and `var.enable_vpc_sc` so a project-scoped evaluation deploy is possible
without org-level roles, and that posture is explicitly NOT compliant for production. The offline
gate cannot prove a Terraform apply, so the residency row is evidenced by configuration rather than
by a runtime assertion. And `infra/terraform/production_edge.tftest.hcl` does carry the plan tests
that would catch a regression (`residency_defaults_are_in_country`,
`reject_region_outside_the_residency_allowlist`, `perimeter_starts_in_dry_run`), but no Makefile
target and no workflow runs `terraform test` today, so those tests are written and unexecuted. That
is why the P-03 row is `Partial` rather than `Covered`: the enforcement ships, the standing guard on
it does not.

### What is the model-risk story?

The model narrates and nothing else, which is the primary control: the scorecard is byte-identical
with the generation adapter stubbed, so a model change cannot move a figure. On top of that the
narration is schema-validated and grounding-checked (every digit in it must appear in the engine
evidence) and DISCARDED for a deterministic summary on any failure.

The offline eval (`eval/run_eval.py --mode smoke`) scores `scorecard_accuracy = 1.0`,
`groundedness >= 0.99` and `pii_safety >= 0.99` on every change. `--mode gate` is the promotion
verdict and delegates to the shared `model-quality-gate` authority, refusing to run off the managed profile.
The bundle name `control-room-handover` is declared but **not yet registered** with `model-quality-gate`, which
is the open **P-08** and **R5** row. [`docs/model-card.md`](../model-card.md) records the rest of
the outstanding model controls: a pinned model id, budget and rate limits, a kill switch, injection
screening and a managed-profile eval run.

### Which regulators does this map to?

[`COMPLIANCE.md`](../../COMPLIANCE.md) maps the catalog's own P-01 to P-13 principles and R1 to R8
dependency rules to a control and an evidence file, aligned to MAS TRM, APRA CPS 234 and CPS 230,
HKMA and PDPA-class regimes. The mapping from those rows to a specific regulation, and the judgement
that a control is SUFFICIENT for it, is explicitly **adopter-owned**: it depends on the
institution's risk appetite, regulator, licence conditions and existing control library. No row
should be quoted as regulatory assurance on this repo's behalf. An adopter is expected to add the
crosswalk to their own control ids, the risk acceptance for every row still Partial or TODO at
go-live, a second-line review of the deterministic policy in `domain/`, and the retention schedule
and legal basis for the audit trail.

### Which rows are still open?

The status legend at the top of [`COMPLIANCE.md`](../../COMPLIANCE.md) is deliberate: **Covered**
means a test fails the build if it regresses, **Partial** means the in-repo half exists and the
named deploy-time or platform half does not, and **TODO (repo owner)** means not covered at all. A
rendered repo is honest on day one, not complete on day one. The rows to read before citing this
document as evidence are P-05 (no retrieval yet, so nothing to ground), P-10 (resilience controls
beyond the review outbox), P-11 (no cost or latency controls), and the R1, R2, R4 and R5 platform
integrations. Close them before this file goes to a second or third line of defence.

### Can we run it against real operational data today?

Not without your own legal, security and model-risk sign-off. Every fixture, the golden eval cases
and the demo data are obviously fictional (fictional parties, `.example` domains, RFC 5737 and RFC
3849 literals), and the one national id in the fixtures exists solely so a redaction check has an
independent literal to look for. The adoption checklist in
[`docs/ADOPTING.md`](../ADOPTING.md) lists the steps that must precede any live use: replace the
feed registry and fixtures, own the policy numbers, wire your IdP, rebuild the eval golden set, set
your residency region, and close the model card's outstanding controls before enabling the managed
narration path.
