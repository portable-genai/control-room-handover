# Adopting this repo as your base

This repository (F5, the Control Room Handover) is a **common base** that a bank or other
regulated institution forks to build its own **operations control-room scorecard and shift
handover**: a service that reads versioned ops-worklist export snapshots from upstream queues,
computes an SLA and capacity scorecard with a pure deterministic engine, drafts a handover brief
the model only narrates, and routes that brief to the incoming shift lead for acknowledgement. It
ships a reusable hexagonal core (a stdlib domain, typed ports, three swappable adapter profiles, a
green offline gate) plus a fully worked control-room vertical you can keep, retune, or replace with
your own operating model.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the port table and the layout),
> [`CONTRIBUTING.md`](../CONTRIBUTING.md) (the five-place port registration and the adapter touch
> list), [`docs/ops-metrics-contract.md`](ops-metrics-contract.md) (the F1 to F5 feed seam),
> [`docs/model-card.md`](model-card.md) (the model boundary), the [`faq/`](faq/) directory.

---

## 1. What you keep vs what you rewrite

The domain is split so the boundary is physical rather than a convention.
`domain/kernel.py` holds the vertical-neutral machinery and imports nothing from the vertical;
`domain/models.py` holds this vertical's artifacts and imports the kernel, never the reverse.

| Layer | Where | For a new operating model |
|---|---|---|
| **Kernel** (vertical-neutral) | `domain/kernel.py` (`Citation`, `AuditEvent`, `Severity`, `Decision`, `utcnow`, the `LenientStrEnum` vocabularies), `domain/errors.py`, every Protocol in `ports/`, the `Container` wiring in `config.py` | keep untouched |
| **Policy** (your numbers) | the staffing baselines in `domain/policy.py`, the anomaly thresholds in `domain/anomaly.py`, the acknowledgement rule in `domain/acknowledgement.py`, the eval thresholds in `eval/run_eval.py` | change deliberately (see section 4) |
| **Vertical** (the artifacts) | `FeedId`, `FeedSnapshot`, `FeedScorecard`, `ControlRoomScorecard`, `HandoverBrief`, `HandoverRequest`, `StaffingBaseline` in `domain/models.py`, the `ScorecardEngine` in `domain/scorecard_engine.py`, the feed fixtures, the golden eval cases, the UI views | rewrite or reseed for your queues |

If your product is another *operational oversight* service (a control room over a different set of
queues, a service-level dashboard, a shift or duty handover), most of the hexagon, the three
profiles, the deterministic-then-narrate pattern, the eval gate and the `human-review-console` acknowledgement
routing transfer directly. You replace the feed registry and the scorecard formulas, and you retune
the policy numbers.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly.

- **Upstream-owned** (take our changes): `domain/kernel.py`, `ports/`, `tests/contract/`, the eval
  harness mechanics (`eval/run_eval.py` scaffolding), the CI workflows, the hexagon wiring
  (`config.py` `Container`), and the security posture in `api/` (the exposure guard, the identity
  dependency, the security headers).
- **Adopter-owned** (yours; expect to edit): the *values* in `config/settings.yaml`, the staffing
  baselines and anomaly thresholds, the feed registry and every fixture, `adapters/onprem/*`, the
  `ui/` theming, the golden eval dataset, and the crosswalk appendix in
  [`COMPLIANCE.md`](../COMPLIANCE.md).

Track upstream by git tag and rebase your adopter-owned changes onto each release rather than
merging `main` continuously, so conflicts stay in the files you were told to expect.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the python package (`control_room_handover`), the console-script
name, the `CONTROLROOM` env-var prefix, the Terraform `name_prefix` stem (`f5-svc`) and the
distribution / git id (`control-room-handover`) in one simultaneous pass. Preview first, then
apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_handover --cli acme-handover \
    --env-prefix ACME --resource acme-svc --dry-run

# Apply, sweeping Markdown prose too:
python scripts/rename_fork.py --package acme_handover --cli acme-handover \
    --env-prefix ACME --resource acme-svc --include-docs --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
