"""The call archive in a real Home Assistant test instance: option on/off, order, test flag, devices, hostile text (R23)."""
import json
from pathlib import Path

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

DOMAIN = "aikos"
TCALL = "input_boolean.aikos_test_in_call"
MANIFEST_VERSION = json.loads((Path(__file__).parents[2] / "custom_components/aikos/manifest.json").read_text())["version"]


async def setup(hass: HomeAssistant, tmp_path: Path, archive: bool):
    hass.states.async_set(TCALL, "off")
    hass.states.async_set("binary_sensor.aikos_intercom_talk_in_call", "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()
    entry.runtime_data.archive.path = tmp_path / "aikos_archive" / "calls.jsonl"
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"call_archive": archive})
    await hass.async_block_till_done()
    return entry


def lines(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


async def test_archive_writes_start_message_end_in_order(hass: HomeAssistant, tmp_path: Path):
    entry = await setup(hass, tmp_path, archive=True)
    hostile = "Probelauf mit \"Anführungszeichen\", 'Hochkomma'; rm -rf / $(echo x) `id`"
    hass.states.async_set(TCALL, "on")
    await hass.async_block_till_done()
    hass.bus.async_fire("aikos_talk_transcript_test", {"side": "door", "speaker": "Paketdienst · DHL", "message": hostile, "text": hostile})
    await hass.async_block_till_done()
    hass.states.async_set(TCALL, "off")
    await hass.async_block_till_done()
    await entry.runtime_data.archive.async_flush()
    got = lines(entry.runtime_data.archive.path)
    assert [x["type"] for x in got] == ["call_start", "message", "call_end"]
    assert all(x["test"] is True for x in got) and len({x["call_id"] for x in got}) == 1
    assert {"name": "aikos", "model": "aikos", "sw": MANIFEST_VERSION} in got[0]["devices"]
    assert got[1]["message"] == hostile and isinstance(got[2]["duration_s"], (int, float))


async def test_archive_off_writes_nothing(hass: HomeAssistant, tmp_path: Path):
    entry = await setup(hass, tmp_path, archive=False)
    hass.states.async_set(TCALL, "on")
    await hass.async_block_till_done()
    hass.bus.async_fire("aikos_talk_transcript", {"side": "door", "text": "Hallo"})
    await hass.async_block_till_done()
    await entry.runtime_data.archive.async_flush()
    assert lines(entry.runtime_data.archive.path) == []


async def test_turning_the_archive_off_stops_writing(hass: HomeAssistant, tmp_path: Path):
    entry = await setup(hass, tmp_path, archive=True)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"call_archive": False})
    await hass.async_block_till_done()
    hass.bus.async_fire("aikos_talk_transcript", {"side": "door", "text": "Hallo"})
    await hass.async_block_till_done()
    await entry.runtime_data.archive.async_flush()
    assert lines(entry.runtime_data.archive.path) == []
