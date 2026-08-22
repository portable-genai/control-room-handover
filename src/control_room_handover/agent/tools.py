"""Tool functions an agent runtime calls: thin, side-effect-honest wrappers on the services.

Design rules, in the order they matter:

* **No business logic here.** The domain service decides HOW; the model only decides WHICH tool
  to call. A rule that lives in a tool wrapper is a rule the CLI and the API do not have.
* **Rule R8 applies on this path too.** A built handover is ROUTED for sign-off from inside the
  tool, in the same call that produced it. An agent surface that only returned the brief would be
  a third place an acknowledgement can quietly stop, after the API and the CLI.
* **Import-safe without a runtime.** ``google.adk`` is imported lazily inside
  :func:`build_function_tools`, so these callables are importable, testable and runnable with no
  ADK and no cloud SDK installed.
* **Typed and documented.** A runtime derives each tool's name, description and JSON parameter
  schema from the signature and the docstring, so both are part of the contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hex_service_kit.serialization import to_jsonable
from pii_kit import redact

from ..config import Container, Settings, build_container
from ..domain.handover_service import HandoverService
from ..domain.models import HandoverRequest
from ..domain.pii import PII_PATTERNS

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

#: The identity a tool call is attributed to when the runtime propagates none. It names the
#: SERVICE, not a person, so an unattributed action is never mistaken for a human's.
DEFAULT_ACTOR = "control-room-handover-agent"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _redacted(node: Any) -> Any:
    """Mask personal data in every string of a tool result, however deeply it is nested.

    A tool result goes into a model's context, and P-04 says minimise the data that reaches a
    model. Walking the whole structure rather than a few named fields means a future field cannot
    arrive unredacted just because nobody remembered to add it.
    """
    if isinstance(node, str):
        return redact(node, PII_PATTERNS)
    if isinstance(node, dict):
        return {key: _redacted(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_redacted(value) for value in node]
    return node


def build_shift_handover(
    shift_id: str,
    as_of: str,
    lookback_days: int = 14,
    actor: str = DEFAULT_ACTOR,
    tenant: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Build a shift-handover brief and route it for the incoming lead's acknowledgement.

    Reads the F1 / F2 ops-feed snapshots, computes the control-room scorecard deterministically,
    narrates it (the model adds no number), writes an already-redacted audit event, and submits
    the brief to the human-review console for sign-off (rule R8).

    Args:
      shift_id: The shift being handed over, e.g. "asia-day".
      as_of: The ISO date the handover is as of, e.g. "2026-08-07".
      lookback_days: How many days of feed snapshots to read for the anomaly window.
      actor: The verified identity this call is attributed to.
      tenant: Tenant partition asserted on the outbound review.

    Returns:
      A JSON-safe result dict with every string masked for personal data, plus ``review_ref``:
      where the handover WENT for sign-off. It is never empty, because a handover always routes.
    """
    container = _container(settings)
    service = HandoverService(
        ops_feeds=container.ops_feeds,
        generation=container.generation,
        audit=container.audit,
        tts=container.tts,
        tracer=container.tracer,
    )
    brief = service.build_handover(
        HandoverRequest(shift_id=shift_id, as_of=as_of, lookback_days=lookback_days),
        actor=actor,
    )
    review_ref = container.review_router.route(brief, maker=actor, tenant=tenant)
    payload = _redacted(to_jsonable(brief))
    if not isinstance(payload, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("a handover brief must serialise to a JSON object")
    payload["review_ref"] = review_ref
    return payload


def verify_audit_trail(settings: Settings | None = None) -> dict[str, Any]:
    """Verify the audit trail's hash chain and its external head anchor.

    Returns:
      A dict with ``ok``, the record counts and a ``detail`` string. ``ok`` is false for an
      edited, deleted or reordered record, and, when an external anchor is configured, for a
      truncated tail as well. Without an anchor a truncation cannot be detected, and the detail
      says so rather than implying a stronger guarantee than the store provides.
    """
    resolved = settings or Settings.load()
    audit = _container(resolved).audit
    verify = getattr(audit, "verify", None)
    if verify is None:
        raise NotImplementedError(
            f"the {resolved.profile} audit adapter does not expose chain verification; a "
            "managed WORM sink is verified by its own retention policy, not from here"
        )
    report = verify()
    return {
        "ok": report.ok,
        "entries": report.entries,
        "chained": report.chained,
        "legacy": report.legacy,
        "first_bad_seq": report.first_bad_seq,
        "detail": report.detail,
        "anchored": bool(resolved.audit_anchor_path),
    }


#: The tool table. The agent card advertises exactly these, by function name.
TOOL_FUNCTIONS = (build_shift_handover, verify_audit_trail)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each callable as a runtime FunctionTool (the only ADK-dependent code path).

    The import is deliberately here rather than at module scope: without it this module, the card
    and every tool would need an agent runtime installed to be imported at all, and the offline
    gate installs none.
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=function) for function in TOOL_FUNCTIONS]
