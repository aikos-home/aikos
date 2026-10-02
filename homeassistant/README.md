# Home Assistant stand-ins

Until the `aikos` integration exists, this folder holds what aikos adds to Home Assistant, as plain HA configuration.
It is the source of truth: deploy from here, don't edit the copies in Home Assistant.

| File | Goes to (HA config dir) | What |
|---|---|---|
| `packages/aikos.yaml` | `packages/aikos.yaml` | Generic part, the same for every house |
| `packages/aikos_local.example.yaml` | `packages/aikos_local.yaml` | House-specific values; copy, then fill in |
| `custom_templates/aikos_call_log.jinja` | `custom_templates/aikos_call_log.jinja` | The call-log logic (one macro, used by the live and the test log) |
| `tests/test_call_log.py` | stays here | Acceptance test against a running HA, test entities only |

Needs `homeassistant: packages: !include_dir_named packages` in `configuration.yaml`.
After changes: reload `template`, `script`, `automation`, `shell_command`, the `input_*` helpers and custom templates
(`homeassistant.reload_custom_templates`); no restart needed except for the very first `shell_command`.

## What the devices can read

| Entity | Meaning |
|---|---|
| `binary_sensor.aikos_front_door` | Front door open, 2 s debounced. Source = the entity named in `input_text.aikos_front_door_source`. Attribute `stuck`: open for more than 10 min (then it ends nothing). Devices only react to an off → on edge. |
| `binary_sensor.aikos_quiet_hours` | Quiet hours active (`input_boolean.aikos_quiet_hours_enabled`, `input_datetime.aikos_quiet_hours_start` / `_end`; the window may wrap midnight). During quiet hours rooms get text only; emergencies pass. |
| `sensor.aikos_people` | From `aikos_local.yaml`. Attribute `keys` (and `keys_json` as text for ESPHome): room key node name → `{name, room, host}`. |
| `sensor.aikos_call_log` | The only source of the chat on both screens. State = time of the last message. Attributes `call_id`, `active`, `last_id`, `messages` (≤ 20: `id, t, side, who, role, text, urgent, lang`, plus `spk` (the speaker the transcript named), `dev` (room key) and `sticky` (true when `who` was carried over: a visitor's identity holds for the whole call, R25; a resident's name holds per room key, never for another key, R26)) and `messages_json` (text for ESPHome: **only the newest 10 messages**, oldest first, R27; devices keep the chat only for the running call, the full call goes to the archive, R23; an empty log may arrive as `[]`). A call's chat is emptied when the call **ends** (door call sensor on → off), and a transcript that arrives while no call runs is not added (R22: a screen must never show the previous call's chat, not even for a moment). A new call starts empty. A later update of the same transcript (e.g. the language) replaces the message instead of adding one. Every new message also fires the event `aikos_call_message` and writes a logbook entry. |

**Stable for devices (contract):** the door screen and the talk computer read `messages_json` (per message `id`, `side`
`door`/`room`, `who`, `text`; for a visitor `who` is the recognised role, empty shows as "Besucher") and `keys_json`
(per key `host`, `name`). These fields change only through the change path (`qualitaet.md` §3, new fields may be added);
`tests/test_call_log.py` checks them.

The log reads the transcript sensors `sensor.talk_transcript` (room side) and `sensor.talk_transcript_door` (door side)
written by the transcriber service, and the door call sensor `binary_sensor.aikos_intercom_talk_in_call`.

## Call archive (optional, R23)

A full archive of every call for development: one JSON line per event in `/config/aikos_archive/calls.jsonl`:
`call_start` (with name, model and firmware version of every device whose manufacturer is `aikos-home`), every transcript
(`message`: time, side, speaker, role, urgency, message, text, original language, device, latency, transcriber version if the
transcriber sends one) and `call_end` (with duration). Test traffic is in the same file, marked `"test": true`. Devices keep
only the newest messages (R27); the archive keeps everything until you delete it. It holds what visitors said: keep it local.

**Off unless you set it up** (the automation fails quietly without the notify entity):
1. `configuration.yaml`: `homeassistant: allowlist_external_dirs: [/config/aikos_archive]` and create that folder (never
   `/config/www`: Home Assistant serves it without login). Restart.
2. Settings → Devices & services → Add integration → **File** → Notification service → file path
   `/config/aikos_archive/calls.jsonl`, no timestamp.
3. Rename the new entity to `notify.aikos_call_archive`.

The archive is written by the File integration, never by a shell, so text a visitor said can never become a command
(`tests/test_call_archive.py` sends quotes and shell syntax and checks they are stored verbatim).

## Tests never touch live entities

`sensor.aikos_call_log_test` runs exactly the same macro, fed only by `sensor.talk_transcript_test` /
`sensor.talk_transcript_door_test`; `input_button.aikos_test_new_call` starts a new test call. The transcriber sends
utterances from its test sources there. `tests/test_call_log.py` uses only these:

```
AIKOS_HA_URL=http://<ha-host>:8123 AIKOS_HA_TOKEN_FILE=<file with a long-lived token> python homeassistant/tests/test_call_log.py
```

## "Restart all"

`script.aikos_restart_all` restarts the AI services (`shell_command.aikos_restart_services` from `aikos_local.yaml`), then
every aikos device except the bell, waits until they are back, then the bell. Devices are found by their ESPHome project
(`aikos-home`), and only real restart buttons are pressed, never a factory reset. Field `probelauf: true` = dry run.
