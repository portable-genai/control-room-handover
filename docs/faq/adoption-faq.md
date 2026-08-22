# Adoption FAQ

For an engineering lead forking this repo as their institution's control-room base. The
step-by-step is [`docs/ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?"
questions.

### How do I rebrand it for my organisation?

`scripts/rename_fork.py` rewrites the python package (`control_room_handover`), the console-script
name, the `CONTROLROOM` env-var prefix, the Terraform `name_prefix` stem (`f5-svc`) and the
distribution / git id (`control-room-handover`) in one pass. Preview with `--dry-run`, apply
with `--yes`, add `--include-docs` to sweep Markdown prose. Then recreate the venv, `make install`,
and run `make gate`. The script does the mechanical rename; the human decisions (region, IdP, feed
registry, policy numbers, eval golden set) are the checklist in `ADOPTING.md`.

One design note worth knowing before you read the script: in this template the console-script name
IS the package name, so every rule is applied in ONE simultaneous pass and the CLI rules match only
where a command NAME can appear (the `[project.scripts]` key, and a documented shell invocation
followed by a subcommand or a flag). A sequential search and replace would rename the command twice.
The script also rewrites its own `_OLD_*` constants, so a fork's copy can rename itself again.

### If several institutions fork this, how does each take upstream fixes?

Track upstream by **git tag**. The repo declares a core-vs-adopter-owned boundary
([`ADOPTING.md`](../ADOPTING.md) section 2): upstream owns `domain/kernel.py`, `ports/`,
`tests/contract/`, the eval harness mechanics, CI and the `api/` security posture; you own the
values in `config/settings.yaml`, the staffing baselines and anomaly thresholds, the feed registry
and fixtures, `adapters/onprem/*`, the `ui/` theming and the eval golden set. Rebase your
adopter-owned changes onto each release rather than merging `main` continuously, so conflicts stay
in files you were told to expect.

### Is there a real kernel module, or is the boundary just a convention?

Real. `domain/kernel.py` holds the vertical-neutral machinery (`Citation`, `AuditEvent`, `Severity`,
`Decision`, `utcnow`, the `LenientStrEnum` vocabularies) and imports nothing from the vertical.
`domain/models.py` holds this vertical's artifacts (`FeedId`, `FeedSnapshot`, `FeedScorecard`,
`ControlRoomScorecard`, `HandoverBrief`, `StaffingBaseline` and the rest) and imports the kernel,
never the reverse. A fork building a different operating model rewrites `models.py` and leaves
`kernel.py` alone. This is recorded as a PASS on check A7 in
[`docs/practices-audit.md`](../practices-audit.md).

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list and a contract test that enforces it. A port must be registered in FIVE
places or it runs with no enforcement at all: `ports/__init__.py` (the `PORT_PROTOCOLS` map),
`config.DEFAULT_BINDINGS`, a `Container` accessor, `config/settings.yaml`, and a `PortCase` in
`tests/contract/canonical.py`. Then bind it in all three families.
`tests/contract/test_port_parity.py` asserts set equality across the five, so a missed step fails
the build rather than passing silently. See [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How do I add a feed?

One more `FeedId` member, its export fixture, and its staffing baseline in `domain/policy.py`. The
`ScorecardEngine` reads the snapshot shape rather than any queue's semantics, so no engine code
changes. `tests/unit/test_feed_contract.py` validates every export fixture against the schema, so a
fixture that stops conforming fails the build. The recorded assumption about bounded feed coverage
is in [`docs/ops-metrics-contract.md`](../ops-metrics-contract.md).

### How do I change the taxonomy?

The vocabularies are `LenientStrEnum`s from the shared commons and the engines are typed on `str`,
so a member IS its wire value and an unknown value from a future release does not crash the reader.
You extend a vocabulary without editing engine code; serialized JSON values are the enum strings.
To replace one wholesale, edit the enum in `domain/models.py` and the label map in the UI.

### Can I retune the policy numbers without touching code?

Not yet, and this is stated honestly rather than glossed. The staffing baselines
(`domain/policy.py`), the robust-z thresholds and minimum window (`domain/anomaly.py`, already
tunable dataclass fields rather than magic numbers) and the acknowledgement deadline
(`domain/acknowledgement.py`) live in the domain as module-level data, not in a `policy:` block in
`config/settings.yaml` loaded through `config.py`. That lift is the open **B4** item in
[`docs/practices-audit.md`](../practices-audit.md). If your operations or risk function must own
these numbers as reviewable configuration, plan that small addition as part of adoption, and add a
test that pins your values.

### Will the demo rot after I diverge?

It is guarded, and the guard is in two places. `tests/unit/test_demo_surface.py` runs inside
`make gate`: it holds `demo.STEPS` and `walkthrough.CHECKS` equal so a narrated claim nobody
verifies cannot exist, drives the whole arc against the real adapters, asserts the tamper step
actually goes red (a demo with no failing panel is a sales deck), and proves the demo surface
imports no cloud SDK in a fresh interpreter. Separately,
`.github/workflows/demo-gate.yaml` runs `make demo-selftest`, `make portability`,
`make demo-static` and `make docs-check` on every push. That same test also requires every
`scripts/*.py` to be described in [`scripts/README.md`](../../scripts/README.md), so the index
cannot fall behind the directory.

### Does CI run for my fork out of the box?

Yes. The offline gate needs no network, no cloud SDK and no credentials, and the workflow
references no organisation secrets, so a fork's build is green immediately. You add secrets only
when you wire the `gcp` profile. Note that the eval gate measures the *reference* golden cases until
you rebuild them for your own queues; that is an explicit adoption step, not a silent pass. The
Hrz4 bundle name is `control-room-handover` and needs renaming and registering with your fork.

### What is still open on day one?

Read [`docs/practices-audit.md`](../practices-audit.md) and the `TODO (repo owner)` rows in
[`COMPLIANCE.md`](../../COMPLIANCE.md) before you cite either as evidence. The short version: the
policy numbers are not yet configuration (B4), the Hrz1 guardrail is not bound (R1), Hrz5
observability and the Hrz4 bundle registration are outstanding (R2, R5), there is no retrieval so
P-05 and R3 do not apply yet, and P-10 resilience controls and P-11 cost controls have not been
built. The deterministic scorecard, the redaction chain, the anchored audit trail and the R8
routing are complete and tested.
