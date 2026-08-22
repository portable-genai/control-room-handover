"""ONE canonical request per port, shared by the structural and behavioural contract suites.

Parity means the same request through every implementation, so the request needs a single home.
Retyping it per suite is how two "parity" tests end up asserting different things.

Each :class:`PortCase` answers three questions about one port:

* ``invoke``   : what a single canonical call to this port looks like;
* ``answered`` : what it means for the OFFLINE family to have actually answered (a port that
  returns ``None`` and records nothing has not answered, it has merely not raised);
* ``managed_refusal`` : what the MANAGED family must do when called with no cloud reachable.
  Never a silent success: either it refuses because it is unconfigured, or its lazy SDK import
  fails. Both are honest; returning as if the work happened is not.

Adding a port means adding a case here. ``test_port_parity.py`` fails the build if this table and
the port map ever disagree, so the touch list in ``CONTRIBUTING.md`` is enforced rather than
merely written down.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_eval_kit import EvalReport
from hex_service_kit.identity import IdentityError, Principal, RequestContext
from hex_service_kit.observability import TokenUsage
from speech_lexicon_kit.ports import SpeechSynthesisRequest, SynthesisResult

from control_room_handover.domain.kernel import (
    AuditEvent,
    Citation,
    Decision,
    Severity,
)
from control_room_handover.domain.models import (
    FeedId,
    FeedSnapshot,
    LlmMessage,
    LlmRequest,
    LlmResponse,
)

from tests.fixtures import sample_cases

#: The audit record every audit-port implementation is handed. Already redacted, as the port
#: requires: a raw identifier must never reach a WORM record.
CANONICAL_EVENT = AuditEvent(
    action="shift_handover",
    actor=sample_cases.ACTOR,
    decision=Decision.ESCALATED,
    severity=Severity.HIGH,
    redacted_summary="Shift handover asia-day as of 2026-08-07",
    citations=(Citation(source_id="recon_breaks", title="Ops worklist export", snippet="urgent"),),
)

#: The reviewed brief every review-router implementation is handed (rule R8's payload).
CANONICAL_RESULT = sample_cases.sample_brief()

#: The inbound transport context every identity implementation is handed.
CANONICAL_CONTEXT = RequestContext(headers={"x-dev-persona": "auditor"})

#: The canonical narration request handed to every generation implementation.
CANONICAL_LLM_REQUEST = LlmRequest(
    messages=(LlmMessage(role="user", content="FIGURES:\n[recon_breaks] queue 320"),),
    response_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
)

#: The canonical synthesis request handed to every text-to-speech implementation.
CANONICAL_TTS_REQUEST = SpeechSynthesisRequest(
    request_id="handover-asia-day",
    text="Operations shift handover.",
    locale="en-SG",
)


@dataclass(frozen=True, slots=True)
class PortCase:
    """One port's canonical call plus the two verdicts the parity suites need."""

    invoke: Callable[[Any], Any]
    answered: Callable[[Any, Any], bool]
    managed_refusal: tuple[type[BaseException], ...]
    detail: str


def _audit_invoke(adapter: Any) -> Any:
    return adapter.record(CANONICAL_EVENT)


def _audit_answered(adapter: Any, _result: Any) -> bool:
    stored = adapter.log.read_all()
    return bool(stored) and stored[-1]["actor"] == sample_cases.ACTOR and adapter.verify().ok


def _identity_invoke(adapter: Any) -> Any:
    return adapter.resolve(CANONICAL_CONTEXT)


def _identity_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, Principal) and bool(result.actor)


def _review_invoke(adapter: Any) -> Any:
    return adapter.route(CANONICAL_RESULT, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)


def _review_answered(adapter: Any, result: Any) -> bool:
    return bool(result) and len(adapter.outbox.pending()) == 1


def _feeds_invoke(adapter: Any) -> Any:
    return adapter.snapshots(FeedId.RECON_BREAKS, 14)


def _feeds_answered(_adapter: Any, result: Any) -> bool:
    return bool(result) and all(isinstance(row, FeedSnapshot) for row in result)


def _generation_invoke(adapter: Any) -> Any:
    return adapter.generate(CANONICAL_LLM_REQUEST)


def _generation_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, LlmResponse) and bool(result.text)


def _tts_invoke(adapter: Any) -> Any:
    return adapter.synthesize(CANONICAL_TTS_REQUEST)


def _tts_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, SynthesisResult) and bool(result.audio.uri)


def _tracer_invoke(adapter: Any) -> Any:
    with adapter.span("canonical.unit", action="canonical"):
        adapter.record_token_usage(TokenUsage(input_tokens=7, output_tokens=2), "canonical-model")
    return True


def _tracer_answered(adapter: Any, result: Any) -> bool:
    return bool(result)


def _evaluation_invoke(adapter: Any) -> Any:
    return adapter.evaluate("eval/datasets/canonical.jsonl")


def _evaluation_answered(adapter: Any, result: Any) -> bool:
    return isinstance(result, EvalReport) and result.dataset.endswith("canonical.jsonl")


CANONICAL_CALLS: dict[str, PortCase] = {
    "audit": PortCase(
        invoke=_audit_invoke,
        answered=_audit_answered,
        # The lazy `google.cloud` import is the first thing the managed sink does.
        managed_refusal=(ImportError,),
        detail="write one already-redacted WORM record",
    ),
    "identity": PortCase(
        invoke=_identity_invoke,
        answered=_identity_answered,
        # No IAP assertion header offline, so the managed adapter refuses before importing.
        managed_refusal=(IdentityError,),
        detail="resolve a verified principal from transport context",
    ),
    "review_router": PortCase(
        invoke=_review_invoke,
        answered=_review_answered,
        # Rule R8: with no console configured the managed router must refuse, not swallow.
        managed_refusal=(RuntimeError,),
        detail="route one reviewed brief to human review",
    ),
    "ops_feeds": PortCase(
        invoke=_feeds_invoke,
        answered=_feeds_answered,
        # The lazy `google.cloud.bigquery` import is the first thing the managed reader does.
        managed_refusal=(ImportError,),
        detail="return the cited snapshot series for a feed",
    ),
    "generation": PortCase(
        invoke=_generation_invoke,
        answered=_generation_answered,
        # The lazy `google.genai` import is the first thing the managed narrator does.
        managed_refusal=(ImportError,),
        detail="narrate the scorecard over the given evidence",
    ),
    "tts": PortCase(
        invoke=_tts_invoke,
        answered=_tts_answered,
        # The lazy `google.cloud.texttospeech` import is the first thing the managed voice does.
        managed_refusal=(ImportError,),
        detail="synthesize a spoken handover reference",
    ),
    "tracer": PortCase(
        invoke=_tracer_invoke,
        answered=_tracer_answered,
        # NOTHING. Tracing is not essential to correctness, so the managed adapter must not refuse
        # offline either: with no SDK it degrades to a no-op and the traced body still runs. An
        # adapter that raised here would take a request down over a diagnostic.
        managed_refusal=(),
        detail="open one span and report the cost of a model call",
    ),
    "evaluation": PortCase(
        invoke=_evaluation_invoke,
        answered=_evaluation_answered,
        # The managed gate reaches Hrz4 over HTTP, which is unreachable offline.
        managed_refusal=(Exception,),
        detail="score one golden dataset through the promotion authority",
    ),
}
