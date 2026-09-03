# Model card: Control Room Handover (F5)

This is a STARTER model card. It records the model boundary as built and the controls that must be
completed before a managed deployment. The deterministic engine is the system of record; the model
is a bounded, replaceable component.

## What the model does, and does not do

- **Does**: from the already-computed, PII-redacted scorecard evidence it writes the prose summary
  of the shift-handover brief (`domain/handover_service.py`, the `GenerationPort` call). The output
  is JSON against a fixed two-key schema (`summary`, `used_source_ids`) and nothing else.
- **Does NOT**: produce any number, severity or verdict. Queue depth, backlog aging, SLA breach
  counts and rate, throughput, the drain ratio, capacity call-outs against the staffing baseline,
  the robust-z anomaly findings and every feed's severity are computed by
  `domain/scorecard_engine.py` and `domain/anomaly.py` in pure stdlib. The acknowledgement clock
  (`domain/acknowledgement.py`) and the rule R8 escalation are likewise deterministic. With the
  generation adapter stubbed the scorecard is byte-identical, so a model change cannot move a
  figure.

## Boundary and validation

- The model sees only the rendered FIGURES evidence block, redacted with the shared `pii-kit`
  rows selected in `domain/pii.py` BEFORE the prompt is built. It never sees a raw feed row.
- The response is schema-validated. A response that does not match `_NARRATION_SCHEMA` raises
  `NarrationDiscardedError` and the service falls back to a deterministic summary.
- The response is grounding-checked: every run of digits in the narration must appear in the engine
  evidence. A narration that introduces a figure the engine never produced is discarded, not
  repaired, and the brief records `narration_grounded=False`.
- The brief is redacted again before the audit write and before the review payload leaves the
  process, because the review console is a shared sink.
- `requires_human_review` is unconditionally `True` on a handover, and the brief is routed to Hrz7
  for the incoming shift lead's acknowledgement in the same call that produced it (rule R8).
  Nothing auto-executes.
- The offline eval scores `groundedness >= 0.99` and `pii_safety >= 0.99` alongside
  `scorecard_accuracy = 1.0`, and `tests/unit/test_not_falsely_green.py` proves the safety metric
  can go red.

## Adapters and profiles

| Profile | Generation adapter | Behaviour |
|---|---|---|
| `local` | `adapters/local/generation.py` | Deterministic schema-driven narrator. No model, no network, SDK-free. Emits a fixed summary that states the shape of the handover and introduces no figure of its own, plus the source ids parsed out of the evidence block. |
| `gcp` | `adapters/gcp/generation.py` | Gemini on the Gemini Enterprise Agent Platform, default model `gemini-3.5-flash`, `google.genai` imported lazily inside the method, JSON response mime type and the request's response schema passed through. |
| `onprem` | `adapters/onprem/generation.py` | Fail-fast placeholder. Raises `NotImplementedError` naming the migration target rather than returning canned prose, which is the honest failure: the scorecard is deterministic and needs no model. |

A second model-adjacent seam is optional text to speech for a spoken handover brief
(`ports/tts.py`, re-exported from `speech-lexicon-kit`). The `local` adapter is a deterministic
no-op that returns a reference and writes no audio; the managed adapter refuses a voice request
when `CONTROLROOM_AUDIO_BUCKET` is empty rather than returning a fictitious URI.

## Remaining controls (TODO, repo owner)

- **Model id, version and routing** for the `gcp` adapter (P-07): `gemini-3.5-flash` is an adapter
  default, not a pinned decision. Pin the exact model and record it here, with the prompt template
  under version control.
- **Budget and rate controls, and a kill switch** (P-10, P-11): there is no per-tenant token
  budget, no request rate limit and no switch that forces deterministic-only operation. Both P-10
  and P-11 are open rows in [`COMPLIANCE.md`](../COMPLIANCE.md).
- **Prompt-injection screening**: no `GuardrailPort` is bound, so nothing screens the evidence on
  the way in or the narration on the way out. Bind the Hrz1 gateway (rule R1) and fail closed to
  deterministic-only when the screen is unavailable.
- **Evaluation of the live model**: the offline eval scores the deterministic stub pipeline against
  the golden cases. Add a managed-profile run through the Hrz4 promotion gate that scores the real
  narration's groundedness against the same cases, and register the bundle
  `control-room-handover` with Hrz4 so `--mode gate` has an authority to ask.
- **Trace the model call**: the observability half of rule R2 is not wired, so the prompt and
  response record lands nowhere shared. Bind Hrz5 before the managed path carries real traffic.

Until these are complete the system is safe to run offline (deterministic engine plus the stub
narrator) and the managed model path is not production-cleared.
