"""The handover path opens ONE span, and that span carries no content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit store.
So the value of tracing the handover path depends entirely on the span carrying structural
attributes only: which action, whose, how long. A queue figure, a citation snippet, the narrated
summary or the caller-chosen shift label reaching a span has left the boundary that the redact
calls exist to hold, and it has left it silently.

``shift_id`` arrives straight from the request body, so a caller can put anything in it. The
content case plants the NRIC there, which is exactly the leak an attribute set that "just adds
the shift" would create.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from control_room_handover.config import build_container
from control_room_handover.domain.handover_service import HandoverService
from control_room_handover.domain.models import HandoverBrief, HandoverRequest

from tests.conftest import local_settings
from tests.fixtures import sample_cases

#: Every attribute key the handover span is allowed to carry. The caller-supplied shift_id and
#: as_of are deliberately absent: both arrive from the request body, so neither is a structural
#: fact about the work. A critical handover that started explaining itself on the span (the
#: severity, a queue depth, a feed) would widen this set, which is the point of asserting on the
#: set rather than on the individual keys.
_HANDOVER_KEYS = {"action", "actor"}

#: A request whose shift label carries the planted identifier, exactly as a caller could send it.
_PII_REQUEST = HandoverRequest(
    shift_id=f"asia-day NRIC {sample_cases.PLANTED_NRIC}",
    as_of=sample_cases.HANDOVER_REQUEST.as_of,
    lookback_days=sample_cases.HANDOVER_REQUEST.lookback_days,
)


class _RecordingTracer:
    """Captures every span name and attribute so the test can inspect what was emitted."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _build(request: HandoverRequest) -> tuple[_RecordingTracer, HandoverBrief]:
    """The REAL local adapters for every port except the tracer under inspection."""
    container = build_container(local_settings())
    tracer = _RecordingTracer()
    service = HandoverService(
        ops_feeds=container.ops_feeds,
        generation=container.generation,
        audit=container.audit,
        tts=container.tts,
        tracer=tracer,  # type: ignore[arg-type]
    )
    brief = service.build_handover(request, actor=sample_cases.ACTOR)
    return tracer, brief


def _emitted(tracer: _RecordingTracer) -> str:
    """Every span name, attribute KEY and attribute VALUE, as one searchable blob."""
    parts: list[str] = []
    for name, attributes in tracer.spans:
        parts.append(name)
        parts.extend(attributes)
        parts.extend(attributes.values())
    return " ".join(parts)


def test_building_one_handover_opens_exactly_one_named_span() -> None:
    tracer, _ = _build(sample_cases.HANDOVER_REQUEST)
    assert [name for name, _ in tracer.spans] == ["handover.build"]


def test_the_span_carries_the_structural_attributes_an_operator_needs() -> None:
    """Enough to answer "whose handover is slow", and nothing more."""
    tracer, _ = _build(sample_cases.HANDOVER_REQUEST)
    _, attributes = tracer.spans[0]
    assert attributes["action"] == "build_handover"
    assert attributes["actor"] == sample_cases.ACTOR


@pytest.mark.parametrize(
    "request_case",
    [sample_cases.HANDOVER_REQUEST, sample_cases.ROUTINE_REQUEST, _PII_REQUEST],
    ids=["day", "night", "pii"],
)
def test_the_attribute_set_is_a_fixed_allowlist_whatever_the_severity(
    request_case: HandoverRequest,
) -> None:
    """A critical shift must not start attaching its queue depths to the span to explain itself."""
    tracer, _ = _build(request_case)
    for _, attributes in tracer.spans:
        assert set(attributes) == _HANDOVER_KEYS


def test_no_span_attribute_carries_brief_content_or_the_planted_identifier() -> None:
    """The request used here has an NRIC planted in the shift label, so a leak would show."""
    tracer, brief = _build(_PII_REQUEST)
    emitted = _emitted(tracer)

    forbidden: list[str] = [
        sample_cases.PLANTED_NRIC,
        _PII_REQUEST.shift_id,
        _PII_REQUEST.as_of,
        # The brief's subject and narrated summary are the other content-shaped values in reach
        # of this call, and the subject is built from the caller's own shift label.
        brief.subject,
        brief.summary,
        str(brief.scorecard.total_queue_depth),
    ]
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal not in emitted, f"a span attribute carried {literal!r}"
        assert literal.lower() not in emitted.lower(), f"a span attribute carried {literal!r}"

    # Belt and braces: no distinctive token of the narrated summary appears either, so a
    # truncated or reformatted fragment cannot slip through the whole-string checks above.
    tokens = {
        token.strip("().,:;") for token in brief.summary.split() if len(token.strip("().,:;")) > 6
    }
    emitted_tokens = set(emitted.lower().split())
    assert tokens, "the fixture must carry distinctive text for this check to mean anything"
    assert not {token.lower() for token in tokens} & emitted_tokens


def test_every_emitted_attribute_value_is_a_string_the_port_declares() -> None:
    """``span(name, **attributes: str)``: a non-string would serialise however the SDK felt."""
    tracer, _ = _build(sample_cases.ROUTINE_REQUEST)
    values: list[Any] = [value for _, attributes in tracer.spans for value in attributes.values()]
    assert values
    assert all(isinstance(value, str) for value in values)
