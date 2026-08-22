"""Managed voice output either persists real bytes or refuses with an honest capability gap."""

from __future__ import annotations

import pytest

from control_room_handover.adapters.gcp.tts import CloudTtsAdapter
from control_room_handover.config import Settings


def test_voice_persistence_refuses_when_no_managed_bucket_is_configured() -> None:
    adapter = CloudTtsAdapter(Settings(profile="gcp", audio_bucket=""))
    with pytest.raises(RuntimeError, match="voice output is unavailable"):
        adapter._persist("brief-1", b"synthetic audio")


def test_voice_persistence_refuses_an_empty_tts_response() -> None:
    adapter = CloudTtsAdapter(Settings(profile="gcp", audio_bucket="fictional-voice"))
    with pytest.raises(ValueError, match="empty audio"):
        adapter._persist("brief-1", b"")
