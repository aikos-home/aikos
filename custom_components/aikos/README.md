# aikos integration for Home Assistant

The household logic of aikos, installed via HACS. Version **0.1.0** (tag `aikos-v0.1.0`): quiet hours. More blocks follow (where the bell
rings, presence, "nobody home" notifications, alarm, pairing of devices); each comes as a new version.

## Install

1. HACS → Integrations → ⋮ → Custom repositories → `https://github.com/aikos-home/aikos`, type Integration → install **aikos**.
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → **aikos**. Nothing to type; aikos can be set up once.

## Interface

One device **aikos** (manufacturer `aikos-home`) with these entities. The ids are fixed English ids, the same in every house
and every Home Assistant language; the names follow the language (German: "Ruhezeit", "Ruhezeit Beginn", ...).

| Entity | What |
|---|---|
| `switch.aikos_quiet_hours` | Quiet hours on/off. Default: on |
| `time.aikos_quiet_hours_start` | Start, default 20:00 |
| `time.aikos_quiet_hours_end` | End, default 07:00 |
| `binary_sensor.aikos_quiet_hours` | Quiet hours active right now; attributes `start`, `end` (HH:MM). Switches exactly at start and end, no polling |

**The window:** from start (inclusive) to end (exclusive); it may run over midnight (20:00–07:00) or lie within one day
(13:00–15:00). Start = end means no quiet hours. During quiet hours the room keys give text only and don't ring;
emergencies pass (the keys do this themselves, so it also works while Home Assistant is down; handing the rule to the keys
comes with a later version).

**Settings** are stored in the integration's config entry, so they survive restarts and are in every Home Assistant backup.

## Errors

| Case | What happens |
|---|---|
| A stored time can't be read | The default is used (20:00 or 07:00) |
| Second "Add integration" | Refused: aikos is set up once |
| Integration removed | Its entities go away; nothing else in Home Assistant changes |

## Structure

| File | Job |
|---|---|
| `quiet_hours.py` | The time rules only (in window? next change?), no Home Assistant code |
| `settings.py` | Reads and stores the settings, tells the entities about changes |
| `entity.py` | What all aikos entities share (the device) |
| `switch.py`, `time.py`, `binary_sensor.py` | The entities |
| `config_flow.py`, `__init__.py` | Setting up and removing aikos |

## Tests

`tests/aikos/` in this repository, run in a real Home Assistant test instance
(Python 3.14, `pip install pytest-homeassistant-custom-component==0.13.367` = Home Assistant 2026.9.4, then `pytest tests/aikos`). CI job `integration-unit`.

## History

- 0.1.0: first version; quiet hours (moved here from the `homeassistant/` package, same `binary_sensor.aikos_quiet_hours`).
