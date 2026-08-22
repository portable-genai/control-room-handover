# Security FAQ

For an AppSec reviewer sizing up this repo. It explains what the attack surface is, what is
deliberately out of scope (and why that is honest rather than a gap), and where the evidence lives.
Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`COMPLIANCE.md`](../../COMPLIANCE.md), [`docs/runbook.md`](../runbook.md).

## What does this system actually process?

Aggregate operational queue metrics: one ops-worklist export snapshot per feed per `as_of`, giving
queue depth, backlog aging buckets, SLA clock-state counts, throughput and the partition each row
was read from. It produces a control-room scorecard and a shift-handover brief. It does not query a
customer record store and it has no per-customer surface.

That said, an operational item's free text can carry a personal identifier, so redaction is not
optional here: `domain/pii.py` selects and orders the jurisdiction rows from the shared `pii-kit`,
and `domain/handover_service.py` redacts before the model sees the evidence, before the audit write
and before the review payload leaves the process. The demo and the eval both plant a synthetic
national id specifically so a redaction check has an independent literal to look for, and
`tests/unit/test_not_falsely_green.py` proves the safety metric can go red.

## How is identity handled? Can a caller spoof the actor?

No. Identity is resolved server-side on every route. The request schemas carry no `actor` field;
`api/app.py::get_principal` builds a `RequestContext` from the headers and resolves a verified
`Principal` through the bound `IdentityPort`, and that verified principal, never a client-supplied
value, is the audit actor and the review maker. The commons helper `make_get_principal` is
deliberately not used, because it collapses every identity error into a bare 401 and this service
distinguishes a caller fault (401 with the reason kept in the log) from a deployment fault (503
naming the fix).

The three profiles differ in what they can honestly claim. `local` seeds dev personas via
`X-Dev-Persona` and authenticates nobody, so it is offline demo and test only. `gcp` verifies the
IAP-injected assertion: `id_token.verify_token` is called with the configured
`CONTROLROOM_IAP_AUDIENCE` and with IAP's own key set rather than google-auth's OAuth2 default, and
the issuer is checked in the adapter because `verify_token` does not check it. `onprem` is a
client-IdP placeholder that raises rather than falling back.

`CONTROLROOM_IAP_AUDIENCE` is read in three states on purpose: unset and set-and-empty both refuse
every caller, because google-auth documents `audience=None` as "the audience is not verified",
which would accept any Google-signed token from any project and read its email as a principal.

## What stops the service being served with no authentication?

A module-scope loopback exposure guard on the app object, not a bound in `main()`, because the
Dockerfile `CMD` and `make run-api` serve the app object. Its posture is derived from the identity
BINDING: the adapter declares whether it can produce a verified principal without trusting a header
the client wrote (`ports/identity.py`: verified, client-asserted, unimplemented, defaulting to
client-asserted when silent). A service credential may never enter that decision, and
`tests/unit/test_end_user_auth_posture.py` walks the guard's argument through the constants it
names to keep it out. `tests/unit/test_serving_path_exposure.py` is the standing gate on the bind
site itself.

Interactive docs (`/docs`, `/redoc`, `/openapi.json`) are registered only under the deliberate
`local` exposure profile. They are ABSENT rather than guarded elsewhere, because a guard the
profile has stood down is not a guard.

## Why can a mis-typed profile take the process down?

Because that is cheaper than serving on a posture nobody chose. `CONTROLROOM_PROFILE` resolves once
at import into a `ProfileChoice` with three states: unset is NO CHOICE rather than a silent
`local`, an emptied value raises, and an unknown or mis-capitalised value (`Local`, `GCP`) raises.
Only `config.py` may read the variable; `tests/unit/test_profile_single_source.py` fails the build
if another module re-derives it, because a permissive default gets reintroduced one module at a
time. `tests/unit/test_three_state_env_reads.py` walks the AST of `src/`, `scripts/` and `eval/`
and fails the build on any two-state environment read that ships, and the `ui/` half has the same
guard in `ui/tests/three-state-env-reads.test.mjs`.

