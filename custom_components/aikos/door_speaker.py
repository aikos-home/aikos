"""Plays a sound file on the door speaker (the greeting's recorded sound, speech in a resident's own voice), as the door's
speech output.

Contract (vertraege.md, talk computer 0.7.21+): `esphome.aikos_intercom_talk_allow_tts {host, ms}` lets the door play RTP
from `host` for `ms` (at most 60 s), also outside a call. The sound goes as the room keys send it: RTP v2, L16 big-endian,
PT 96, 16 kHz mono, 20 ms frames, to UDP 5004 of the talk computer. ffmpeg (part of Home Assistant) decodes whatever the
phone recorded. Everything stays in the house network (R11).
"""
from __future__ import annotations

import asyncio
import logging
import random
import socket
import struct
from pathlib import Path

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

TALK_DEVICE = "aikos-intercom-talk"          # the talk computer's device name (naming rule aikos-<family>-<role>)
ALLOW_ACTION = "aikos_intercom_talk_allow_tts"
CUE_ACTION = "aikos_intercom_talk_tts_cue"   # talk computer 0.7.26: a short soft two-tone, "speech is on its way"
DOOR_PORT = 5004
RATE, FRAME = 16000, 320                     # 20 ms
LEAD = 10                                    # frames ahead (200 ms) against Wi-Fi jitter; the door buffers 1 s
MAX_S = 50                                   # allow_tts grants at most 60 s
FFMPEG = "ffmpeg"


class DoorSpeakerError(Exception):
    pass


async def decode(path: Path, max_s: int = MAX_S) -> bytes:
    """Any audio ffmpeg reads → 16 kHz mono s16be, loudness-normalised, at most `max_s`."""
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path), "-t", str(max_s), "-af", "loudnorm=I=-18:TP=-3",
        "-f", "s16be", "-ar", str(RATE), "-ac", "1", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0 or not out:
        raise DoorSpeakerError(f"cannot decode {path.name}: {err.decode(errors='replace')[-200:]}")
    return out


def talk_host(hass: HomeAssistant) -> str:
    """The talk computer's address, from its ESPHome entry."""
    for entry in hass.config_entries.async_entries("esphome"):
        if entry.data.get("device_name") == TALK_DEVICE or entry.title == TALK_DEVICE:
            host = str(entry.data.get("host") or "")
            if host:
                return host
    raise DoorSpeakerError(f"no ESPHome entry for {TALK_DEVICE}")


def _resolve_and_source(host: str) -> tuple[str, str]:
    ip = socket.gethostbyname(host)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((ip, DOOR_PORT))  # no packet is sent; it only picks the interface the door sees us from
        return ip, s.getsockname()[0]
    finally:
        s.close()


def frames_of(pcm: bytes) -> list[bytes]:
    step = FRAME * 2
    if len(pcm) % step:
        pcm += b"\0" * (step - len(pcm) % step)
    ssrc, seq, ts = random.getrandbits(32), random.getrandbits(16), random.getrandbits(32)
    out = []
    for i in range(len(pcm) // step):
        hdr = struct.pack("!BBHII", 0x80, 96 | (0x80 if i == 0 else 0), (seq + i) & 0xFFFF, (ts + i * FRAME) & 0xFFFFFFFF, ssrc)
        out.append(hdr + pcm[i * step:(i + 1) * step])
    return out


async def stream(target: tuple[str, int], pcm: bytes) -> int:
    """RTP to the door, paced in real time with LEAD frames ahead. Returns the number of frames sent."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, remote_addr=target)
    try:
        frames = frames_of(pcm)
        t0 = loop.time()
        for i, f in enumerate(frames):
            transport.sendto(f)
            wait = t0 + (i + 1 - LEAD) * 0.02 - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
        return len(frames)
    finally:
        transport.close()


async def cue(hass: HomeAssistant) -> None:
    """The door's own short two-tone while speech is being made (silent during a call). Best effort, never waits."""
    if hass.services.has_service("esphome", CUE_ACTION):
        try:
            await hass.services.async_call("esphome", CUE_ACTION, {}, blocking=False)
        except Exception as e:  # the cue is a nicety; the speech comes anyway
            _LOGGER.debug("aikos: no cue at the door: %s", e)


async def play(hass: HomeAssistant, path: Path) -> float:
    """The file at the door. Returns the seconds played; raises DoorSpeakerError if the door can't be reached."""
    if not hass.services.has_service("esphome", ALLOW_ACTION):
        raise DoorSpeakerError(f"esphome.{ALLOW_ACTION} not there")
    pcm = await decode(path)
    door_ip, me = await hass.async_add_executor_job(_resolve_and_source, talk_host(hass))
    seconds = len(pcm) / 2 / RATE
    await hass.services.async_call("esphome", ALLOW_ACTION, {"host": me, "ms": int(seconds * 1000) + 2000}, blocking=True)
    await asyncio.sleep(0.3)
    frames = await stream((door_ip, DOOR_PORT), pcm)
    _LOGGER.info("aikos: %.1f s played at the door", frames * 0.02)
    return seconds
