"""Managed TextToSpeechPort: synthesize the spoken handover with Cloud TTS (SDK imported lazily).

The primary adapter. It synthesises the handover brief with Google Cloud Text-to-Speech, writes
the audio to this deployment's object store (a GCS bucket named in settings) and returns the URI,
so the speech kit never becomes the thing that persisted audio. The ``google.cloud.texttospeech``
import is INSIDE the method, so the offline profiles import this module with no TTS SDK installed.
Optional: it is only reached when a handover requests a voice brief.
"""

from __future__ import annotations

from urllib.parse import quote

from speech_lexicon_kit.ports import (
    AudioRef,
    SpeechSynthesisRequest,
    SynthesisResult,
)

from ...config import Settings


class CloudTtsAdapter:
    """Cloud Text-to-Speech synthesizer for the managed profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def synthesize(self, request: SpeechSynthesisRequest) -> SynthesisResult:
        # Lazy import: the offline profiles must import this module with no TTS SDK present.
        from google.cloud import texttospeech  # noqa: PLC0415

        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=request.text)
        voice = texttospeech.VoiceSelectionParams(language_code=request.locale)
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        )
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        uri = self._persist(request.request_id, response.audio_content)
        return SynthesisResult(
            request_id=request.request_id,
            audio=AudioRef(uri=uri, media_type=request.audio_encoding),
            voice=request.voice,
            characters_billed=len(request.text),
        )

    def _persist(self, request_id: str, audio: bytes) -> str:
        """Write bytes to the configured regional bucket with application-default identity."""
        bucket = self._settings.audio_bucket.strip()
        if not bucket:
            raise RuntimeError(
                "voice output is unavailable: CONTROLROOM_AUDIO_BUCKET is not configured; "
                "the text handover remains the record of authority"
            )
        if not audio:
            raise ValueError("Cloud TTS returned an empty audio payload")

        # Use the Storage JSON upload surface through google-auth instead of another SDK. Both
        # imports remain lazy and already belong to the managed dependency set.
        from google.auth import default as google_auth_default
        from google.auth.transport.requests import AuthorizedSession

        credentials, _project = google_auth_default(
            scopes=("https://www.googleapis.com/auth/devstorage.read_write",)
        )
        object_name = f"voice-briefs/{request_id}.mp3"
        url = (
            "https://storage.googleapis.com/upload/storage/v1/b/"
            f"{quote(bucket, safe='')}/o?uploadType=media&name={quote(object_name, safe='')}"
        )
        response = AuthorizedSession(credentials).post(
            url,
            data=audio,
            headers={"Content-Type": "audio/mpeg"},
            timeout=30.0,
        )
        response.raise_for_status()
        return f"gs://{bucket}/{object_name}"
