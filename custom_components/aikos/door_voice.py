"""Speech for the door in a resident's own voice, through Home Assistant's TTS (the aikos TTS service via Wyoming; any
local TTS works, the voice is passed as the `voice` option). Imported lazily: aikos also runs without a TTS set up.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant


async def synthesize(hass: HomeAssistant, engine: str, text: str, voice: str) -> tuple[str, bytes]:
    """(file extension, audio). Raises HomeAssistantError (or another exception) if the service can't speak."""
    from homeassistant.components import tts

    source = tts.generate_media_source_id(hass, text, engine=engine, language="de", options={"voice": voice})
    ext, data = await tts.async_get_media_source_audio(hass, source)
    if not data:
        raise ValueError("no audio")
    return ext, data
