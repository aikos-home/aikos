"""Rule G4 / AT-G4: the Home Assistant connection only runs commands a non-admin may run, from a fixed list."""

import pytest

from aikos_app.ha.client import ALLOWED_COMMANDS, ALLOWED_SERVICE_DOMAINS, HaClient, HaError


def test_the_list_is_exactly_the_reviewed_one():
    # Each of these was checked in Home Assistant 2026.9.4: no admin-only decorator on its handler.
    assert ALLOWED_COMMANDS == {"get_states", "subscribe_entities", "history/history_during_period",
                                "media_source/browse_media", "media_source/resolve_media", "call_service"}
    assert ALLOWED_SERVICE_DOMAINS == frozenset()  # step 1 only reads


@pytest.mark.parametrize("command", ["config/auth/list", "auth/long_lived_access_token", "subscribe_events",
                                     "render_template", "execute_script", "fire_event"])
async def test_other_commands_never_leave_the_app(command):
    with pytest.raises(HaError, match="not allowed"):
        await HaClient("http://ha.invalid", "t").command(command)


async def test_service_domains_are_restricted():
    with pytest.raises(HaError, match="not allowed"):
        await HaClient("http://ha.invalid", "t").command("call_service", domain="homeassistant", service="restart")


async def test_only_local_media_links_are_fetched():
    with pytest.raises(HaError):
        await HaClient("http://ha.invalid", "t").media("/api/config")