```

`--dist` defaults to the package name with underscores turned into hyphens; pass it explicitly if
your git id follows a different convention. Note that in this template the console-script name IS
the package name, so the script matches the command name only where a command name can appear (the
`[project.scripts]` key and a documented shell invocation) and leaves module paths to the package
rule. The script deliberately does NOT make the decisions below.

## 4. The human decisions (the script cannot make these)

1. **Region and residency.** The region is one value shared by the runtime and Terraform:
   `region` in `config/settings.yaml` (`GCP_REGION`, default `asia-southeast1`) and
   `var.region` plus `var.allowed_regions` in `infra/terraform/`. Set both to your in-country
   region, and extend the allowlist only after confirming the whole managed stack is available
   there. See [`docs/runbook.md`](runbook.md).
2. **Identity and IdP.** This repo owns no login flow. The `gcp` profile verifies the IAP-injected
   assertion against `CONTROLROOM_IAP_AUDIENCE` (unset or emptied refuses every caller rather than
   verifying without an audience), `local` uses seeded dev personas that authenticate nobody, and
   `onprem` is a client-IdP placeholder. Configure your issuer on the deployed service, not in this
   code.
3. **The feed registry and its contract.** F5 is bound to the two feeds this wave documents
   (`recon_breaks`, `disputes`) and holds a CONSUMED copy of the ops-worklist export schema. When
   the upstream publisher lands, replace the consumed copy with a pin to its published schema and
   keep `tests/unit/test_feed_contract.py` pointed at the pinned file. Adding a feed is one more
   `FeedId` member plus its fixture and staffing baseline, never new engine code. See
   [`docs/ops-metrics-contract.md`](ops-metrics-contract.md).
4. **Policy numbers.** Own the numbers your operations and risk functions set: the staffing
   baselines in `domain/policy.py` (headcount times items per analyst is the capacity call-out),
   the robust-z anomaly thresholds in `domain/anomaly.py`, the acknowledgement window in
   `domain/acknowledgement.py`, and the eval thresholds in `eval/run_eval.py`. These are module
   level today rather than a `policy:` section in `config/settings.yaml`, which is the open B4 item
   in [`docs/practices-audit.md`](practices-audit.md). Change them deliberately and add a test that
   pins your values. The defaults are obviously synthetic placeholders, not your policy.
5. **Reference data is fictional.** Every feed fixture, the golden eval cases and the demo data use
   obviously fictional parties and `.example` domains, and the one national id in the fixtures
   exists only so a redaction check has an independent literal to look for. Replace them with your
   own synthetic data. **Do not run against real operational data without your own security and
   model-risk sign-off.**
6. **Eval golden set.** Rebuild `eval/datasets/golden_cases.jsonl` for your queues: a fork inherits
   a green gate that measures the WRONG scorecard until you do. The gate structure and the strict
   `scorecard_accuracy = 1.0` and `pii_safety >= 0.99` metrics are generic; the golden cases are
   yours. The `model-quality-gate` bundle name is registered as `control-room-handover`; rename it with your
   fork and register it with `model-quality-gate` before `--mode gate` has an authority to ask.
7. **The model.** Read [`docs/model-card.md`](model-card.md) before you enable the managed
   narration path: the model id, the budget and rate controls, the kill switch and the
   prompt-injection screen are all listed there as outstanding, and the deterministic scorecard
   stands on its own without any of them.
8. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001,
   `HEALTHCHECK`), `infra/terraform/` (the resource-location Org Policy, regional CMEK, the
   dry-run-first VPC-SC perimeter, the locked WORM log bucket) and the loopback-by-default binding
   before you expose anything.
9. **The UI.** If your fork has no user-facing surface, run `make drop-ui` rather than leaving
   `ui/` half-wired; `tests/unit/test_ui_surface.py` holds the repo consistent in both directions.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it *touches* are
owned by sibling platform services, and you should integrate rather than rebuild them (see
[`docs/faq/features-faq.md`](faq/features-faq.md) for the full map). What is wired today, and what
is not, is recorded honestly in the R1 to R8 rows of [`COMPLIANCE.md`](../COMPLIANCE.md):

- `human-review-console` human-review and maker-checker console: wired. Every handover routes for the incoming
  lead's acknowledgement over the shared `review-kit` (rule R8), in the same call that built
  the brief. You point it at your console; you do not re-implement it.
- `model-quality-gate`: half wired. `eval/run_eval.py --mode gate` is the client
  and refuses to run off the managed profile; registering the bundle is yours.
- `agent-registry`: half wired. The A2A card is served at
  `/.well-known/agent-card.json` from the same tool table the runtime binds; registering it is
  yours.
- `agent-observability` and immutable WORM audit: half wired. The audit half is local and
  tamper-evident (hash chain plus an external head anchor); exporting traces and the audit stream
  to the shared sink is yours.
- `agent-guardrail-gateway`: **not** wired. There is no `GuardrailPort` today. Bind one before any
  untrusted text reaches the model, and screen the narration on the way back.
- `enterprise-knowledge-base` governed knowledge base: not used. This vertical retrieves nothing, so P-05 and R3 do
  not apply yet. If your fork adds retrieval, both become mandatory.
- **F1** `recon-breaks-engine` and **F2** `disputes-chargebacks-manager` are the upstream
  publishers of the worklist snapshots this service consumes. F5 computes the control-room view; it
  does not own reconciliation or dispute logic and must not grow either.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make gate` green.
- [ ] Set your in-country region in `config/settings.yaml` and in the Terraform tfvars, and pruned
      `var.allowed_regions` to what you have actually validated.
- [ ] Wired your IdP on the deployed service and set `CONTROLROOM_IAP_AUDIENCE` (this repo owns no
      login flow).
- [ ] Replaced the feed registry, pinned the upstream export schema, and reseeded every fixture.
- [ ] Owned the policy numbers (staffing baselines, anomaly thresholds, acknowledgement window,
      eval thresholds) with your operations and risk functions.
- [ ] Rebuilt the eval golden set and registered your bundle name with `model-quality-gate`.
- [ ] Read `docs/model-card.md` and closed its outstanding controls before enabling the managed
      narration path.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, bind address, audit anchor on a separate
      volume).
- [ ] Wired your `human-review-console` review endpoint and decided which sibling services you integrate vs stub.
- [ ] Ran `make drop-ui` if this fork has no user-facing surface.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