## What about the browser boundary?

The client never asserts identity. Every client-supplied actor, tenant, role, ACL and authorization
header is discarded before forwarding (`ui/lib/embed-policy.mjs`), identity is resolved
server-side, and the service credential is read from the server environment so it never reaches a
bundle. Framing and per-tenant CORS are allowlists that refuse a wildcard however it is written, and
they refuse from `next.config.mjs` so a UI whose allowlist rendered empty never boots. If a fork has
no user-facing surface, `make drop-ui` removes `ui/` with its npm dependabot ecosystem and its CI
job in one step, and `tests/unit/test_ui_surface.py` holds the repo consistent in both directions.

## What about outbound service-to-service calls?

The rule R8 review submission is the real outbound call. It goes through the shared
`review-kit` client, which refuses a plaintext non-loopback URL and a missing bearer at
construction. Inbound S2S uses `make_require_service_caller` from the commons. The outbound Hrz7
credentials (`HRZ7_S2S_TOKEN`, `HRZ7_S2S_SIGNING_KEY`) are deliberately distinct variables from this
service's own inbound `CONTROLROOM_S2S_TOKEN`, so one cannot be mistaken for the other.

## Are there secrets in the repo?

No literal secret material. `config/settings.yaml` holds env var NAMES and non-secret defaults with
`${VAR:-default}` interpolation only; `.env.example` documents the non-secret environment and
`.env.secrets.example` carries placeholder values. `tests/unit/test_repo_artifacts.py` asserts that
no example env file carries a real-looking value.

## What is the supply-chain posture?

Committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`, py3.12) with `ruff` pinned
exactly, a multi-stage digest-pinned non-root Dockerfile (uid 10001, `HEALTHCHECK`) that installs
from the lock then the project with `--no-deps`, SHA-pinned GitHub Actions, `dependabot.yml` per
ecosystem, and `pip-audit` plus `npm audit` as hard CI failures. The catalog commons are pinned to
40-character COMMIT shas rather than tags, and `tests/unit/test_repo_artifacts.py` asks a local git
object store whether each pinned sha is a commit object and not an annotated tag object, which is a
distinction no regular expression can make.

## Is the audit trail tamper-evident?

Yes, within honest limits, and the limits are the interesting part. The local sink wraps the
commons `HashChainedAuditLog`: a SHA-256 hash chain with update and delete triggers, JSONL export
and restore, and `verify_chain()`. A hash chain detects an in-place edit, a deletion and a reorder,
but it CANNOT detect a truncated tail, because dropping the newest rows leaves a shorter chain that
verifies perfectly. So `audit_anchor_path` (`CONTROLROOM_AUDIT_ANCHOR`) writes the chain head to a
file on a different volume under different credentials, and
`tests/unit/test_audit_anchor.py` proves the detection, proves the control case goes UNDETECTED
without an anchor, and proves an append after truncation refuses rather than re-anchoring. In
production the managed WORM sink (Hrz5, or a locked Cloud Logging bucket) is the real answer; the
local chain is the offline stand-in. Operating rules are in [`docs/runbook.md`](../runbook.md).

## What is explicitly out of scope for this repo?

The guardrail and prompt-injection screening engine (**Hrz1**, and note it is **not wired** today,
which is recorded as an open R1 row rather than glossed over), the governed knowledge base
(**Hrz2**), the agent registry (**Hrz3**), the AI-quality and eval gate (**Hrz4**), the shared WORM
audit and tracing sink (**Hrz5**), and the human-review console (**Hrz7**). The reconciliation and
dispute engines upstream (**F1**, **F2**) are out of scope too: F5 reads their published snapshots
and owns none of their logic. See [features-faq.md](features-faq.md) for the full boundary map.
