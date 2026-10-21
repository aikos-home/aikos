"""Parcels expected today, from the carriers' mails in one mailbox (sprachausgabe S14/S15): `binary_sensor.aikos_parcel_expected`.

Every POLL aikos logs in to the mailbox (IMAP over TLS, an app password; options "Parcel mails"), searches the inbox for
today's mails from the carriers' domains only (parcel_rules.CARRIERS) and reads their sender, subject and date, nothing
else: no text, no other mail, nothing is marked as read. The rules (parcel_rules.py) say whether a parcel is still
expected. The whole day is read again each time, so a missed moment costs nothing. Nothing leaves the house but the
connection to the mail server itself.

Mailbox unreachable or the login refused: the sensor keeps its last answer (and says why in `error`); at midnight it is off.
"""
from __future__ import annotations

import imaplib
import logging
import ssl
from collections.abc import Callable
from datetime import date, datetime, timedelta
from email import policy
from email.parser import BytesHeaderParser
from email.utils import parsedate_to_datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import OPT_MAIL_PASSWORD, OPT_MAIL_SERVER, OPT_MAIL_USER
from .parcel_rules import CARRIERS, Expectation, Notice, classify, expectation

_LOGGER = logging.getLogger(__name__)
POLL = timedelta(minutes=3)
TIMEOUT = 20
MAX_MAILS = 200
DEFAULT_SERVER = "imap.gmail.com"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class MailError(Exception):
    """`login` (refused), `connect` (server not reachable) or `search` (the server didn't answer as expected)."""


def search_criteria(since: date) -> str:
    """IMAP SEARCH: mails since that day from any carrier domain (a subdomain matches too)."""
    froms = [f'FROM "{d}"' for d in CARRIERS]
    tree = froms[0]
    for f in froms[1:]:
        tree = f"OR {tree} {f}"
    return f"SINCE {since.day:02d}-{_MONTHS[since.month - 1]}-{since.year} {tree}"


def _connect(server: str, user: str, password: str) -> imaplib.IMAP4_SSL:
    try:
        box = imaplib.IMAP4_SSL(server, 993, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    except (OSError, imaplib.IMAP4.error) as e:
        raise MailError("connect") from e
    try:
        box.login(user, password)
    except imaplib.IMAP4.error as e:
        box.shutdown()
        raise MailError("login") from e
    return box


def check_login(server: str, user: str, password: str) -> None:
    """For the options form: raises MailError if this mailbox can't be opened."""
    box = _connect(server, user, password)
    try:
        box.logout()
    except (OSError, imaplib.IMAP4.error):
        pass


def fetch(server: str, user: str, password: str, since: date) -> list[tuple[str, str, datetime]]:
    """(sender domain, subject, date) of the carriers' mails since that day. Runs in an executor."""
    box = _connect(server, user, password)
    try:
        typ, _ = box.select("INBOX", readonly=True)
        if typ != "OK":
            raise MailError("search")
        typ, data = box.uid("SEARCH", None, search_criteria(since))
        if typ != "OK":
            raise MailError("search")
        uids = (data[0] or b"").split()[-MAX_MAILS:]
        if not uids:
            return []
        typ, data = box.uid("FETCH", b",".join(uids).decode(), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if typ != "OK":
            raise MailError("search")
    except (OSError, imaplib.IMAP4.error) as e:
        raise MailError("search") from e
    finally:
        try:
            box.logout()
        except (OSError, imaplib.IMAP4.error):
            pass
    out = []
    parser = BytesHeaderParser(policy=policy.default)
    for part in data:
        if not isinstance(part, tuple) or len(part) < 2:
            continue
        try:
            msg = parser.parsebytes(part[1])
            sender = msg["from"]
            domain = sender.addresses[0].domain if sender and sender.addresses else ""
            when = parsedate_to_datetime(str(msg["date"]))
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        out.append((domain, str(msg["subject"] or ""), when))
    return out


class ParcelMail:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self.state = Expectation()
        self.checked = ""
        """When the mailbox was last read (ISO)."""
        self.error = ""
        self.notices: list[Notice] = []
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    @property
    def configured(self) -> bool:
        o = self._entry.options
        return bool(o.get(OPT_MAIL_USER) and o.get(OPT_MAIL_PASSWORD))

    @callback
    def start(self) -> None:
        self.stop()
        if not self.configured:
            self._set([], "", "")
            return
        self._unsubs.append(async_track_time_interval(self._hass, self._tick, POLL))
        self._unsubs.append(async_track_time_change(self._hass, self._midnight, hour=0, minute=0, second=5))
        self._entry.async_create_background_task(self._hass, self.async_poll(), "aikos parcel mail")

    @callback
    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _tick(self, _now: datetime) -> None:
        self._entry.async_create_background_task(self._hass, self.async_poll(), "aikos parcel mail")

    @callback
    def _midnight(self, _now: datetime) -> None:
        self._set([], self.checked, self.error)   # a new day: yesterday's parcels are over
        self._tick(_now)

    @callback
    def _set(self, notices: list[Notice], checked: str, error: str) -> None:
        self.notices = notices
        self.state = expectation(notices, dt_util.now())
        self.checked, self.error = checked, error
        for update in list(self._listeners):
            update()

    async def async_poll(self) -> None:
        o = self._entry.options
        now = dt_util.now()
        since = now.date() - timedelta(days=1)   # the server may count days in another zone; the rules keep only today
        try:
            mails = await self._hass.async_add_executor_job(
                fetch, o.get(OPT_MAIL_SERVER) or DEFAULT_SERVER, o[OPT_MAIL_USER], o[OPT_MAIL_PASSWORD], since)
        except MailError as e:
            if str(e) != self.error:
                _LOGGER.warning("aikos: parcel mails not read (%s)", e)
            self._set(self.notices, self.checked, str(e))
            return
        notices = [n for d, s, at in mails if (n := classify(d, s, at)) is not None]
        self._set(notices, now.isoformat(timespec="seconds"), "")
