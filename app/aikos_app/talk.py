"""Talking to the door live from the phone (A5, A48: hold to talk, as at a room key).

The phone sends its microphone as 16-bit little-endian PCM, 16 kHz mono, in 20 ms frames over the app's WebSocket; this
node turns it into RTP for the door. The door sends its microphone as RTP to this node, which passes it on to the phone.
Contract (vertraege.md §2, talk computer 0.7.24): `esphome.aikos_intercom_talk_app_join {host, ms}` announces this node's
socket (`host` = ip:port, `ms` ≤ 60 s, renewed before it runs out; "" and 0 = leave); for the call this socket is a key,
`esphome.aikos_intercom_talk_key_state {host, state}` at least every 3 s (2 = holds and talks, 1 = in the call and
listens, 0 = leaves). RTP L16 big-endian, PT 96, 16 kHz mono, 20 ms, from exactly that ip:port to UDP 5004 of the door.
Holding without a ring opens a call. One participant per node: the door knows one host:port.

As a room key does, the node sends a copy of what is said (and the end of speech) to the transcriber's room side
(`transcriber`, host:port). While someone is in the call from the app, aikos knows who (`aikos.app_talker {ip, name}`,
aikos 0.18.0): the transcript comes back under their name, and the door screen shows "<name> spricht gerade" (it looks the
node's address up in `sensor.aikos_people`, which lists the app while someone is in the call; Klingelbox, CHAT 22.10.).
"""

from __future__ import annotations

import asyncio
import logging
import random
import struct
from array import array
from collections.abc import Awaitable, Callable

from .ha.client import HaClient

_LOGGER = logging.getLogger(__name__)
DOOR_PORT = 5004
FRAME_BYTES = 640                  # 20 ms at 16 kHz, 16 bit
PT_AUDIO, PT_END = 96, 13
JOIN_MS = 30_000
JOIN_EVERY_S = 20
STATE_EVERY_S = 2
LISTEN, HOLD, LEAVE = 1, 2, 0


def swap16(pcm: bytes) -> bytes:
    """Little- ↔ big-endian 16-bit samples."""
    a = array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    a.byteswap()
    return a.tobytes()


class Rtp:
    def __init__(self) -> None:
        self.seq, self.ts, self.ssrc = random.getrandbits(16), random.getrandbits(32), random.getrandbits(32)

    def packet(self, payload: bytes, pt: int = PT_AUDIO, marker: bool = False) -> bytes:
        hdr = struct.pack("!BBHII", 0x80, pt | (0x80 if marker else 0), self.seq & 0xFFFF, self.ts & 0xFFFFFFFF, self.ssrc)
        self.seq += 1
        self.ts += FRAME_BYTES // 2
        return hdr + payload


def audio_payload(packet: bytes) -> bytes | None:
    """The door's RTP: the PCM (big-endian) of an audio packet, None for anything else."""
    if len(packet) <= 12 or packet[0] >> 6 != 2 or packet[1] & 0x7F != PT_AUDIO:
        return None
    csrc = packet[0] & 0x0F
    return packet[12 + 4 * csrc:]


class TalkBridge:
    """This node's socket for the door, and the one session that uses it."""

    def __init__(self, ha: HaClient, host: str, port: int, door: str, door_port: int = DOOR_PORT,
                 transcriber: str = "") -> None:
        self.ha = ha
        self.host, self.port, self.door, self.door_port = host, port, door, door_port
        self.enabled = bool(host and port and door)
        t_host, _, t_port = transcriber.rpartition(":")
        self.transcriber = (t_host, int(t_port)) if t_host and t_port.isdigit() else None
        self._transport: asyncio.DatagramTransport | None = None
        self.session: TalkSession | None = None

    @property
    def me(self) -> str:
        return f"{self.host}:{self.port}"

    async def start(self) -> None:
        if not self.enabled or self._transport is not None:
            return
        bridge = self

        class Door(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr) -> None:
                if addr[0] != bridge.door or bridge.session is None:
                    return   # only the door, only while someone listens
                pcm = audio_payload(data)
                if pcm:
                    bridge.session.from_door(swap16(pcm))

        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(Door, local_addr=("0.0.0.0", self.port))

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def send(self, packet: bytes) -> None:
        """To the door, and a copy to the transcriber (what is said from the app, as from a room key)."""
        if self._transport is not None:
            self._transport.sendto(packet, (self.door, self.door_port))
            if self.transcriber is not None:
                self._transport.sendto(packet, self.transcriber)

    async def action(self, name: str, data: dict) -> None:
        await self.ha.call_service("esphome", f"aikos_intercom_talk_{name}", data)


