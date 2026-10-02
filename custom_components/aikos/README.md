# aikos integration for Home Assistant

The household logic of aikos, installed via HACS. Version **0.4.1** (tag `aikos-v0.4.1`): quiet hours (0.1.0), the ring push (0.2.0, tag `aikos-v0.2.0`), the call log (0.3.0) and the call archive. More blocks follow (where the bell
rings, presence, alarm, pairing of devices); each comes as a new version.

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

### Ring push (0.2.0)

Settings → Devices & services → aikos → **Configure**:

| Option | What |
|---|---|
| Doorbell | The doorbell's `event` entity (a new timestamp = a press), or a `binary_sensor` that turns on when pressed |
| Residents | HA persons. "Nobody home" = none of them is `home` (unknown counts as away) |
| Phones | Notify services, e.g. the mobile app's service `mobile_app_<phone>` |

On a press, aikos sends **"Es hat geklingelt (22:14) · Ruhezeit"** (English if Home Assistant is not set to German) to every phone
when quiet hours are active, or **"… · niemand zu Hause"** when nobody is home. Otherwise nothing.
- Storm ringing and quick repeats give one push per 30 s.
- A device coming back online (unavailable → its last press) is no press.
- Without a doorbell or phones there is no push (default).

### Call log (0.3.0)

The only source of the chat on the door screen and the room keys. Moved here from the `homeassistant/` package without changing
what the devices read.

| Entity | What |
|---|---|
| `sensor.aikos_call_log` | State = time of the newest message. Attributes `call_id`, `active`, `last_id`, `messages` (≤ 20), `messages_json` |
| `sensor.aikos_call_log_test` | The same for bench tests, fed only by `sensor.talk_transcript_test` / `_door_test`, `input_boolean.aikos_test_in_call` and `input_button.aikos_test_new_call` |

- **Sources (live):** `sensor.talk_transcript` (room), `sensor.talk_transcript_door` (door), `binary_sensor.aikos_intercom_talk_in_call`.
- **Per message:** `id` (side + transcript time), `t`, `side` (`door`/`room`), `who`, `role`, `text` (≤ 300 characters), `urgent`, `lang`
  (language name if not German), `spk` (the speaker the transcript named), `dev` (room key), `sticky`.
- **Contract for the devices:** `messages_json` = the newest 10 messages, oldest first, compact JSON text; every message has `id`,
  `side`, `who`, `text`. Changes only through the change path; new fields may be added.
- **R22:** emptied when a call starts and when it ends; a transcript outside a call is not added. **R25:** a visitor's identity
  holds for the call (`sticky`). **R26:** a resident's name holds per room key, never for another key. **R27:** devices get 10.
- A later update of the same transcript replaces the message. Every new message fires the event `aikos_call_message` and writes
  a logbook entry (live log only).
- Survives a restart (the last state is restored).



| Case | What happens |
|---|---|
| A stored time can't be read | The default is used (20:00 or 07:00) |
| A configured phone's notify service doesn't exist (any more) | Warning in the log; the other phones still get the push |
| A notify service fails | Logged; the others still get it, the integration keeps running |
| The archive file can't be written | Logged; calls and everything else go on |
| Second "Add integration" | Refused: aikos is set up once |
| Integration removed | Its entities go away; nothing else in Home Assistant changes |

## Structure

| File | Job |
|---|---|
| `quiet_hours.py` | The time rules only (in window? next change?), no Home Assistant code |
| `settings.py` | Reads and stores the settings, tells the entities about changes |
| `entity.py` | What all aikos entities share (the device) |
| `switch.py`, `time.py`, `binary_sensor.py` | The entities |
| `ring_push.py` | When a press becomes a push, and its text (no Home Assistant code) |
| `ring_notifier.py` | Watches the doorbell and sends the push |
| `call_log.py` | The call-log rules (R22, R25–R27), no Home Assistant code |
| `sensor.py` | The call log sensors, event and logbook |
| `call_archive.py` | The archive's lines (no Home Assistant code) |
| `archive_writer.py` | Listens to calls and transcripts, appends the lines |
| `config_flow.py`, `__init__.py` | Setting up and removing aikos |

## Tests

`tests/aikos/` in this repository, run in a real Home Assistant test instance
(Python 3.14, `pip install pytest-homeassistant-custom-component==0.13.367` = Home Assistant 2026.9.4, then `pytest tests/aikos`). CI job `integration-unit`.

## History

- 0.4.1: the archive reads the device registry the supported way (no deprecation warning; would have stopped working in HA 2027.9).
- 0.4.0: the call archive moves here from the package (an option instead of File integration + allowlist; same file and lines,
  plus the integration's own version in `call_start`).
- 0.3.0: the call log moves here from the `homeassistant/` package (same entity ids and attributes; the Jinja macro is gone).
- 0.2.0: ring push to the residents' phones during quiet hours or when nobody is home (requirements 1 and 3,
  `features/klingelregeln.md` KR-R3, KR-R12); options flow for doorbell, residents, phones. Quiet hours unchanged.
- 0.1.0: first version; quiet hours (moved here from the `homeassistant/` package, same `binary_sensor.aikos_quiet_hours`).
