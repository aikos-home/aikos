"""The single connection to Home Assistant (WebSocket API), with a fixed list of allowed commands.

Rule G4: the app's Home Assistant account is not an admin. Every command here is one a normal user may run (checked in
Home Assistant 2026.9.4: none of their handlers is admin-only). Anything else is refused before it leaves the app, so a
bug in an endpoint can never turn into a general door into Home Assistant (rule G2).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import Callable, Iterable
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

ALLOWED_COMMANDS = frozenset({
    "get_states",
    "subscribe_entities",
    "history/history_during_period",
    "media_source/browse_media",
    "media_source/resolve_media",
    "call_service",
})
ALLOWED_SERVICES = frozenset({
    ("aikos", "door_messages"),
    ("aikos", "door_message_delete"),
    ("aikos", "door_message_heard"),
    ("aikos", "bell_mute"),
    ("aikos", "bell_unmute"),
    ("aikos", "quiet_hours"),
    ("aikos", "door_say"),
    ("aikos", "door_say_cancel"),
    ("aikos", "door_picture"),
    ("aikos", "door_picture_clear"),
    ("aikos", "door_greeting"),
    ("aikos", "door_announcements"),
})
"""The services the app may call, each behind one endpoint that checks the person's rights first (rule G2)."""

MEDIA_PATH_PREFIXES = ("/media/local/", "/local/aikos_door/")
"""Signed local media links (resolve_media), and the door picture (public in Home Assistant anyway)."""
COMMAND_TIMEOUT_S = 15
CONNECT_WAIT_S = 5


class HaError(Exception):
    def __init__(self, message: str = "", code: str = "") -> None:
        super().__init__(message)
        self.code = code


class HaNotConnected(HaError):
    pass


class HaClient:
    def __init__(self, url: str, token: str, session: aiohttp.ClientSession | None = None) -> None:
        self._url, self._token = url.rstrip("/"), token
        self._session = session
        self._own_session = session is None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._watched: list[str] = []
        self._states: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[str, dict[str, Any] | None], None]] = []
        self._sub_id: int | None = None
        self.last_error = ""

    # life cycle
    def watch(self, entity_ids: Iterable[str]) -> None:
        """Entities whose state the app keeps live (set before start)."""
        self._watched = sorted({e for e in entity_ids if e})

    def on_change(self, listener: Callable[[str, dict[str, Any] | None], None]) -> None:
        self._listeners.append(listener)

    async def start(self) -> None:
        if not self._url or not self._token:
            self.last_error = "not configured"
            return
        if self._session is None:
            self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._run(), name="aikos-app ha connection")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._own_session and self._session:
            await self._session.close()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def state(self, entity_id: str) -> dict[str, Any] | None:
        return self._states.get(entity_id)

    # commands
    @staticmethod
    def check(type_: str, payload: dict[str, Any]) -> None:
        """Refuse anything outside the fixed lists before it leaves the app."""
        if type_ not in ALLOWED_COMMANDS:
            raise HaError(f"command not allowed: {type_}")
        if type_ == "call_service" and (payload.get("domain"), payload.get("service")) not in ALLOWED_SERVICES:
            raise HaError(f"service not allowed: {payload.get('domain')}.{payload.get('service')}")

    async def call_service(self, domain: str, service: str, data: dict[str, Any] | None = None, *,
                           response: bool = False) -> Any:
        result = await self.command("call_service", domain=domain, service=service, service_data=data or {},
                                    return_response=response)
        return (result or {}).get("response") if response else None

    async def command(self, type_: str, **payload: Any) -> Any:
        self.check(type_, payload)
        if not self._connected.is_set():
            try:
                await asyncio.wait_for(self._connected.wait(), CONNECT_WAIT_S)
            except TimeoutError:
                raise HaNotConnected(self.last_error or "not connected") from None
        msg_id = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        try:
            await self._ws.send_json({"id": msg_id, "type": type_, **payload})
            msg = await asyncio.wait_for(fut, COMMAND_TIMEOUT_S)
        except (ConnectionError, aiohttp.ClientError, AttributeError) as e:
            raise HaNotConnected(str(e)) from e
        except TimeoutError:
            raise HaError(f"{type_}: no answer") from None
        finally:
            self._pending.pop(msg_id, None)
        if not msg.get("success"):
            err = msg.get("error") or {}
            raise HaError(err.get("message", "failed"), str(err.get("code") or ""))
        return msg.get("result")

    async def media(self, url: str, headers: dict[str, str] | None = None) -> aiohttp.ClientResponse:
        """GET a signed media link from `media_source/resolve_media`, or the door picture. The caller releases the response."""
        if not url.startswith(MEDIA_PATH_PREFIXES) or ".." in url:
            raise HaError("not a local media link")
        if self._session is None:
            raise HaNotConnected("not started")
        return await self._session.get(self._url + url, headers=headers or {},
                                       timeout=aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=30))

    # connection
    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._connect_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep trying; the app answers "Home Assistant not reachable" meanwhile
                self.last_error = f"{type(e).__name__}: {e}"
                _LOGGER.warning("Home Assistant connection: %s", self.last_error)
            finally:
                self._connected.clear()
                self._ws = None
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(HaNotConnected("connection lost"))
                self._pending.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _connect_once(self) -> None:
        async with self._session.ws_connect(self._url + "/api/websocket", heartbeat=30,
                                            max_msg_size=32 * 1024 * 1024) as ws:
            hello = await ws.receive_json(timeout=10)
            if hello.get("type") != "auth_required":
                raise HaError(f"unexpected greeting {hello.get('type')}")
            await ws.send_json({"type": "auth", "access_token": self._token})
            auth = await ws.receive_json(timeout=10)
            if auth.get("type") != "auth_ok":
                raise HaError("authentication failed")
            self._ws = ws
            self._states.clear()
            if self._watched:
                self._sub_id = next(self._ids)
                await ws.send_json({"id": self._sub_id, "type": "subscribe_entities", "entity_ids": self._watched})
            self._connected.set()
            self.last_error = ""
            _LOGGER.info("connected to Home Assistant")
            async for raw in ws:
                if raw.type != aiohttp.WSMsgType.TEXT:
                    break
                self._dispatch(raw.json())

    def _dispatch(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if msg.get("type") == "event" and msg_id == self._sub_id:
            self._apply_entities(msg.get("event") or {})
        elif msg_id in self._pending and not self._pending[msg_id].done():
            self._pending[msg_id].set_result(msg)

    def _apply_entities(self, ev: dict[str, Any]) -> None:
        """Compressed states of `subscribe_entities`: a = added, c = changed (+ / -), r = removed."""
        changed: list[str] = []
        for eid, s in (ev.get("a") or {}).items():
            self._states[eid] = {"state": s.get("s"), "attributes": dict(s.get("a") or {}),
                                 "last_changed": s.get("lc")}
            changed.append(eid)
        for eid, diff in (ev.get("c") or {}).items():
            cur = self._states.setdefault(eid, {"state": None, "attributes": {}, "last_changed": None})
            plus, minus = diff.get("+") or {}, diff.get("-") or {}
            if "s" in plus:
                cur["state"] = plus["s"]
            if "lc" in plus:
                cur["last_changed"] = plus["lc"]
            cur["attributes"].update(plus.get("a") or {})
            for key in minus.get("a") or []:
                cur["attributes"].pop(key, None)
            changed.append(eid)
        for eid in ev.get("r") or []:
            self._states.pop(eid, None)
            changed.append(eid)
        for eid in changed:
            for listener in self._listeners:
                try:
                    listener(eid, self._states.get(eid))
                except Exception:
                    _LOGGER.exception("state listener failed")
