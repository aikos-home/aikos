# aikos

Home Assistant integration and shared device components of **aikos**, an open-source home system made of a door station
([intercom](https://github.com/aikos-home/intercom)) and room keys ([roomkey](https://github.com/aikos-home/roomkey)).

> **Status: skeleton.** Nothing here is installable yet. The integration will be published via HACS.

## What lives here

| Path | What | Maintained by |
|---|---|---|
| `custom_components/aikos/` | Home Assistant integration (HACS): where the doorbell rings, quiet hours, presence, "nobody home" notifications, alarm panel with per-key rights, activity log | aikos core |
| `esphome/components/` | ESPHome components shared by the devices, e.g. `aikos_voice` (intercom audio) | intercom and roomkey maintainers, jointly |
| `services/transcriber/` | Speech to text for Home Assistant, locally: what residents and visitors say, who is speaking, translation ([README](services/transcriber/README.md)) | aikos core; logic: roomkey maintainers |
| `homeassistant/` | Home Assistant stand-ins until the integration exists: package, call-log macro, acceptance test | aikos core |
| `docs/` | System documentation: architecture, installation, building the devices | aikos core |
| `tools/` | Checks used by all aikos repositories (privacy scan) | aikos core |

The devices themselves (firmware, hardware, product design) live in their own repositories.

## Principles

- **Devices first.** Door station and room keys are standard ESPHome devices with good entities and work on their own.
  The integration adds the household logic on top; it is installed via HACS, not hand-written automations.
- **The doorbell is designed to ring without Home Assistant.** Every press goes to Home Assistant and directly to the room
  keys at the same time, so a Home Assistant restart doesn't silence the bell.
- **No cloud.** Audio and transcripts stay in the house. A visitor's voice is stored only if they choose
  "leave a message".
- **No camera.** The door station has none, in any version.
- **Portable.** Nothing in this code knows a particular house; everything comes from the setup in Home Assistant.

## Using shared ESPHome components (once released)

Components are pinned by tag, so a device never picks up an unreviewed change:

```yaml
external_components:
  - source: github://aikos-home/aikos@<tag>
    components: [aikos_voice]
```

## Privacy

Every push runs `tools/privacy_scan.py` (CI: built-in checks for private IP addresses, MAC addresses, e-mail addresses and
Home Assistant entity ids). A private denylist of personal terms is checked locally before each push and is never committed.

## Licences

Code: [MIT](LICENSE). Documentation: CC BY 4.0. Hardware lives in the device repositories (CERN-OHL-P-2.0).
