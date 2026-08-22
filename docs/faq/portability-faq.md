# Portability FAQ

For architecture, cloud, and exit-planning reviewers who want to know how real the "no lock-in"
claim is and how an off-cloud or sovereign exit would work. Cross-references:
[`ARCHITECTURE.md`](../../ARCHITECTURE.md), [`docs/onprem-migration.md`](../onprem-migration.md).

## What is the no-lock-in claim, concretely?

`src/control_room_handover/domain/` is pure standard library plus the stdlib-only catalog commons.
No cloud SDK, no web framework, no HTTP client. Every outbound concern lives behind a
`@runtime_checkable` `Protocol` in `ports/`, and the whole adapter stack is selected by one setting.
The domain is where the consequential work happens, so the thing you would have to rewrite on an
exit is the thing that has no vendor in it.

## What are the three profiles?

`CONTROLROOM_PROFILE` selects the whole adapter family:

- **`local`** a real, working, SDK-free offline stack: seeded dev personas, a hash-chained SQLite
  WORM audit log from the commons, deterministic feeds, a deterministic narrator and a no-op TTS.
  This is the dev, test and CI default, and the working proof that the domain runs entirely
  off-cloud.
- **`gcp`** the managed services: Cloud Logging WORM audit, IAP identity, Gemini narration, Cloud
  TTS, Cloud Trace, the Hrz4 eval gate. Every SDK import is lazy, inside the method, so the module
  tree stays importable with no cloud SDK installed.
- **`onprem`** fail-fast placeholders that satisfy the same Protocols. They raise
  `NotImplementedError` and name the migration target, which proves the ports are honest exit seams
  rather than decoration.

Unset is its own state, not a silent `local`: the offline adapters bind but nobody chose them, so
the seeded personas are refused, no S2S scheme is selected, and the exposure guard refuses every
non-loopback peer.

## Is the portability claim tested, or just asserted?

Tested, and bounded. `make portability` runs `scripts/portability_demo.py` offline with eight named
checks, each passing or failing on its own, and exits non-zero on any failure: the port map is
complete across every profile, every adapter constructs from a single `Settings` argument and
conforms to its Protocol, the offline family ANSWERS, the exit family REFUSES, an in-place rewrite
of an audit record is detected, an anchored trail detects a truncated tail, the trail exports and
reloads intact outside this codebase, and no `google.*` module was imported by any of it. The
script prints what it does NOT prove rather than leaving the claim unbounded.

Inside the gate, `tests/contract/test_port_parity.py` asserts set equality across all five homes of
a port (the Protocol map, `DEFAULT_BINDINGS`, the `Container` accessor, `config/settings.yaml`, and
the canonical-call table), so an unregistered port cannot run untested, and
`tests/contract/test_behavioral_parity.py` proves the offline family answers, the on-premises
family raises and the managed family refuses rather than silently succeeding.

## How would a sovereign or on-prem exit actually go?

The `onprem` profile is the scaffold, and each fail-fast placeholder marks one seam where a client
supplies their own component: their worklist feed, their model host, their IdP, their audit store,
their review console, their tracer. Because the domain never changes, the exit is an adapter
exercise rather than a rewrite. The `onprem` generation adapter is the clearest illustration: it
refuses rather than returning canned prose, because a handover narrated by nobody's model is worse
than a handover with a deterministic summary, which is what the service falls back to anyway. See
[`docs/onprem-migration.md`](../onprem-migration.md).

## Can the data be exported in an open format?

Yes. The audit trail exports to and restores from JSON Lines, and the portability check proves the
exported trail reloads intact in a fresh store outside this codebase. That is what makes the exit a
file copy rather than a migration project. The scorecard and brief serialise to plain JSON, which
is also what the demo renderer reads.

## How is data residency handled?

One region value, shared by the runtime and the deploy. `region` in `config/settings.yaml`
(`GCP_REGION`, default `asia-southeast1`) is what the service reports on `/healthz` and prints on
the agent card, so a drifting deployment is visible. `infra/terraform/variables.tf` validates
`var.region` against `var.allowed_regions` at plan time, so an unvetted region fails
`terraform plan` rather than putting regulated data out of jurisdiction; `org_policy.tf` applies the
`gcp.resourceLocations` allowlist so an out-of-region resource cannot be created;
`kms.tf` binds a REGIONAL CMEK key ring in the same region as the data it protects; and
`vpc_sc.tf` stands up a dry-run-first VPC-SC perimeter around the sovereignty-critical APIs. A
second region is a tfvars change plus a settings change, not a fork.

## What is honestly NOT portable, or not proven?

- **Tamper evidence** is scoped to what the local sink can prove. The hash chain detects an edit, a
  deletion and a reorder; only the external anchor detects a truncated tail; and neither is a
  substitute for a managed WORM sink in production. The portability script says so rather than
  overclaiming.
- **The shared platform sinks** are not portable by this repo's choice. Tracing to Hrz5 and the
  promotion verdict from Hrz4 are calls to systems this repo does not own; the `onprem` family
  refuses them so the dependency is visible rather than silently degraded.
- **The upstream feed contract.** F5 holds a CONSUMED copy of the ops-worklist export schema rather
  than a pin to the publisher's file, which is recorded as an assumption in
  [`docs/ops-metrics-contract.md`](../ops-metrics-contract.md). A fork that binds its own queues
  should pin its publisher's schema and keep `tests/unit/test_feed_contract.py` pointed at it.
