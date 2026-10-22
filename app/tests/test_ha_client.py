"""Rule G4 / AT-G4: the Home Assistant connection only runs commands a non-admin may run, from a fixed list."""

import pytest

from aikos_app.ha.client import ALLOWED_COMMANDS, ALLOWED_SERVICES, HaClient, HaError


def test_the_list_is_exactly_the_reviewed_one():
    # Each of these was checked in Home Assistant 2026.9.4: no admin-only decorator on its handler.
    assert ALLOWED_COMMANDS == {"get_states", "subscribe_entities", "history/history_during_period",
                                "media_source/browse_media", "media_source/resolve_media", "call_service"}
    assert ALLOWED_SERVICES == {("aikos", s) for s in (
        "door_messages", "door_message_delete", "door_message_heard",                       # step 2: the message register
        "bell_mute", "bell_unmute", "quiet_hours", "door_say", "door_say_cancel",          # step 3: the door actions
        "door_say_audio",                                                                  # voice messages (A49)
        "door_picture", "door_picture_clear", "door_greeting",
        "door_announcements")} | {("esphome", s) for s in (                          # the door announcements
        "aikos_intercom_talk_app_join", "aikos_intercom_talk_key_state")}                  # talking from the app (A5)


@pytest.mark.parametrize("command", ["config/auth/list", "auth/long_lived_access_token", "subscribe_events",
                                     "render_template", "execute_script", "fire_event"])
async def test_other_commands_never_leave_the_app(command):
    with pytest.raises(HaError, match="not allowed"):
        await HaClient("http://ha.invalid", "t").command(command)


@pytest.mark.parametrize("domain,service", [("homeassistant", "restart"), ("aikos", "store_media"), ("lock", "unlock"),
                                            ("aikos", None), (None, "door_messages")])
async def test_only_the_listed_services_are_called(domain, service):
    with pytest.raises(HaError, match="not allowed"):
        await HaClient("http://ha.invalid", "t").command("call_service", domain=domain, service=service)


@pytest.mark.parametrize("url", ["/api/config", "/local/other/x.png", "/local/aikos_door/../secrets.yaml", "/auth/token"])
async def test_only_local_media_links_and_the_door_picture_are_fetched(url):
    with pytest.raises(HaError):
        await HaClient("http://ha.invalid", "t").media(url)