class TalkSession:
    """One phone in the call: listens from the start, talks while it holds."""

    def __init__(self, bridge: TalkBridge, to_phone: Callable[[bytes], Awaitable[None]], name: str = "") -> None:
        self.bridge = bridge
        self._to_phone = to_phone
        self.name = name
        self._named = False
        self.holding = False
        self._rtp = Rtp()
        self._first = False
        self._buffer = b""
        self._tasks: list[asyncio.Task] = []
        self._out: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)   # ~1 s of the door; older frames are dropped

    async def open(self) -> None:
        self.bridge.session = self
        await self._talker(self.bridge.host, self.name)
        await self.bridge.action("app_join", {"host": self.bridge.me, "ms": JOIN_MS})
        await self._state()
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._renew()), loop.create_task(self._forward())]

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.bridge.session is self:
            self.bridge.session = None
        try:
            await self.bridge.action("key_state", {"host": self.bridge.me, "state": LEAVE})
            await self.bridge.action("app_join", {"host": "", "ms": 0})
        except Exception as e:  # the door may be gone already; leaving must never raise
            _LOGGER.warning("talk: leaving the door: %s", e)
        if self._named:
            await self._talker("", "")

    async def _state(self) -> None:
        await self.bridge.action("key_state", {"host": self.bridge.me, "state": HOLD if self.holding else LISTEN})

    async def _renew(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(STATE_EVERY_S)
            n += 1
            try:
                await self._state()
                if n * STATE_EVERY_S % JOIN_EVERY_S == 0:
                    await self.bridge.action("app_join", {"host": self.bridge.me, "ms": JOIN_MS})
            except Exception as e:  # one missed refresh is not the end of the call
                _LOGGER.warning("talk: refresh: %s", e)

    async def _talker(self, ip: str, name: str) -> None:
        """Tell aikos who talks from the app, so the transcriber names it; aikos before 0.18.0 does not know it."""
        try:
            await self.bridge.ha.call_service("aikos", "app_talker", {"ip": ip, "name": name})
            self._named = bool(ip)
        except Exception as e:
            _LOGGER.info("talk: who talks not told: %s", e)

    async def hold(self, on: bool) -> None:
        if on == self.holding:
            return
        self.holding = on
        if on:
            self._first, self._buffer = True, b""
        else:
            self.bridge.send(self._rtp.packet(b"\x00", pt=PT_END))   # end of speech
        await self._state()

    def from_phone(self, pcm_le: bytes) -> None:
        if not self.holding:
            return
        self._buffer += pcm_le
        while len(self._buffer) >= FRAME_BYTES:
            frame, self._buffer = self._buffer[:FRAME_BYTES], self._buffer[FRAME_BYTES:]
            self.bridge.send(self._rtp.packet(swap16(frame), marker=self._first))
            self._first = False

    def from_door(self, pcm_le: bytes) -> None:
        if self.holding:
            return   # talking: the door's own sound would only echo back
        if self._out.full():
            self._out.get_nowait()
        self._out.put_nowait(pcm_le)

    async def _forward(self) -> None:
        while True:
            await self._to_phone(await self._out.get())
