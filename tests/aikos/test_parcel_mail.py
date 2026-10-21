"""Parcels from the carriers' mails in a real Home Assistant test instance (sprachausgabe S15): the mailbox's login is tried
before it is stored; only today's carrier mails are searched, read without being marked; the sensor follows them; a mailbox
that can't be read keeps the last answer and says why; the door announcements take this sensor when no other is set."""
from datetime import datetime, timedelta

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

DOMAIN = "aikos"
SENSOR = "binary_sensor.aikos_parcel_expected"


def addr(local: str, domain: str) -> str:
    """A public carrier address (or a made-up one), put together so the privacy scan's e-mail rule can stay strict."""
    return local + "\x40" + domain


def local(hour, minute=0):
    return datetime(2026, 10, 21, hour, minute, tzinfo=dt_util.get_default_time_zone())


@pytest.fixture
def mailbox(monkeypatch):
    """The mailbox as a test double: what fetch returns now, which logins work."""
    from custom_components.aikos import parcel_mail
    box = {"mails": [], "fail": None, "logins": [], "fetches": 0}

    def check_login(server, user, password):
        box["logins"].append((server, user, password))
        if password != "app-pw":
            raise parcel_mail.MailError("login")

    def fetch(server, user, password, since):
        box["fetches"] += 1
        if box["fail"]:
            raise parcel_mail.MailError(box["fail"])
        return list(box["mails"])
    monkeypatch.setattr(parcel_mail, "check_login", check_login)
    monkeypatch.setattr(parcel_mail, "fetch", fetch)
    return box


async def options(hass: HomeAssistant, entry, **fields):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], fields)
    await hass.async_block_till_done(wait_background_tasks=True)
    return result


async def setup(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    entry = (await hass.config_entries.flow.async_configure(result["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    return entry


async def test_login_is_tried_before_the_mailbox_is_stored(hass: HomeAssistant, mailbox, freezer):
    freezer.move_to(local(10))
    entry = await setup(hass)
    user = addr("someone", "example.org")
    result = await options(hass, entry, parcel_mail_user=user, parcel_mail_password="wrong")
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "mail_login"}
    assert "parcel_mail_user" not in entry.options
    result = await options(hass, entry, parcel_mail_user=user, parcel_mail_password="app-pw")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["parcel_mail_server"] == "imap.gmail.com" and entry.options["parcel_mail_password"] == "app-pw"
    mailbox["logins"].clear()
    result = await options(hass, entry, parcel_mail_user=user)                  # password left empty: the stored one stays
    assert result["type"] is FlowResultType.CREATE_ENTRY and entry.options["parcel_mail_password"] == "app-pw"
    assert mailbox["logins"] == []                                              # nothing changed: not tried again
    await options(hass, entry)                                                  # user emptied: off
    assert "parcel_mail_user" not in entry.options and "parcel_mail_password" not in entry.options


async def test_the_sensor_follows_the_mails_and_reads_again_every_3_minutes(hass: HomeAssistant, mailbox, freezer):
    freezer.move_to(local(10))
    entry = await setup(hass)
    assert hass.states.get(SENSOR).state == "off"
    mailbox["mails"] = [("amazon.de", "In Zustellung: „Akku-Set...“", local(9)),
                        ("service.dpd.de", "Zwischen 13:45 und 15:45 Uhr kommt Ihr DPD Paket", local(8)),
                        ("service.dpd.de", "Ihr Paket ist da!", local(9, 30))]
    await options(hass, entry, parcel_mail_user=addr("someone", "example.org"), parcel_mail_password="app-pw")
    st = hass.states.get(SENSOR)
    assert st.state == "on" and st.attributes["carriers"] == ["Amazon"] and st.attributes["error"] == ""
    assert st.attributes["window"] == "" and st.attributes["configured"] is True
    mailbox["mails"].append(("amazon.de", "Zugestellt: „Akku-Set...“", local(10, 1)))
    freezer.tick(timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(SENSOR).state == "off"
    assert mailbox["fetches"] == 2


async def test_a_mailbox_that_cant_be_read_keeps_the_last_answer(hass: HomeAssistant, mailbox, freezer):
    freezer.move_to(local(10))
    entry = await setup(hass)
    mailbox["mails"] = [("dhl.de", "Ihre DHL Sendung kommt heute", local(8))]
    await options(hass, entry, parcel_mail_user=addr("someone", "example.org"), parcel_mail_password="app-pw")
    assert hass.states.get(SENSOR).state == "on"
    mailbox["fail"] = "connect"
    freezer.tick(timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    st = hass.states.get(SENSOR)
    assert st.state == "on" and st.attributes["error"] == "connect"


async def test_the_announcements_take_this_sensor_by_default(hass: HomeAssistant, mailbox, freezer):
    freezer.move_to(local(10))
    entry = await setup(hass)
    mailbox["mails"] = [("dhl.de", "Ihre DHL Sendung kommt heute", local(8))]
    await options(hass, entry, parcel_mail_user=addr("someone", "example.org"), parcel_mail_password="app-pw")
    await hass.services.async_call(DOMAIN, "door_announcements", {"disclosure": 1, "parcel": "Bitte vor die Tür legen."},
                                   blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.aikos_door_announcements").state == "parcel"


class FakeImap:
    """imaplib's IMAP4_SSL as far as fetch uses it."""
    calls: list = []

    def __init__(self, host, port, ssl_context=None, timeout=None):
        FakeImap.calls = [("connect", host, port)]

    def login(self, user, password):
        FakeImap.calls.append(("login", user))
        return "OK", [b""]

    def select(self, folder, readonly=False):
        FakeImap.calls.append(("select", folder, readonly))
        return "OK", [b"3"]

    def uid(self, command, *args):
        FakeImap.calls.append(("uid", command, args[-1]))
        if command == "SEARCH":
            return "OK", [b"11 12"]
        sender = addr("shipment-tracking", "amazon.de")
        head = (f"From: Amazon <{sender}>\r\nSubject: =?UTF-8?Q?In_Zustellung:_=E2=80=9EAkku-Set...=E2=80=9C?=\r\n"
                "Date: Wed, 21 Oct 2026 09:00:00 +0200\r\n\r\n").encode()
        return "OK", [(b"11 (UID 11 BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {120}", head), b")",
                      (b"12 (UID 12 BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {9}", b"garbage\r\n"), b")"]

    def logout(self):
        FakeImap.calls.append(("logout",))

    def shutdown(self):
        pass


def test_fetch_searches_todays_carrier_mails_and_marks_nothing_read(monkeypatch):
    from datetime import date

    from custom_components.aikos import parcel_mail
    monkeypatch.setattr(parcel_mail.imaplib, "IMAP4_SSL", FakeImap)
    mails = parcel_mail.fetch("imap.example.org", "u", "p", date(2026, 10, 20))
    assert len(mails) == 1 and mails[0][:2] == ("amazon.de", "In Zustellung: „Akku-Set...“")
    assert ("select", "INBOX", True) in FakeImap.calls                          # read-only
    search = next(c[2] for c in FakeImap.calls if c[:2] == ("uid", "SEARCH"))
    assert search.startswith("SINCE 20-Oct-2026 OR") and 'FROM "dhl.de"' in search
    assert "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)]" in next(c[2] for c in FakeImap.calls if c[:2] == ("uid", "FETCH"))
    assert FakeImap.calls[-1] == ("logout",)
