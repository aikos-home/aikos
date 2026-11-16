"""Who talks to the door from the aikos app right now (A5, A49: the app as a room key), for the transcriber.

The transcriber names the sender of an utterance by the `sensor.*_ip_address` entity whose state is the sender's IP (its
friendly name without " IP address"); `sensor.aikos_app_talker_ip_address` is that entity for the app: state = the app
node's address while someone is in the call from the app, friendly name "<person> IP address". The aikos app sets
it with `aikos.app_talker {ip, name}` when someone joins, and clears it when they leave. No Home Assistant imports.
"""
from __future__ import annotations

from collections.abc import Callable

KEY = "aikos_app_talker"
"""The transcriber's `key_id` for what is said from the app (the entity's object id without `_ip_address`)."""
NAME_MAX = 60


class AppTalker:
    def __init__(self) -> None:
        self.ip = ""
        self.name = ""
        self._listeners: list[Callable[[], None]] = []

    def set(self, ip: str, name: str) -> None:
        ip, name = ip.strip(), " ".join(name.split())[:NAME_MAX]
        if (ip, name) == (self.ip, self.name):
            return
        self.ip, self.name = ip, name if ip else ""
        for update in list(self._listeners):
            update()

    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)
