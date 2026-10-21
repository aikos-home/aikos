"""The residents' own voices (rules A43–A45, S9): the app's link to the house's voice service (aikos TTS, HTTP with a token).
Each person enrols only their own voice; the voice id is derived from the account's random handle, so it is the same on
every node and says nothing about the person. Home Assistant speaks with it through its own link (Wyoming).
"""

from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import quote

import aiohttp

from .store.accounts import User

LIST_TTL_S = 30


class VoiceError(Exception):
    def __init__(self, code: str, status: int = 503) -> None:
        super().__init__(code)
        self.code, self.status = code, status


def voice_id(user: User) -> str:
    return "v" + hashlib.sha256(b"aikos-voice:" + user.handle).hexdigest()[:16]


class Voices:
    def __init__(self, url: str, token: str) -> None:
        self.url, self._token = url.rstrip("/"), token
        self._session: aiohttp.ClientSession | None = None
        self._cache: tuple[float, dict[str, dict]] = (float("-inf"), {})

    @property
    def enabled(self) -> bool:
        return bool(self.url and self._token)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def _request(self, method: str, path: str, **kw) -> tuple[int, bytes]:
        if not self.enabled:
            raise VoiceError("no_voice_service")
        if self._session is None:
            self._session = aiohttp.ClientSession()
        headers = {"Authorization": f"Bearer {self._token}", **kw.pop("headers", {})}
        try:
            async with self._session.request(method, self.url + path, headers=headers,
                                             timeout=aiohttp.ClientTimeout(total=kw.pop("timeout", 30)), **kw) as r:
                return r.status, await r.read()
        except (aiohttp.ClientError, TimeoutError):
            raise VoiceError("voice_service_unreachable") from None

    async def _all(self) -> dict[str, dict]:
        at, voices = self._cache
        if time.monotonic() - at < LIST_TTL_S:
            return voices
        status, body = await self._request("GET", "/v1/voices")
        if status != 200:
            raise VoiceError("voice_service_error")
        voices = {v["id"]: v for v in json.loads(body)}
        self._cache = (time.monotonic(), voices)
        return voices

    async def of(self, user: User) -> dict | None:
        """The person's enrolled voice ({seconds, created}), or None."""
        return (await self._all()).get(voice_id(user))

    async def for_speech(self, user: User) -> str:
        """The voice to read this person's text with; "" = shown only (no voice, or the service is away)."""
        if not self.enabled:
            return ""
        try:
            return voice_id(user) if await self.of(user) else ""
        except VoiceError:
            return ""

    async def enrol(self, user: User, audio: bytes) -> dict:
        status, body = await self._request("PUT", f"/v1/voices/{voice_id(user)}", data=audio, timeout=90,
                                           headers={"X-Voice-Name": quote(user.name)})
        self._cache = (float("-inf"), {})
        if status == 400:
            raise VoiceError("voice_recording", 400)
        if status != 200:
            raise VoiceError("voice_service_error")
        return json.loads(body)

    async def delete(self, user: User) -> None:
        status, _ = await self._request("DELETE", f"/v1/voices/{voice_id(user)}")
        self._cache = (float("-inf"), {})
        if status not in (204, 404):
            raise VoiceError("voice_service_error")

    async def prepare(self, user: User, texts: list[str]) -> None:
        """Say these once now, so they play at once later (the quick replies). Best effort."""
        try:
            await self._request("POST", "/v1/prepare", json={"voice": voice_id(user), "texts": texts})
        except VoiceError:
            pass

    async def sample(self, user: User, text: str) -> bytes:
        status, body = await self._request("POST", "/v1/speak", json={"voice": voice_id(user), "text": text}, timeout=90)
        if status == 404:
            raise VoiceError("no_voice", 404)
        if status != 200:
            raise VoiceError("voice_service_error")
        return body
