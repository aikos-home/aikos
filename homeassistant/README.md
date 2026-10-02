# Home Assistant stand-ins

What aikos adds to Home Assistant and the [integration](../custom_components/aikos/README.md) doesn't do yet, as plain HA
configuration. Parts move into the integration step by step (quiet hours 0.1.0, call log 0.3.0, call archive 0.4.0).
It is the source of truth: deploy from here, don't edit the copies in Home Assistant.

| File | Goes to (HA config dir) | What |
|---|---|---|
| `packages/aikos.yaml` | `packages/aikos.yaml` | Generic part, the same for every house |
| `packages/aikos_local.example.yaml` | `packages/aikos_local.yaml` | House-specific values; copy, then fill in |
| `tests/test_call_log.py` | stays here | Acceptance test of the call log (now in the integration) against a running HA, test entities only |

Needs `homeassistant: packages: !include_dir_named packages` in `configuration.yaml`.
After changes: reload `template`, `script`, `automation`, `shell_command` and the `input_*` helpers; no restart needed except
for the very first `shell_command`.

## What the devices can read

| Entity | Meaning |
|---|---|
| `binary_sensor.aikos_front_door` | Front door open, 2 s debounced. Source = the entity named in `input_text.aikos_front_door_source`. Attribute `stuck`: open for more than 10 min (then it ends nothing). Devices only react to an off → on edge. |
| `binary_sensor.aikos_test_doorbell` | **Test only:** on for 1 s when `input_button.aikos_test_doorbell` is pressed. A stand-in doorbell for bench tests of the aikos ring push. |
| `binary_sensor.aikos_quiet_hours` | Quiet hours active. **Moved into the aikos integration** (0.1.0, [README](../custom_components/aikos/README.md)); same entity id. |
| `sensor.aikos_people` | From `aikos_local.yaml`. Attribute `keys` (and `keys_json` as text for ESPHome): room key node name → `{name, room, host}`. |
| `sensor.aikos_call_log` | The only source of the chat on both screens. **Now provided by the aikos integration** (0.3.0), same entity id and attributes; the rules (R22, R25–R27) and the contract are in the [integration README](../custom_components/aikos/README.md). `sensor.aikos_call_log_test` is its bench twin, fed only by the `*_test` transcripts and `input_boolean.aikos_test_in_call`. |

**Stable for devices (contract):** the door screen and the talk computer read `messages_json` (per message `id`, `side`
`door`/`room`, `who`, `text`; for a visitor `who` is the recognised role, empty shows as "Besucher") and `keys_json`
(per key `host`, `name`). These fields change only through the change path (`qualitaet.md` §3, new fields may be added);
`tests/test_call_log.py` checks them.

The log reads the transcript sensors `sensor.talk_transcript` (room side) and `sensor.talk_transcript_door` (door side)
written by the transcriber service, and the door call sensor `binary_sensor.aikos_intercom_talk_in_call`.

## Call archive (R23)

**Moved into the aikos integration (0.4.0):** turn on "Call archive" in aikos → Configure. Same file
(`<config>/aikos_archive/calls.jsonl`) and the same lines as before; no File integration and no `allowlist_external_dirs` needed
any more. `tests/test_call_archive.py` still checks it against a running HA.

## Tests never touch live entities

`sensor.aikos_call_log_test` (aikos integration) runs exactly the same rules, fed only by `sensor.talk_transcript_test` /
`sensor.talk_transcript_door_test`; `input_button.aikos_test_new_call` starts a new test call. The transcriber sends
utterances from its test sources there. `tests/test_call_log.py` uses only these:

```
AIKOS_HA_URL=http://<ha-host>:8123 AIKOS_HA_TOKEN_FILE=<file with a long-lived token> python homeassistant/tests/test_call_log.py
```

## "Restart all"

`script.aikos_restart_all` restarts the AI services (`shell_command.aikos_restart_services` from `aikos_local.yaml`), then
every aikos device except the bell, waits until they are back, then the bell. Devices are found by their ESPHome project
(`aikos-home`), and only real restart buttons are pressed, never a factory reset. Field `probelauf: true` = dry run.
